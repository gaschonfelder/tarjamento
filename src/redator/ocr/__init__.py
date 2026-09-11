"""OCR: de imagem (ou PDF digitalizado) para a mesma ``PageExtraction`` do PDF nativo.

Ponto de entrada: ``extract_pdf_scanned``, que tem a forma de ``extract_pdf``
e por isso serve de ``extrator`` para ``process_pdf`` e ``gerar_pdf_debug``.
O motor padrão é o Tesseract; qualquer outro que satisfaça ``OcrEngine``
entra no lugar sem tocar em nada fora deste pacote.
"""

from .base import OcrEngine
from .scanned import DPI_PADRAO, extract_pdf_scanned
from .tesseract_engine import (
    IDIOMA_PADRAO,
    LIMIAR_CONFIANCA_PADRAO,
    PSM_PADRAO,
    TesseractEngine,
    localizar_tessdata,
    localizar_tesseract,
    montar_pagina_de_dados,
    tesseract_disponivel,
)

__all__ = [
    "DPI_PADRAO",
    "IDIOMA_PADRAO",
    "LIMIAR_CONFIANCA_PADRAO",
    "PSM_PADRAO",
    "OcrEngine",
    "TesseractEngine",
    "extract_pdf_scanned",
    "localizar_tessdata",
    "localizar_tesseract",
    "montar_pagina_de_dados",
    "tesseract_disponivel",
]
