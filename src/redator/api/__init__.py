"""API HTTP que serve a interface de revisão.

O pacote só consome o que as fases anteriores já entregam — ``process_pdf``,
``extract_pdf``, ``extract_pdf_scanned`` e os detectores. Nada aqui detecta
nada.

Leia ``app.py`` antes de mexer: esta API serve o valor real dos dados
pessoais detectados, e as restrições que decorrem disso (sem CORS, bind em
loopback, TTL curto, nenhuma retenção) estão explicadas lá.
"""

from .config import Config
from .schemas import (
    EntidadeResponse,
    JobResponse,
    JobStatus,
    PaginaResponse,
)
from .storage import Armazenamento

__all__ = [
    "Armazenamento",
    "Config",
    "EntidadeResponse",
    "JobResponse",
    "JobStatus",
    "PaginaResponse",
]
