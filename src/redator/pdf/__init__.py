"""Extração de texto e posição a partir de PDF, e o pipeline sobre ela."""

from .extract import (
    CharBox,
    DocumentExtraction,
    PageExtraction,
    bboxes_for_span,
    extract_pdf,
)
from .pipeline import gerar_pdf_debug, process_pdf

__all__ = [
    "CharBox",
    "DocumentExtraction",
    "PageExtraction",
    "bboxes_for_span",
    "extract_pdf",
    "gerar_pdf_debug",
    "process_pdf",
]
