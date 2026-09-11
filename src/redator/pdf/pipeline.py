"""PDF de ponta a ponta: extrai, detecta por página, desenha para inspeção.

Liga a camada de extração (Fase 2) ao pipeline de detecção (Fase 1). Cada
página é processada isolada: os offsets das entidades são relativos ao texto
daquela página, que é o único espaço em que ``bboxes_for_span`` faz sentido.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pymupdf

from ..detectors import Detector
from ..entities import Entity
from ..pipeline import detect_all
from .extract import (
    BBox,
    DocumentExtraction,
    PageExtraction,
    bboxes_for_span,
    extract_pdf,
)

__all__ = ["Extrator", "gerar_pdf_debug", "process_pdf"]

#: Qualquer função que leve um caminho de PDF a uma ``DocumentExtraction``.
#: ``extract_pdf`` (camada de texto nativa) e ``extract_pdf_scanned`` (OCR)
#: têm esta forma, e o pipeline não distingue uma da outra.
Extrator = Callable[[str | Path], DocumentExtraction]

# Vermelho translucido: a tarja de debug deixa ver o que esta por baixo.
_COR = (1.0, 0.0, 0.0)
_OPACIDADE_PREENCHIMENTO = 0.3
_OPACIDADE_BORDA = 0.9
_ESPESSURA_BORDA = 0.5
_FONTE_ROTULO = 6.0
_ALTURA_ROTULO = 8.0


def process_pdf(
    caminho: str | Path,
    detectores: list[Detector],
    *,
    extrator: Extrator = extract_pdf,
) -> dict[int, list[Entity]]:
    """Roda os detectores sobre cada página e devolve as entidades por página.

    Os offsets de cada ``Entity`` são do texto ORIGINAL da página, como o
    extrator o devolveu — ``detect_all`` normaliza internamente e já traz os
    offsets de volta, então aqui não há segunda normalização.

    ``extrator`` escolhe de onde vem o texto: ``extract_pdf`` (padrão) lê a
    camada de texto nativa; ``redator.ocr.extract_pdf_scanned`` renderiza e
    OCRa. O restante do pipeline é o mesmo — é a razão de as duas devolverem
    a mesma ``DocumentExtraction``.

    A origem do texto não precisa ser informada: cada página a carrega em
    ``PageExtraction.origem_ocr``, e é dela que sai o ``origem_ocr`` de
    :func:`redator.pipeline.detect_all`. Assim não há como processar texto de
    OCR e esquecer de tratá-lo como tal.

    Toda página aparece no resultado, mesmo sem entidade (lista vazia): quem
    chama sabe que ela foi processada, e não apenas que nada foi achado.
    """
    documento = extrator(caminho)
    return {
        pagina.page: detect_all(pagina.text, detectores, origem_ocr=pagina.origem_ocr)
        for pagina in documento.pages
    }


def _rotulo(entidade: Entity) -> str:
    return f"{entidade.type.name} {entidade.confidence:.2f}"


def _caixa_do_rotulo(bbox: BBox, pagina: pymupdf.Page, texto: str) -> pymupdf.Rect:
    """Uma faixa estreita logo acima da caixa; abaixo, se não couber."""
    x0, y0, _, y1 = bbox
    largura = max(len(texto) * _FONTE_ROTULO * 0.6, 60.0)
    topo = y0 - _ALTURA_ROTULO
    if topo < pagina.rect.y0:
        topo = y1
    return pymupdf.Rect(x0, topo, x0 + largura, topo + _ALTURA_ROTULO)


def _desenhar(pagina: pymupdf.Page, entidade: Entity, caixas: list[BBox]) -> None:
    for indice, bbox in enumerate(caixas):
        rect = pymupdf.Rect(*bbox)
        pagina.draw_rect(
            rect,
            color=_COR,
            fill=_COR,
            width=_ESPESSURA_BORDA,
            fill_opacity=_OPACIDADE_PREENCHIMENTO,
            stroke_opacity=_OPACIDADE_BORDA,
            overlay=True,
        )
        if indice == 0:
            rotulo = _rotulo(entidade)
            anotacao = pagina.add_freetext_annot(
                _caixa_do_rotulo(bbox, pagina, rotulo),
                rotulo,
                fontsize=_FONTE_ROTULO,
                fontname="helv",
                text_color=_COR,
            )
            anotacao.update()


def gerar_pdf_debug(
    caminho_entrada: str | Path,
    caminho_saida: str | Path,
    entidades_por_pagina: dict[int, list[Entity]],
    *,
    extrator: Extrator = extract_pdf,
) -> Path:
    """Copia o PDF com cada entidade marcada em vermelho translúcido.

    ``extrator`` tem de ser o MESMO usado para produzir as entidades: os
    offsets delas só fazem sentido no texto que aquele extrator gerou.

    Sobre cada retângulo de ``bboxes_for_span`` vai um preenchimento com
    opacidade — o conteúdo original continua visível por baixo — e, junto do
    primeiro retângulo de cada entidade, uma anotação de texto livre com o
    tipo e a confiança. É para olhar, não para publicar: a tarja de verdade é
    outra etapa.

    O resultado é sempre um arquivo novo. Entrada e saída no mesmo caminho é
    erro, não sobrescrita silenciosa.
    """
    entrada = Path(caminho_entrada)
    saida = Path(caminho_saida)
    if entrada.resolve() == saida.resolve():
        raise ValueError(f"saida igual a entrada: {entrada} — nunca sobrescreve")

    extraido = {pagina.page: pagina for pagina in extrator(entrada).pages}

    documento = pymupdf.open(str(entrada))
    try:
        for numero, entidades in entidades_por_pagina.items():
            if numero not in extraido:
                raise IndexError(f"pagina {numero} nao existe em {entrada}")
            pagina_extraida: PageExtraction = extraido[numero]
            pagina_pdf = documento[numero]
            for entidade in entidades:
                caixas = bboxes_for_span(pagina_extraida, entidade.start, entidade.end)
                _desenhar(pagina_pdf, entidade, caixas)
        documento.save(str(saida))
    finally:
        documento.close()
    return saida
