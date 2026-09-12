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
from collections.abc import Awaitable, Callable
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
from rq import Queue
from starlette.concurrency import run_in_threadpool

from .config import Config
from .jobs import criar_fila, enfileirar
from .schemas import JobResponse
from .storage import Armazenamento, novo_job_id

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
            # esperando um worker que nunca virá.
            await run_in_threadpool(armazenamento.remover, job_id)
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

    @aplicacao.delete(
        "/documentos/{job_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Destrói o job e tudo que ele deixou em disco",
    )
    def descartar(request: Request, job_id: str) -> Response:
        """Antecipa o TTL: é o que a interface chama ao terminar a revisão."""
        armazenamento: Armazenamento = request.app.state.armazenamento
        if not armazenamento.remover(job_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="job nao encontrado"
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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
