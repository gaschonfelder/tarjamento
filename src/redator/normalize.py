"""Normalização de texto com rastreamento de offsets.

O detector trabalha sobre texto normalizado, mas a tarja precisa cair no texto
original. Por isso ``normalize`` devolve, além do texto, um mapa que leva cada
posição do normalizado de volta ao original — inclusive quando a normalização
muda o comprimento, em qualquer direção.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator

__all__ = ["normalize", "span_to_original", "to_original"]

# ‐ ‑ ‒ – —  : hífens tipográficos que viram hífen ASCII.
_HIFENS = frozenset("‐‑‒–—")

# Jamo V e T do Hangul: compõem com o jamo anterior apesar de serem starters,
# então não podem iniciar um bloco novo (veja _blocos).
_JAMO_DEPENDENTE = range(0x1160, 0x1200)


def _preparar(char: str) -> str:
    """Substituições um-para-um, feitas antes do NFKC.

    Preservam os índices, então não afetam o mapa. Cobrem o que o NFKC não faz:
    ele não mexe em traços tipográficos, e deixa passar alguns espaços (o espaço
    ogâmico, por exemplo).
    """
    if char in _HIFENS:
        return "-"
    if unicodedata.category(char) == "Zs":
        return " "
    return char


def _blocos(texto: str) -> Iterator[tuple[int, int]]:
    """Fatia o texto em trechos que podem ser normalizados isoladamente.

    Um bloco começa num starter e engloba os caracteres combinantes seguintes,
    que são justamente os que podem se fundir com ele. Jamo dependente entra no
    bloco anterior pelo mesmo motivo.
    """
    if not texto:
        return
    inicio = 0
    for indice in range(1, len(texto)):
        char = texto[indice]
        if unicodedata.combining(char) == 0 and ord(char) not in _JAMO_DEPENDENTE:
            yield inicio, indice
            inicio = indice
    yield inicio, len(texto)


def normalize(texto: str) -> tuple[str, list[int]]:
    """Normaliza o texto e devolve ``(normalizado, mapa)``.

    A normalização é NFKC, mais hífens tipográficos viram ``-`` e qualquer
    espaço Unicode vira espaço comum. Quebras de linha, espaços repetidos e
    caixa ficam intactos.

    O mapa tem ``len(normalizado) + 1`` entradas: ``mapa[i]`` é o índice no
    original onde começa o i-ésimo caractere normalizado, e a entrada extra no
    fim vale ``len(texto)``. É essa entrada a mais que deixa
    :func:`span_to_original` converter o fim exclusivo de um span sem caso
    especial. Para texto que não muda, o mapa é ``list(range(len(texto) + 1))``.

    Quando vários caracteres originais se fundem em um só normalizado, todos os
    normalizados daquele bloco apontam para o início do bloco — o span original
    recuperado cobre o bloco inteiro, que é o que a tarja precisa cobrir.

    Levanta ``ValueError`` se a normalização por blocos divergir do NFKC do
    texto inteiro. Nesse caso não haveria como rastrear os offsets com
    honestidade, e falhar alto é melhor que tarjar o trecho errado.
    """
    preparado = "".join(_preparar(char) for char in texto)

    partes: list[str] = []
    mapa: list[int] = []
    for inicio, fim in _blocos(preparado):
        bloco = unicodedata.normalize("NFKC", preparado[inicio:fim])
        partes.append(bloco)
        mapa.extend([inicio] * len(bloco))

    normalizado = "".join(partes)
    mapa.append(len(texto))

    esperado = unicodedata.normalize("NFKC", preparado)
    if normalizado != esperado:
        raise ValueError(
            "normalizacao por blocos divergiu do NFKC do texto inteiro; "
            "os offsets nao sao rastreaveis para esta entrada"
        )
    return normalizado, mapa


def to_original(idx_norm: int, mapa: list[int]) -> int:
    """Índice no texto original correspondente a ``idx_norm``.

    Aceita ``idx_norm == len(normalizado)``, que devolve ``len(original)`` — é
    a entrada sentinela do mapa, útil como fim exclusivo.
    """
    if not 0 <= idx_norm < len(mapa):
        raise IndexError(f"idx_norm {idx_norm} fora do mapa de {len(mapa)} entradas")
    return mapa[idx_norm]


def span_to_original(start: int, end: int, mapa: list[int]) -> tuple[int, int]:
    """Converte um span do texto normalizado para o texto original.

    O fim é convertido pela entrada ``mapa[end]``, ou seja, pelo início do
    caractere seguinte — é o que mantém o intervalo exclusivo correto mesmo
    quando o último caractere do span ocupa vários caracteres no original.

    Um span que cai inteiro dentro da expansão de um único caractere original
    (por exemplo o ``f`` de um ``ﬁ`` que virou ``fi``) recuperaria um intervalo
    vazio; nesse caso o resultado é alargado para cobrir o caractere original
    inteiro, que é o trecho que precisa ser tarjado.
    """
    if start > end:
        raise ValueError(f"start ({start}) nao pode ser maior que end ({end})")
    inicio = to_original(start, mapa)
    fim = to_original(end, mapa)
    if start < end and fim == inicio:
        fim = min(inicio + 1, mapa[-1])
    return inicio, fim
