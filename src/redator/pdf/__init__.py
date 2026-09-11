"""Extração de texto e posição a partir de PDF, e o pipeline sobre ela."""

from .extract import (
    CharBox,
    DocumentExtraction,
    LowConfidenceWord,
    PageExtraction,
    bboxes_for_span,
    extract_pdf,
)
from .pipeline import Extrator, gerar_pdf_debug, process_pdf

__all__ = [
    "CharBox",
    "DocumentExtraction",
    "Extrator",
    "LowConfidenceWord",
    "PageExtraction",
    "bboxes_for_span",
    "extract_pdf",
    "gerar_pdf_debug",
    "process_pdf",
]
