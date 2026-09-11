"""Detectores de entidades.

Só a infraestrutura por enquanto: o contrato em :mod:`redator.detectors.base`.
Os detectores concretos entram aqui conforme forem implementados.
"""

from .base import Detector

__all__ = ["Detector"]
