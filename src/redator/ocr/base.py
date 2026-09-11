"""Contrato do motor de OCR.

Trocar o motor — Tesseract por PaddleOCR, docTR, o que vier — não pode exigir
tocar em nada fora de ``redator.ocr``. O que garante isso é o motor devolver a
MESMA ``PageExtraction`` que ``extract_pdf`` devolve para PDF nativo: dali em
diante pipeline, âncoras e ``bboxes_for_span`` não sabem, nem precisam saber,
de onde o texto veio.

As estruturas de dados são as de ``redator.pdf.extract``, reexportadas aqui
por conveniência. Não há duplicata: um ``CharBox`` de OCR é um ``CharBox``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from PIL import Image

from ..pdf.extract import (
    BBox,
    CharBox,
    DocumentExtraction,
    LowConfidenceWord,
    PageExtraction,
)

__all__ = [
    "BBox",
    "CharBox",
    "DocumentExtraction",
    "LowConfidenceWord",
    "OcrEngine",
    "PageExtraction",
]


@runtime_checkable
class OcrEngine(Protocol):
    """Reconhece o texto de uma imagem e devolve texto com posição.

    A página devolvida usa ``page=0`` e coordenadas em PIXELS da imagem. O
    motor não sabe de qual página de qual PDF a imagem veio, nem em que
    escala foi renderizada — quem sabe é ``extract_pdf_scanned``, que
    renumera e converte para pontos.
    """

    def extract_text(self, imagem: Image.Image) -> PageExtraction:
        """Texto e caixas da imagem. Imagem sem nada legível devolve vazio."""
        ...
