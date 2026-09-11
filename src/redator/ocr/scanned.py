"""PDF digitalizado -> ``DocumentExtraction``, por renderização + OCR.

O resultado tem o MESMO formato que ``extract_pdf`` produz para PDF nativo.
É isso que permite a ``process_pdf`` e a ``gerar_pdf_debug`` trabalharem
sobre qualquer um dos dois sem saber a diferença — basta passar esta função
como ``extrator``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pymupdf
from PIL import Image

from ..pdf.extract import (
    BBox,
    CharBox,
    DocumentExtraction,
    LowConfidenceWord,
    PageExtraction,
)
from .base import OcrEngine
from .tesseract_engine import TesseractEngine

__all__ = ["DPI_PADRAO", "extract_pdf_scanned"]

# 300 dpi e o padrao de digitalizacao de documento e a resolucao que o
# Tesseract recomenda. Menos degrada o reconhecimento; mais so custa tempo.
DPI_PADRAO = 300


def _escalar(bbox: BBox, escala_x: float, escala_y: float) -> BBox:
    return (
        bbox[0] * escala_x,
        bbox[1] * escala_y,
        bbox[2] * escala_x,
        bbox[3] * escala_y,
    )


def _para_pontos(
    pagina: PageExtraction, numero: int, escala_x: float, escala_y: float
) -> PageExtraction:
    """Renumera a página e leva as caixas de pixels da imagem a pontos do PDF.

    O motor só vê a imagem: devolve ``page=0`` e pixels. Aqui a página ganha
    o número real e as caixas passam para o espaço da página do PDF, o mesmo
    em que ``extract_pdf`` trabalha e em que ``gerar_pdf_debug`` desenha.
    """
    caixas: list[CharBox] = [
        replace(caixa, page=numero, bbox=_escalar(caixa.bbox, escala_x, escala_y))
        for caixa in pagina.char_boxes
    ]
    baixa: list[LowConfidenceWord] = [
        replace(palavra, page=numero, bbox=_escalar(palavra.bbox, escala_x, escala_y))
        for palavra in pagina.low_confidence_words
    ]
    return PageExtraction(
        page=numero, text=pagina.text, char_boxes=caixas, low_confidence_words=baixa
    )


def extract_pdf_scanned(
    caminho: str | Path,
    engine: OcrEngine | None = None,
    dpi: int = DPI_PADRAO,
) -> DocumentExtraction:
    """Renderiza cada página como imagem, OCRa, e devolve no formato nativo.

    Não depende de o PDF ter camada de texto — toda página é renderizada com
    ``page.get_pixmap`` e passada ao motor, mesmo que houvesse texto. Para PDF
    com texto nativo, ``extract_pdf`` é melhor e mais barato; esta função é
    para o que veio do scanner.

    ``engine`` é qualquer ``OcrEngine``; o padrão é ``TesseractEngine()``.
    Uma página em branco nem chega ao motor (``TesseractEngine`` a atalha),
    então um PDF só de páginas vazias funciona mesmo sem Tesseract instalado.

    Coordenadas: as caixas saem em PONTOS do PDF, convertidas da imagem pela
    razão exata entre o retângulo da página e o tamanho do pixmap — não pelo
    ``dpi`` nominal, que sofre arredondamento na renderização.
    """
    motor = engine if engine is not None else TesseractEngine()
    documento = pymupdf.open(str(caminho))
    try:
        paginas: list[PageExtraction] = []
        for numero in range(documento.page_count):
            pagina_pdf = documento[numero]
            pixmap = pagina_pdf.get_pixmap(
                dpi=dpi, colorspace=pymupdf.csRGB, alpha=False
            )
            imagem = Image.frombytes(
                "RGB", (pixmap.width, pixmap.height), pixmap.samples
            )
            bruta = motor.extract_text(imagem)
            escala_x = pagina_pdf.rect.width / pixmap.width
            escala_y = pagina_pdf.rect.height / pixmap.height
            paginas.append(_para_pontos(bruta, numero, escala_x, escala_y))
    finally:
        documento.close()
    return DocumentExtraction(pages=paginas)
