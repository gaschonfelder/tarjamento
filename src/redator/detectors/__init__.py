"""Detectores de entidades."""

from .base import Detector
from .documentos import DETECTORES_DOCUMENTOS, DetectorDocumento

__all__ = ["DETECTORES_DOCUMENTOS", "Detector", "DetectorDocumento"]
