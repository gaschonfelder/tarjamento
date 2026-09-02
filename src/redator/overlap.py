"""Resolução de sobreposições entre entidades detectadas."""

from __future__ import annotations

from .entities import DetectionMethod, Entity

__all__ = [
    "discard_spurious_fragments",
    "resolve_entities",
    "resolve_overlaps",
]

# Métodos cuja evidência é fraca o bastante para um casamento interno ser
# considerado fragmento de um documento maior, e não um dado por si só.
_METODOS_FRAGILES = frozenset({DetectionMethod.PADRAO, DetectionMethod.CONTEXTUAL})


def _precedence_key(entity: Entity) -> tuple[int, int, float, int, str]:
    """Chave de ordenação: menor tupla == maior precedência.

    Ordem dos critérios: ``validated``, comprimento, ``confidence``, ``start``
    e, por último, o nome do EntityType — este só para desempatar de forma
    estável. Evidência de dígito verificador vem antes de extensão: uma
    detecção longa e frouxa não derruba um documento validado por DV.
    """
    return (
        0 if entity.validated else 1,
        -entity.length,
        -entity.confidence,
        entity.start,
        entity.type.name,
    )


def _competes(a: Entity, b: Entity) -> bool:
    """Se as duas entidades disputam o mesmo trecho.

    Entidades aninhadas convivem — um CEP validado dentro de um ENDERECO de NER
    são duas anotações legítimas do mesmo texto. O que não convive é o
    cruzamento parcial (limites inconsistentes) e o span idêntico (duas leituras
    concorrentes do mesmo trecho).
    """
    return a.partially_overlaps(b) or a.span == b.span


def resolve_overlaps(entities: list[Entity]) -> list[Entity]:
    """Remove as disputas por trecho, preservando aninhamentos.

    Percorre as entidades da mais forte para a mais fraca e aceita cada uma que
    não compita com nenhuma já aceita. Como a ordem de varredura vem só dos
    atributos das entidades, o resultado independe da ordem da entrada — e uma
    cadeia A–B–C (com A e C disjuntos) resolve corretamente: se B perde para A,
    C ainda pode entrar.

    A lista de entrada não é modificada. O resultado sai ordenado por ``start``
    crescente e, no mesmo ``start``, por ``end`` decrescente — a entidade
    externa antes da que ela contém.
    """
    accepted: list[Entity] = []
    for candidate in sorted(entities, key=_precedence_key):
        if not any(_competes(candidate, kept) for kept in accepted):
            accepted.append(candidate)
    accepted.sort(key=_position_key)
    return accepted


def _position_key(entity: Entity) -> tuple[int, int]:
    """Ordem de leitura: ``start`` crescente, ``end`` decrescente."""
    return (entity.start, -entity.end)


def _is_spurious_fragment(inner: Entity, outer: Entity) -> bool:
    """Se ``inner`` é só um pedaço de ``outer``, e não um dado independente.

    Exige evidência forte do lado de fora — DV conferido — e evidência fraca do
    lado de dentro. Um CEP validado dentro de um ENDERECO de NER não se
    qualifica (a externa não passou por DV), nem um CPF validado dentro de um
    CNPJ (a interna tem DV próprio).
    """
    return (
        outer.contains(inner)
        and outer.validated
        and outer.type.metodo is DetectionMethod.VALIDADO_DV
        and not inner.validated
        and inner.type.metodo in _METODOS_FRAGILES
    )


def discard_spurious_fragments(entities: list[Entity]) -> list[Entity]:
    """Remove casamentos espúrios aninhados dentro de documentos validados.

    ``resolve_overlaps`` preserva aninhamentos porque muitos são estruturais —
    um CEP dentro de um ENDERECO são duas anotações legítimas. Já um TELEFONE
    casado no miolo de um CPF validado é ruído: não muda a tarja, mas suja o
    relatório de entidades e a auditoria. Este filtro tira só esse caso.

    Nunca descarta entidade validada, nem nada contido em detecção de NER ou em
    qualquer externa que não tenha passado por DV. A lista de entrada não é
    modificada e o resultado sai na ordem de leitura.
    """
    kept = [
        entity
        for entity in entities
        if not any(
            _is_spurious_fragment(entity, other)
            for other in entities
            if other is not entity
        )
    ]
    kept.sort(key=_position_key)
    return kept


def resolve_entities(entities: list[Entity]) -> list[Entity]:
    """Conveniência: ``resolve_overlaps`` seguido de ``discard_spurious_fragments``."""
    return discard_spurious_fragments(resolve_overlaps(entities))
