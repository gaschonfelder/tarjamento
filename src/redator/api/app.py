"""A API que serve a interface de revisão.

**Esta API devolve o valor real dos dados pessoais que detecta.** É o que a
interface mostra no hover, por baixo da tarja, para quem revisa decidir se a
detecção está certa. Sem isso não há revisão — mas é um endpoint que serve
CPF, e-mail e RG em texto claro, e o resto do módulo é construído em torno
disso:

- **nenhum CORS.** Não há ``CORSMiddleware`` aqui, e não deve haver: qualquer
  origem liberada é uma página de terceiro capaz de ler o conteúdo de um
  documento em revisão;
- **bind em loopback por default** (:data:`redator.api.config.HOST_PADRAO`).
  Rede interna exige ``REDATOR_API_HOST`` escrito à mão por quem opera;
- **nenhuma resposta é cacheável.** ``Cache-Control: no-store`` em tudo, para
  que o dado não sobreviva ao TTL dentro de um cache de navegador ou proxy;
- **nada é retido.** Todo job morre no TTL ou no DELETE, o que vier primeiro.

Para subir::

    uv run uvicorn redator.api.app:app
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from rq import Queue
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from ..detectors import TODOS_DETECTORES
from ..entities import Entity
from ..pdf.pipeline import process_pdf
from ..perfil import AcaoRedacao, EntidadeComAcao
from ..redacao import BBox, redigir_pdf
from .config import Config
from .jobs import criar_fila, enfileirar, extrair
from .schemas import (
    AcaoDecisao,
    DecisaoEntidade,
    ExportarRequest,
    JobResponse,
    JobStatus,
    PaginaResponse,
)
from .storage import Armazenamento, ErroLimpeza, novo_job_id

__all__ = ["app", "criar_app", "servir"]

_log = logging.getLogger(__name__)

#: Assinatura de PDF. A checagem é de conteúdo, não de extensão nem de
#: ``content-type``: os dois vêm do cliente e não valem nada.
_MAGIC_PDF = b"%PDF-"

#: Tamanho de leitura do upload. O corpo é lido em pedaços justamente para o
#: limite de tamanho poder interromper antes de a coisa toda estar na memória.
_PEDACO = 64 * 1024


def _sem_cache(resposta: Response) -> Response:
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    return resposta


async def _ler_limitado(arquivo: UploadFile, maximo: int) -> bytes:
    """Lê o upload inteiro, abortando assim que passar de ``maximo`` bytes."""
    pedacos: list[bytes] = []
    total = 0
    while pedaco := await arquivo.read(_PEDACO):
        total += len(pedaco)
        if total > maximo:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"arquivo acima do maximo de {maximo} bytes",
            )
        pedacos.append(pedaco)
    return b"".join(pedacos)


def _entidades_conhecidas(
    caminho_pdf: Path, paginas: list[PaginaResponse]
) -> dict[str, tuple[int, Entity]]:
    """O ``Entity`` real por trás de cada id do resultado original.

    O servidor nunca persistiu um ``Entity`` — só o ``EntidadeResponse``
    convertido (Fase 3), sem ``start``/``end``. Para recuperar um span de
    texto que ``redigir_pdf`` consiga usar, este reprocessa ``caminho_pdf``
    do zero: mesmo roteamento de extração do job (:func:`extrair`, nativo ou
    OCR) e os mesmos detectores (``TODOS_DETECTORES``) sobre um arquivo
    imutável produzem, deterministicamente, a MESMA lista de entidades, na
    MESMA ordem, que gerou ``resultado.json`` da primeira vez. Zipar essa
    lista fresca com os ``EntidadeResponse`` armazenados (mesma ordem de
    origem) devolve o ``Entity`` de cada id sem o servidor ter guardado um
    único.

    Uma divergência de tamanho ou de tipo entre as duas listas significa que
    esta premissa quebrou — o PDF do job mudou por fora, ou o reprocessamento
    não é mais determinístico — e é erro do servidor, não do cliente: nunca
    é seguro tarjar com base num mapeamento que pode estar errado.
    """
    documento = extrair(caminho_pdf)
    frescas = process_pdf(
        caminho_pdf, list(TODOS_DETECTORES), extrator=lambda _: documento
    )
    conhecidas: dict[str, tuple[int, Entity]] = {}
    for pagina in paginas:
        entidades_frescas = frescas.get(pagina.numero, [])
        if len(entidades_frescas) != len(pagina.entidades):
            raise RuntimeError(
                f"reprocessamento da pagina {pagina.numero} do job produziu "
                f"{len(entidades_frescas)} entidade(s), resultado original "
                f"tinha {len(pagina.entidades)} — nao e seguro exportar"
            )
        for resposta, entidade in zip(pagina.entidades, entidades_frescas, strict=True):
            if entidade.type.name != resposta.type:
                raise RuntimeError(
                    f"reprocessamento da pagina {pagina.numero} do job diverge "
                    f"do resultado original ({entidade.type.name} != "
                    f"{resposta.type}) — nao e seguro exportar"
                )
            conhecidas[resposta.id] = (pagina.numero, entidade)
    return conhecidas


def _montar_redacao(
    decisoes: list[DecisaoEntidade],
    conhecidas: dict[str, tuple[int, Entity]],
    paginas_validas: set[int],
) -> tuple[dict[int, list[EntidadeComAcao]], dict[int, list[BBox]]]:
    """Valida as decisões e monta o que ``redigir_pdf`` precisa.

    Toda entidade de ``conhecidas`` (o resultado original) precisa de uma
    decisão — a ausência não vira default nenhum, porque omissão pode
    significar "esqueceu de revisar", não "decidiu publicar" (ver docstring
    do endpoint). Uma decisão que referencia um id fora de ``conhecidas`` só
    pode ser uma tarja manual, e só é aceita com ``bboxes``: é a única
    informação que torna aquela área real para o servidor.
    """
    faltando = set(conhecidas) - {d.entidade_id for d in decisoes}
    if faltando:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "mensagem": (
                    f"faltam decisoes para {len(faltando)} entidade(s) do "
                    "resultado original"
                ),
                "faltando": [
                    {
                        "entidade_id": id_,
                        "pagina": conhecidas[id_][0],
                        "type": conhecidas[id_][1].type.name,
                    }
                    for id_ in sorted(faltando)
                ],
            },
        )

    entidades_por_pagina: dict[int, list[EntidadeComAcao]] = defaultdict(list)
    manuais_por_pagina: dict[int, list[BBox]] = defaultdict(list)

    for decisao in decisoes:
        acao = (
            AcaoRedacao.TARJAR
            if decisao.acao is AcaoDecisao.TARJAR
            else AcaoRedacao.PUBLICAR
        )
        conhecida = conhecidas.get(decisao.entidade_id)
        if conhecida is not None:
            pagina_real, entidade = conhecida
            if decisao.pagina != pagina_real:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"decisao para {decisao.entidade_id} informa pagina "
                        f"{decisao.pagina}, mas a entidade esta na pagina "
                        f"{pagina_real}"
                    ),
                )
            entidades_por_pagina[pagina_real].append(
                EntidadeComAcao(entity=entidade, acao=acao)
            )
            continue

        if not decisao.bboxes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"entidade {decisao.entidade_id} nao esta no resultado "
                    "original e nao trouxe bboxes — sem area nao ha o que "
                    "redigir"
                ),
            )
        if decisao.pagina not in paginas_validas:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"pagina {decisao.pagina} nao existe neste documento",
            )
        if acao is AcaoRedacao.TARJAR:
            manuais_por_pagina[decisao.pagina].extend(decisao.bboxes)

    return dict(entidades_por_pagina), dict(manuais_por_pagina)


def _destruir_apos_exportar(armazenamento: Armazenamento, job_id: str) -> None:
    """Roda DEPOIS de o PDF exportado ser servido — fecha a não-retenção.

    Mesma lógica de ``descartar`` (o DELETE explícito), só que sem cliente
    HTTP esperando resposta: uma falha de limpeza vira log crítico, nunca
    some em silêncio.
    """
    try:
        armazenamento.remover(job_id)
    except ErroLimpeza:
        _log.critical(
            "falha ao remover job %s apos exportacao; dado pessoal pode ter"
            " ficado retido alem do TTL prometido",
            job_id,
            exc_info=True,
        )


def criar_app(config: Config | None = None, fila: Queue | None = None) -> FastAPI:
    """Monta a aplicação.

    ``config`` e ``fila`` são injetáveis para o teste poder usar um diretório
    descartável e uma fila síncrona. Em produção nenhum dos dois é passado:
    a configuração vem do ambiente e a fila, do Redis configurado.
    """
    configuracao = config if config is not None else Config.do_ambiente()
    aplicacao = FastAPI(
        title="redator — API de revisão",
        description=(
            "Serve o resultado da detecção para a interface de revisão, "
            "incluindo o valor real de cada dado detectado. Uso interno."
        ),
        version="0.1.0",
    )
    aplicacao.state.config = configuracao
    aplicacao.state.armazenamento = Armazenamento(configuracao.diretorio_base)
    aplicacao.state.fila = fila if fila is not None else criar_fila(configuracao)

    @aplicacao.middleware("http")
    async def _cabecalhos(
        request: Request, proxima: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        return _sem_cache(await proxima(request))

    @aplicacao.post(
        "/documentos",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
        summary="Recebe um PDF e enfileira a detecção",
    )
    async def receber(
        request: Request, arquivo: Annotated[UploadFile, File()]
    ) -> JobResponse:
        """Devolve 202 com o job em RECEBIDO, sem esperar o processamento.

        O PDF transita pelo arquivo temporário que o Starlette usa para o
        multipart, é copiado para o diretório do job e o temporário é
        fechado — não há cópia sobrando fora do job.

        Gravação e enfileiramento bloqueiam (disco e socket do Redis) e por
        isso saem do laço de eventos por ``run_in_threadpool``. As outras
        duas rotas são ``def`` simples, que o FastAPI já roda em thread — o
        upload é a única que precisa de ``async`` de verdade, para ler o
        corpo em pedaços.
        """
        configuracao: Config = request.app.state.config
        armazenamento: Armazenamento = request.app.state.armazenamento

        conteudo = await _ler_limitado(arquivo, configuracao.tamanho_maximo_bytes)
        if not conteudo.startswith(_MAGIC_PDF):
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="o arquivo nao e um PDF",
            )

        job_id = novo_job_id()
        estado = await run_in_threadpool(
            armazenamento.criar, job_id, conteudo, configuracao.ttl_segundos
        )
        try:
            await run_in_threadpool(
                enfileirar, request.app.state.fila, job_id, configuracao
            )
        except Exception:  # noqa: BLE001 — Redis fora do ar tem tipo demais
            # Sem fila não há job: some com o PDF em vez de deixá-lo no disco
            # esperando um worker que nunca virá. Best-effort: se a própria
            # limpeza falhar, o critical fica registrado, mas quem chamou já
            # vai receber 503 pela falha de fila, que é o problema principal.
            try:
                await run_in_threadpool(armazenamento.remover, job_id)
            except ErroLimpeza:
                _log.critical(
                    "falha ao limpar job %s apos falha de enfileiramento",
                    job_id,
                    exc_info=True,
                )
            _log.exception("nao consegui enfileirar o job %s", job_id)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="fila indisponivel",
            ) from None
        return estado

    @aplicacao.get(
        "/documentos/{job_id}",
        response_model=JobResponse,
        summary="Estado do job, com as páginas quando PRONTO",
    )
    def consultar(request: Request, job_id: str) -> JobResponse:
        """404 cobre os três casos: id inválido, nunca existiu e já expirou.

        Os três são indistinguíveis de propósito — quem pergunta por um job
        que não é seu não deve aprender daqui se ele existiu.
        """
        armazenamento: Armazenamento = request.app.state.armazenamento
        estado = armazenamento.obter(job_id)
        if estado is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job nao encontrado"
            )
        return estado

    @aplicacao.get(
        "/documentos/{job_id}/original",
        response_class=FileResponse,
        summary="O PDF original, byte a byte",
    )
    def original(request: Request, job_id: str) -> FileResponse:
        """O arquivo enviado, para a interface poder renderizá-lo.

        Existe porque o browser NÃO guarda o ``File`` do upload entre
        recarregamentos: sem esta rota, um refresh perde o documento mesmo com
        o job vivo no servidor, e a tela de revisão não teria o que desenhar.

        Serve dado pessoal em claro, como o resto da API. As proteções são as
        mesmas — loopback por default, sem CORS, TTL curto e ``no-store`` pelo
        middleware — e a validação passa pelo mesmo ``obter``, que destrói o
        que venceu antes de responder.
        """
        armazenamento: Armazenamento = request.app.state.armazenamento
        if armazenamento.obter(job_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job nao encontrado"
            )
        return FileResponse(
            armazenamento.caminho_pdf(job_id), media_type="application/pdf"
        )

    @aplicacao.delete(
        "/documentos/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Destrói o job e tudo que ele deixou em disco",
    )
    def descartar(request: Request, job_id: str) -> Response:
        """Antecipa o TTL: é o que a interface chama ao terminar a revisão.

        Diferente do GET (que só precisa que o job pareça morto), aqui quem
        chamou pediu a destruição explicitamente — se a limpeza física falhar
        depois das retentativas, não faz sentido devolver 204 como se tivesse
        funcionado. Vira 500, registrado como crítico, para o cliente saber
        que precisa tentar de novo (ou alguém precisa olhar o disco).
        """
        armazenamento: Armazenamento = request.app.state.armazenamento
        try:
            removido = armazenamento.remover(job_id)
        except ErroLimpeza:
            _log.critical(
                "falha ao remover job %s por pedido explicito (DELETE)",
                job_id,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="falha ao remover o job do disco; tente novamente",
            ) from None
        if not removido:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job nao encontrado"
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @aplicacao.post(
        "/documentos/{job_id}/exportar",
        response_class=FileResponse,
        summary="Redige de verdade (Fase 4) e devolve o PDF pronto para publicação",
    )
    def exportar(request: Request, job_id: str, corpo: ExportarRequest) -> FileResponse:
        """Fecha o ciclo: detecção → revisão humana → redação real → download.

        Exige uma decisão (``TARJAR``/``PUBLICAR``) para CADA entidade do
        resultado original — sem default por omissão. Uma entidade esquecida
        na revisão não vira "publicar" silenciosamente só porque ninguém
        mandou nada sobre ela: falta decisão é 400, com a lista de quais.
        Uma tarja MANUAL (sem origem em detector) entra pelo mesmo corpo, com
        ``bboxes`` próprio — é a única forma de o servidor saber onde ela
        está, já que nunca a viu antes desta chamada.

        A redação em si é ``redigir_pdf`` (Fase 4), sobre o ``original.pdf``
        do job — nenhuma lógica de redação é duplicada aqui. Antes de servir
        o arquivo, ``RelatorioRedacao.verificacao`` — o leitor independente
        que reabre o resultado do zero e não confia no que a redação afirma —
        precisa ter aprovado. Reprovado vira 500 com o vazamento: um
        documento com dado pessoal ainda detectável não pode ser servido como
        se estivesse pronto, mesmo que o arquivo exista em disco. O job
        continua vivo nesse caso, para permitir nova tentativa ou inspeção.

        Só pode ser chamado uma vez por job: depois de servir o download com
        sucesso, o job inteiro é destruído (original, redigido, estado,
        resultado) — consistente com a política de não-retenção. Uma segunda
        chamada encontra 404, como qualquer job que já não existe mais.
        """
        armazenamento: Armazenamento = request.app.state.armazenamento
        estado = armazenamento.obter(job_id)
        if estado is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job nao encontrado"
            )
        if estado.status is not JobStatus.PRONTO or estado.paginas is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"job ainda nao esta pronto (status={estado.status.value})",
            )

        caminho_original = armazenamento.caminho_pdf(job_id)
        conhecidas = _entidades_conhecidas(caminho_original, estado.paginas)
        paginas_validas = {p.numero for p in estado.paginas}

        entidades_por_pagina, manuais_por_pagina = _montar_redacao(
            corpo.decisoes, conhecidas, paginas_validas
        )

        caminho_saida = armazenamento.caminho_redigido(job_id)
        relatorio = redigir_pdf(
            caminho_original,
            caminho_saida,
            entidades_por_pagina,
            redacoes_manuais_por_pagina=manuais_por_pagina,
        )

        if not relatorio.verificacao.aprovado:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "mensagem": (
                        "a verificacao pos-redacao reprovou este documento — "
                        "ele NAO deve ser considerado seguro para publicacao"
                    ),
                    "vazamentos": [
                        {
                            "origem": v.origem,
                            "pagina": v.pagina,
                            "tipo": v.entity.type.name if v.entity else None,
                            "detalhe": v.detalhe,
                        }
                        for v in relatorio.verificacao.vazamentos
                    ],
                },
            )

        return FileResponse(
            caminho_saida,
            media_type="application/pdf",
            background=BackgroundTask(_destruir_apos_exportar, armazenamento, job_id),
        )

    return aplicacao


app = criar_app()


def servir() -> None:
    """Sobe o uvicorn com o host e a porta da configuração.

    Um bind fora do loopback é registrado no log com o que ele significa. Não
    é impedido — há caso legítimo, a rede interna do órgão —, mas também não
    passa em silêncio.
    """
    import uvicorn

    configuracao = Config.do_ambiente()
    if configuracao.exposto_na_rede:
        _log.warning(
            "bind em %s: a API expoe o valor real dos dados detectados a "
            "quem alcancar esse endereco",
            configuracao.host,
        )
    uvicorn.run(app, host=configuracao.host, port=configuracao.porta)
