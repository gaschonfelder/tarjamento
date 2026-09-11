"""Fronteiras de candidato, compartilhadas pelos detectores.

Um candidato não pode estar colado a letra ou dígito, nem ser o pedaço de uma
corrida maior de grupos numéricos. Sem isso ``52998224725-A`` (código) e
``04.122.7001.2001.3.3.90.39.00`` (dotação) virariam documento.
"""

from __future__ import annotations

import re

__all__ = ["ANTES", "DEPOIS", "SO_DIGITOS", "tolerante"]

_SEPARADOR = r"[.\-/ ]"

#   (?<![^\W_])        nada alfanumerico imediatamente antes -> BR52998224725SP
#   (?<![^\W_][.\-/])  nao vem depois de alfanumerico + separador -> A-52998224725
#   (?![^\W_])         nada alfanumerico logo depois          -> 5299822472500
#   (?![.\-/][^\W_])   nao e seguido de separador + alfanumerico -> 52998224725-A
#
# O espaco fica de fora das duas regras de separador: ele e o que separa o
# candidato do resto da frase.
ANTES = r"(?<![^\W_])(?<![^\W_][.\-/])"
DEPOIS = r"(?![^\W_])(?![.\-/][^\W_])"

SO_DIGITOS = re.compile(r"\D")


def tolerante(minimo: int, maximo: int | None = None) -> re.Pattern[str]:
    """Dígitos com no máximo um separador entre eles, dentro das fronteiras."""
    maximo = minimo if maximo is None else maximo
    return re.compile(
        rf"{ANTES}\d(?:{_SEPARADOR}?\d){{{minimo - 1},{maximo - 1}}}{DEPOIS}"
    )
