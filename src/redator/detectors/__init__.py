"""Detectores de entidades."""

from .base import Detector
from .contato import DETECTORES_CONTATO
from .contextual import DETECTORES_CONTEXTUAIS
from .documentos import DETECTORES_DOCUMENTOS, DetectorDocumento

#: Todos os detectores implementados, na ordem em que foram construidos.
TODOS_DETECTORES: list[Detector] = [
    *DETECTORES_DOCUMENTOS,
    *DETECTORES_CONTATO,
    *DETECTORES_CONTEXTUAIS,
]

__all__ = [
    "DETECTORES_CONTATO",
    "DETECTORES_CONTEXTUAIS",
    "DETECTORES_DOCUMENTOS",
    "TODOS_DETECTORES",
    "Detector",
    "DetectorDocumento",
]
