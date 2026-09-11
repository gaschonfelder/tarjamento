"""Contrato que todo detector precisa cumprir."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..entities import Entity, EntityType

__all__ = ["Detector"]


@runtime_checkable
class Detector(Protocol):
    """Acha ocorrências de um tipo de entidade no texto normalizado.

    Os offsets das entidades devolvidas são do texto NORMALIZADO. Converter para
    o texto original é trabalho de :func:`redator.pipeline.detect_all`, que é
    quem tem o mapa — o detector nem precisa saber que existe um original.
    """

    name: str
    entity_type: EntityType

    def detect(self, texto: str) -> list[Entity]:
        """Entidades achadas em ``texto``, já normalizado."""
        ...
