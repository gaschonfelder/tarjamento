"""Extração de texto e posição a partir de PDF."""

from .extract import (
    CharBox,
    DocumentExtraction,
    PageExtraction,
    bboxes_for_span,
    extract_pdf,
)

__all__ = [
    "CharBox",
    "DocumentExtraction",
    "PageExtraction",
    "bboxes_for_span",
    "extract_pdf",
]
