"""Fila, worker e expiração.

O worker roda em processo separado da API::

    rq worker --with-scheduler --url redis://127.0.0.1:6379/0 redator

O ``--with-scheduler`` não é opcional por conveniência: é ele que dispara
:func:`expirar_job` no vencimento do TTL. Sem ele a expiração ainda acontece,
mas só quando alguém ler o job (``Armazenamento.obter`` destrói o que já
venceu) ou quando :func:`purgar_expirados` for chamada — ou seja, um job
abandonado ficaria no disco até a próxima varredura. As duas vias existem de
propósito: nenhuma sozinha é suficiente, e a soma garante que nada vencido
seja servido e que nada abandonado fique.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pymupdf
from redis import Redis
from rq import Queue

from ..detectors import TODOS_DETECTORES
from ..entities import Entity
from ..ocr import extract_pdf_scanned
from ..pdf import DocumentExtraction, PageExtraction, bboxes_for_entity, extract_pdf
from ..pdf.pipeline import process_pdf
from .config import Config
from .schemas import EntidadeResponse, JobStatus, PaginaResponse
from .storage import Armazenamento

__all__ = [
    "TIMEOUT_PROCESSAMENTO",
    "agendar_expiracao",
    "criar_fila",
    "enfileirar",
    "expirar_job",
    "extrair",
    "montar_paginas",
    "processar_documento",
    "purgar_expirados",
]

_log = logging.getLogger(__name__)

#: Teto de tempo de um job. Extração + OCR de um documento grande é lenta;
#: 10 minutos é folgado para o que a ferramenta recebe e ainda impede que um
#: PDF patológico prenda o worker para sempre.
TIMEOUT_PROCESSAMENTO = 600

#: Quanto o RQ guarda o registro do job depois de terminar. O registro não
#: contém dado pessoal — a função não devolve nada, o resultado vai para o
#: ``Armazenamento`` —, mas não há razão para mantê-lo além do troco.
_RESULT_TTL = 60

#: Progresso reportado depois da extração e antes da detecção. São as duas
#: fases do worker, e é a única divisão honesta que dá para fazer sem abrir
#: ``process_pdf``: não há como saber quantas páginas faltam antes de extrair.
_PROGRESSO_EXTRAIDO = 0.5


def criar_fila(config: Config) -> Queue:
    """A fila RQ desta configuração. A conexão com o Redis é preguiçosa."""
    return Queue(config.fila, connection=Redis.from_url(config.redis_url))


# ---------------------------------------------------------------------- #
# enfileiramento
# ---------------------------------------------------------------------- #


def enfileirar(fila: Queue, job_id: str, config: Config) -> None:
    """Põe o processamento na fila e agenda a expiração do job."""
    fila.enqueue(
        processar_documento,
        job_id,
        config,
        job_timeout=TIMEOUT_PROCESSAMENTO,
        result_ttl=_RESULT_TTL,
    )
    agendar_expiracao(fila, job_id, config)


def agendar_expiracao(fila: Queue, job_id: str, config: Config) -> None:
    """Agenda a destruição do job para daqui a ``config.ttl_segundos``.

    Depende do scheduler do RQ estar de pé. Se não estiver, nada estoura aqui
    — o agendamento simplesmente nunca dispara, e a expiração fica por conta
    de ``Armazenamento.obter`` e de :func:`purgar_expirados`.
    """
    fila.enqueue_in(
        timedelta(seconds=config.ttl_segundos),
        expirar_job,
        job_id,
        config,
        result_ttl=_RESULT_TTL,
    )


# ---------------------------------------------------------------------- #
# extração e conversão
# ---------------------------------------------------------------------- #


def extrair(caminho: Path) -> DocumentExtraction:
    """Texto nativo se houver; OCR se TODAS as páginas vierem vazias.

    O critério é o documento inteiro, e não página a página, de propósito: um
    PDF misto — capa digitalizada, miolo nativo — perderia o texto nativo se
    fosse OCRado por causa da capa, e o OCR é ordens de grandeza mais caro.
    Um documento em que só algumas páginas são imagem fica, portanto, com
    essas páginas vazias. É limitação conhecida, não descuido.
    """
    documento = extract_pdf(caminho)
    if any(pagina.text.strip() for pagina in documento.pages):
        return documento
    return extract_pdf_scanned(caminho)


def _dimensoes(caminho: Path) -> dict[int, tuple[float, float]]:
    """``{numero: (largura, altura)}`` em pontos, do próprio PDF.

    Vem daqui, e não da ``PageExtraction``, porque ela não carrega o tamanho
    da página — e este módulo não pode mexer em ``redator.pdf``. Serve para
    as duas origens: ``extract_pdf_scanned`` já devolve as caixas em pontos
    da página, no mesmo espaço.
    """
    documento = pymupdf.open(str(caminho))
    try:
        return {
            numero: (documento[numero].rect.width, documento[numero].rect.height)
            for numero in range(documento.page_count)
        }
    finally:
        documento.close()


def _converter(entidade: Entity, pagina: PageExtraction) -> EntidadeResponse:
    return EntidadeResponse(
        # O id nasce aqui: ``Entity`` não tem um, e a interface precisa
        # referenciar uma tarja específica para ligar, desligar e revisar.
        id=uuid.uuid4().hex,
        type=entidade.type.name,
        confidence=entidade.confidence,
        context=entidade.context,
        requires_review=entidade.requires_review,
        validated=entidade.validated,
        bboxes=bboxes_for_entity(pagina, entidade),
        texto_original=entidade.text,
        pagina=pagina.page,
    )


def montar_paginas(
    caminho: Path,
    documento: DocumentExtraction,
    entidades_por_pagina: dict[int, list[Entity]],
) -> list[PaginaResponse]:
    """Junta extração, dimensões e entidades no formato que a interface lê.

    Toda página entra, mesmo sem entidade nenhuma: a interface precisa saber
    o tamanho de cada uma para renderizar, e uma página ausente seria
    ambígua entre "sem dado pessoal" e "não processada".
    """
    dimensoes = _dimensoes(caminho)
    return [
        PaginaResponse(
            numero=pagina.page,
            largura=dimensoes[pagina.page][0],
            altura=dimensoes[pagina.page][1],
            entidades=[
                _converter(entidade, pagina)
                for entidade in entidades_por_pagina.get(pagina.page, [])
            ],
        )
        for pagina in documento.pages
    ]


# ---------------------------------------------------------------------- #
# o job
# ---------------------------------------------------------------------- #


def processar_documento(job_id: str, config: Config) -> None:
    """Extrai, detecta e grava o resultado. Executada pelo worker RQ.

    Nunca propaga exceção: qualquer falha vira ``status=ERRO`` com a mensagem
    no próprio job. Deixar a exceção subir mandaria o job para a fila de
    falhas do RQ, onde a interface não o enxerga — o usuário veria o job
    parado em PROCESSANDO para sempre, que é pior que ver o erro.
    """
    armazenamento = Armazenamento(config.diretorio_base)
    estado = armazenamento.ler_estado(job_id)
    if estado is None:
        # Cancelado ou expirado entre o enfileiramento e agora. Não é erro:
        # não há para quem reportar, e recriar o job seria ressuscitar o que
        # alguém mandou destruir.
        _log.info("job %s nao existe mais; nada a processar", job_id)
        return

    armazenamento.escrever_estado(
        estado.model_copy(update={"status": JobStatus.PROCESSANDO, "progresso": 0.0})
    )
    try:
        caminho = armazenamento.caminho_pdf(job_id)
        documento = extrair(caminho)
        armazenamento.escrever_estado(
            estado.model_copy(
                update={
                    "status": JobStatus.PROCESSANDO,
                    "progresso": _PROGRESSO_EXTRAIDO,
                }
            )
        )
        entidades = process_pdf(
            caminho, list(TODOS_DETECTORES), extrator=lambda _: documento
        )
        paginas = montar_paginas(caminho, documento, entidades)
    except Exception as erro:  # noqa: BLE001 — a falha vira estado, não crash
        _log.exception("job %s falhou", job_id)
        armazenamento.escrever_estado(
            estado.model_copy(
                update={
                    "status": JobStatus.ERRO,
                    "progresso": None,
                    "erro": f"{type(erro).__name__}: {erro}",
                }
            )
        )
        return

    armazenamento.escrever_resultado(job_id, paginas)
    armazenamento.escrever_estado(
        estado.model_copy(update={"status": JobStatus.PRONTO, "progresso": 1.0})
    )


# ---------------------------------------------------------------------- #
# expiração
# ---------------------------------------------------------------------- #


def expirar_job(job_id: str, config: Config) -> bool:
    """Destrói o job no vencimento: PDF original, resultado e estado.

    Confere o vencimento antes de apagar. Um job pode ter tido o TTL
    renovado, ou este agendamento pode ter atrasado; apagar sem olhar
    destruiria trabalho ainda válido.

    Se ``armazenamento.remover`` não conseguir apagar o diretório (ver
    ``ErroLimpeza`` em ``storage.py``), a exceção **não é capturada aqui** —
    ela sobe e o RQ marca este agendamento como falho no seu próprio
    registro de falhas, visível a quem opera. É a via correta para este
    caminho especificamente: ele já roda em background, sem cliente HTTP
    esperando resposta, então deixar o erro visível (em vez de engolir ou
    inventar um retorno) é estritamente melhor que devolver ``False`` como se
    fosse só "ainda não venceu".
    """
    armazenamento = Armazenamento(config.diretorio_base)
    estado = armazenamento.ler_estado(job_id)
    if estado is None:
        return False
    if estado.expira_em > datetime.now(UTC):
        _log.info("job %s ainda nao venceu; expiracao ignorada", job_id)
        return False
    removido = armazenamento.remover(job_id)
    if removido:
        _log.info("job %s expirado e removido", job_id)
    return removido


def purgar_expirados(config: Config) -> list[str]:
    """Varre o diretório base e remove todo job vencido.

    Existe para ser chamada por fora — um cron, um job periódico, ou a mão —
    e é o que impede que um job nunca lido fique no disco caso o scheduler
    do RQ não esteja rodando.
    """
    return Armazenamento(config.diretorio_base).purgar_expirados()
