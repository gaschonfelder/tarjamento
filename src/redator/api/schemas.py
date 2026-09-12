"""Modelos de request/response da API.

São um espelho de ``redator.entities.Entity`` e de ``redator.pdf``, não um
modelo novo: os campos têm os mesmos nomes e o mesmo significado que lá. As
duas únicas coisas que nascem aqui são o ``id`` de entidade — que a interface
precisa para referenciar uma tarja e que ``Entity`` não tem — e as bboxes,
que em ``Entity`` não existem porque lá o offset é de texto, não de página.

``texto_original`` carrega o VALOR REAL do dado pessoal. É deliberado: a
revisão mostra o dado por baixo da tarja no hover, e sem ele não há revisão.
É também a razão de todo o resto da API ser fechada por default — veja
``redator.api.config``.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

__all__ = [
    "EntidadeResponse",
    "JobResponse",
    "JobStatus",
    "PaginaResponse",
]

#: ``(x0, y0, x1, y1)`` em pontos da página, o mesmo espaço de
#: ``redator.pdf.bboxes_for_span`` — inclusive para páginas vindas de OCR,
#: que ``extract_pdf_scanned`` já converte de pixels para pontos.
BBox = tuple[float, float, float, float]


class EntidadeResponse(BaseModel):
    """Uma entidade detectada, com onde tarjar e o que está por baixo."""

    id: str
    type: str
    confidence: float
    context: str | None
    requires_review: bool
    validated: bool
    bboxes: list[BBox]
    texto_original: str
    pagina: int


class PaginaResponse(BaseModel):
    """Uma página e o que foi achado nela.

    ``largura``/``altura`` vêm do retângulo da página no PDF, em pontos: sem
    elas a interface não tem como escalar as bboxes para a imagem que mostra.
    """

    numero: int
    largura: float
    altura: float
    entidades: list[EntidadeResponse]


class JobStatus(str, Enum):
    """Ciclo de vida de um job. ``ERRO`` é terminal, como ``PRONTO``."""

    RECEBIDO = "recebido"
    PROCESSANDO = "processando"
    PRONTO = "pronto"
    ERRO = "erro"


class JobResponse(BaseModel):
    """O estado de um job, e o resultado quando houver.

    ``paginas`` só vem preenchido em ``PRONTO``; nos demais estados é ``None``,
    que é diferente de lista vazia (documento processado sem nenhuma entidade).
    """

    id: str
    status: JobStatus
    progresso: float | None = Field(default=None, ge=0.0, le=1.0)
    erro: str | None = None
    paginas: list[PaginaResponse] | None = None
    expira_em: datetime
