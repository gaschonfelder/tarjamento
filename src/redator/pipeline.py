"""Orquestração: normaliza, detecta, devolve offsets do texto original."""

from __future__ import annotations

from dataclasses import replace

from .detectors import DETECTORES_SO_OCR, TIPOS_FRAGEIS_EM_OCR, Detector
from .entities import Entity
from .normalize import normalize, span_to_original
from .overlap import resolve_entities

__all__ = ["detect_all"]


def _para_original(entidade: Entity, texto: str, mapa: list[int]) -> Entity:
    """Reancora uma entidade do texto normalizado no texto original."""
    inicio, fim = span_to_original(entidade.start, entidade.end, mapa)
    return replace(entidade, start=inicio, end=fim, text=texto[inicio:fim])


def detect_all(
    texto: str, detectores: list[Detector], *, origem_ocr: bool = False
) -> list[Entity]:
    """Roda os detectores e devolve entidades ancoradas no texto original.

    Os detectores veem o texto normalizado e reportam offsets nele. Aqui cada
    entidade é convertida de volta para o original e tem o campo ``text``
    reescrito com o trecho original — ou seja, com a acentuação, os hífens
    tipográficos e os espaços que a normalização tinha trocado.

    No fim aplica :func:`redator.overlap.resolve_entities`, que resolve as
    disputas por trecho e descarta fragmentos espúrios. Como a resolução roda
    depois da conversão, ela enxerga os offsets reais — importante, porque a
    normalização pode mudar comprimentos e, com eles, a precedência.

    ``origem_ocr`` diz que este texto foi lido por OCR, e não veio da camada
    de texto de um PDF. Normalmente não é preciso passá-lo à mão:
    :func:`redator.pdf.process_pdf` o lê de ``PageExtraction.origem_ocr``.
    Com ele ligado, duas coisas mudam — e só para esta origem:

    - entram também os :data:`redator.detectors.DETECTORES_SO_OCR`, que
      resgatam o que a degradação de leitura quebrou (um ``@`` lido como
      ``&``, por exemplo). Eles são aditivos e nunca disputam trecho com os
      detectores normais;
    - os :data:`redator.detectors.TIPOS_FRAGEIS_EM_OCR` saem com
      ``requires_review=True``, mesmo com casamento limpo e âncora. A
      confiança não muda: o que a marca diz é que o TIPO é frágil nesta
      origem, não que aquela detecção seja duvidosa.
    """
    normalizado, mapa = normalize(texto)

    efetivos = [*detectores, *DETECTORES_SO_OCR] if origem_ocr else detectores
    brutas: list[Entity] = []
    for detector in efetivos:
        brutas.extend(detector.detect(normalizado))

    reancoradas: list[Entity] = []
    for entidade in brutas:
        if entidade.end > len(normalizado):
            raise ValueError(
                f"detector {entidade.detector!r} devolveu end={entidade.end} "
                f"alem do texto normalizado ({len(normalizado)} caracteres)"
            )
        reancoradas.append(_para_original(entidade, texto, mapa))

    resolvidas = resolve_entities(reancoradas)
    if not origem_ocr:
        return resolvidas
    return [
        replace(entidade, requires_review=True)
        if entidade.type in TIPOS_FRAGEIS_EM_OCR
        else entidade
        for entidade in resolvidas
    ]
