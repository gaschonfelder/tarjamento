"""Orquestração: normaliza, detecta, devolve offsets do texto original."""

from __future__ import annotations

from dataclasses import replace

from .detectors import Detector
from .entities import Entity
from .normalize import normalize, span_to_original
from .overlap import resolve_entities

__all__ = ["detect_all"]


def _para_original(entidade: Entity, texto: str, mapa: list[int]) -> Entity:
    """Reancora uma entidade do texto normalizado no texto original."""
    inicio, fim = span_to_original(entidade.start, entidade.end, mapa)
    return replace(entidade, start=inicio, end=fim, text=texto[inicio:fim])


def detect_all(texto: str, detectores: list[Detector]) -> list[Entity]:
    """Roda os detectores e devolve entidades ancoradas no texto original.

    Os detectores veem o texto normalizado e reportam offsets nele. Aqui cada
    entidade é convertida de volta para o original e tem o campo ``text``
    reescrito com o trecho original — ou seja, com a acentuação, os hífens
    tipográficos e os espaços que a normalização tinha trocado.

    No fim aplica :func:`redator.overlap.resolve_entities`, que resolve as
    disputas por trecho e descarta fragmentos espúrios. Como a resolução roda
    depois da conversão, ela enxerga os offsets reais — importante, porque a
    normalização pode mudar comprimentos e, com eles, a precedência.
    """
    normalizado, mapa = normalize(texto)

    brutas: list[Entity] = []
    for detector in detectores:
        brutas.extend(detector.detect(normalizado))

    reancoradas: list[Entity] = []
    for entidade in brutas:
        if entidade.end > len(normalizado):
            raise ValueError(
                f"detector {entidade.detector!r} devolveu end={entidade.end} "
                f"alem do texto normalizado ({len(normalizado)} caracteres)"
            )
        reancoradas.append(_para_original(entidade, texto, mapa))

    return resolve_entities(reancoradas)
