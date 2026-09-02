"""Validação de dígito verificador de documentos brasileiros.

Funções puras: sem I/O, sem estado global e sem extração por regex. Cada uma
recebe o documento como texto — com ou sem máscara — e devolve apenas se os
dígitos verificadores fecham. Entrada malformada devolve ``False``; nenhuma
função levanta exceção.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "is_valid_cnh",
    "is_valid_cnpj",
    "is_valid_cns",
    "is_valid_cpf",
    "is_valid_luhn",
    "is_valid_pis",
    "is_valid_processo_cnj",
    "is_valid_titulo_eleitor",
]

_ASCII_DIGITS = frozenset("0123456789")
_MASK_CHARS = str.maketrans("", "", ".-/ ")

# Códigos de UF do título de eleitor: 01 (SP) a 28 (Exterior).
_UF_MIN = 1
_UF_MAX = 28
# Em SP e MG o resto zero produz DV 1, e não 0.
_UF_RESTO_ZERO_VIRA_UM = frozenset({1, 2})


def _only_digits(value: str) -> str | None:
    """Remove pontos, hífens, barras e espaços.

    Devolve ``None`` se sobrar qualquer caractere que não seja dígito ASCII —
    isso reprova letras, símbolos e também dígitos Unicode exóticos que
    ``str.isdigit`` aceitaria.
    """
    stripped = value.translate(_MASK_CHARS)
    if not stripped or not _ASCII_DIGITS.issuperset(stripped):
        return None
    return stripped


def _normalize(value: str, length: int) -> str | None:
    """``_only_digits`` mais a exigência de comprimento exato."""
    digits = _only_digits(value)
    if digits is None or len(digits) != length:
        return None
    return digits


def _all_same(digits: str) -> bool:
    """Sequências como ``00000000000`` fecham o DV mas nunca são documentos."""
    return len(set(digits)) == 1


def _mod11_dv(digits: str, weights: Sequence[int]) -> int:
    """DV por módulo 11 na convenção de CPF/CNPJ/PIS: resto < 2 vira 0."""
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cpf(value: str) -> bool:
    """CPF: 11 dígitos, dois DVs por módulo 11 com pesos 10..2 e 11..2."""
    digits = _normalize(value, 11)
    if digits is None or _all_same(digits):
        return False
    dv1 = _mod11_dv(digits[:9], range(10, 1, -1))
    dv2 = _mod11_dv(digits[:10], range(11, 1, -1))
    return digits[9:] == f"{dv1}{dv2}"


def is_valid_cnpj(value: str) -> bool:
    """CNPJ: 14 dígitos, dois DVs por módulo 11 com pesos cíclicos 2..9."""
    digits = _normalize(value, 14)
    if digits is None or _all_same(digits):
        return False
    dv1 = _mod11_dv(digits[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    dv2 = _mod11_dv(digits[:13], (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return digits[12:] == f"{dv1}{dv2}"


def is_valid_pis(value: str) -> bool:
    """PIS/PASEP/NIT: 11 dígitos, um DV por módulo 11 com pesos 3,2,9..2."""
    digits = _normalize(value, 11)
    if digits is None or _all_same(digits):
        return False
    dv = _mod11_dv(digits[:10], (3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return digits[10] == str(dv)


def is_valid_titulo_eleitor(value: str) -> bool:
    """Título de eleitor: 12 dígitos, dois DVs por módulo 11.

    Os dígitos 9-10 são o código de UF (01 a 28) e entram no segundo DV. Em SP
    (01) e MG (02) o resto zero produz DV 1 em vez de 0, porque a numeração
    desses estados estourou a faixa original.
    """
    digits = _normalize(value, 12)
    if digits is None:
        return False

    uf = int(digits[8:10])
    if not _UF_MIN <= uf <= _UF_MAX:
        return False
    resto_zero = 1 if uf in _UF_RESTO_ZERO_VIRA_UM else 0

    total = sum(int(digit) * weight for digit, weight in zip(digits[:8], range(2, 10)))
    remainder = total % 11
    dv1 = resto_zero if remainder == 0 else (0 if remainder == 10 else remainder)

    total = int(digits[8]) * 7 + int(digits[9]) * 8 + dv1 * 9
    remainder = total % 11
    dv2 = resto_zero if remainder == 0 else (0 if remainder == 10 else remainder)

    return digits[10:] == f"{dv1}{dv2}"


def is_valid_cnh(value: str) -> bool:
    """CNH: 11 dígitos, dois DVs por módulo 11 com pesos 9..1 e 1..9.

    Quando o primeiro resto é 10 o DV1 vira 0 e o segundo DV é descontado em 2.
    O desconto é aplicado módulo 11 e um resultado de dois dígitos vira 0, de
    modo que todo prefixo de 9 dígitos tenha exatamente um par de DVs válido.
    Implementações que subtraem sem reduzir produzem valores negativos e
    rejeitam esses casos.
    """
    digits = _normalize(value, 11)
    if digits is None or _all_same(digits):
        return False

    base = digits[:9]
    total = sum(int(digit) * weight for digit, weight in zip(base, range(9, 0, -1)))
    remainder = total % 11
    desconto = 2 if remainder >= 10 else 0
    dv1 = 0 if remainder >= 10 else remainder

    total = sum(int(digit) * weight for digit, weight in zip(base, range(1, 10)))
    descontado = (total % 11 - desconto) % 11
    dv2 = 0 if descontado >= 10 else descontado

    return digits[9:] == f"{dv1}{dv2}"


def _cns_definitivo(digits: str) -> bool:
    """CNS iniciado em 1 ou 2: PIS de 11 dígitos mais sufixo calculado."""
    pis = digits[:11]
    total = sum(int(digit) * (15 - index) for index, digit in enumerate(pis))
    dv = 11 - total % 11
    if dv == 11:
        dv = 0
    if dv == 10:
        # O DV de dois dígitos não cabe: soma-se 2 e o sufixo passa a 001.
        dv = 11 - (total + 2) % 11
        return digits == f"{pis}001{dv}"
    return digits == f"{pis}000{dv}"


def _cns_provisorio(digits: str) -> bool:
    """CNS iniciado em 7, 8 ou 9: soma ponderada 15..1 divisível por 11."""
    total = sum(int(digit) * (15 - index) for index, digit in enumerate(digits))
    return total % 11 == 0


def is_valid_cns(value: str) -> bool:
    """Cartão Nacional de Saúde: 15 dígitos, com dois algoritmos distintos.

    Números definitivos começam em 1 ou 2 e carregam um PIS nos 11 primeiros
    dígitos; provisórios começam em 7, 8 ou 9 e são validados pela soma
    ponderada do número inteiro. Qualquer outro dígito inicial é inválido.
    """
    digits = _normalize(value, 15)
    if digits is None:
        return False
    if digits[0] in "12":
        return _cns_definitivo(digits)
    if digits[0] in "789":
        return _cns_provisorio(digits)
    return False


def is_valid_processo_cnj(value: str) -> bool:
    """Processo CNJ (Res. 65/2008): 20 dígitos, DV por módulo 97 (ISO 7064).

    O DV ocupa as posições 8-9; o restante do número, na ordem original e
    seguido de ``00``, deve satisfazer ``98 - resto % 97 == DV``.
    """
    digits = _normalize(value, 20)
    if digits is None:
        return False
    dv = int(digits[7:9])
    base = digits[:7] + digits[9:]
    return 98 - int(base + "00") % 97 == dv


def is_valid_luhn(value: str) -> bool:
    """Algoritmo de Luhn: dobra os dígitos de posição ímpar a partir da direita.

    Genérico, sem comprimento fixo — o chamador é quem decide se o número tem
    tamanho de cartão. Exige ao menos dois dígitos.
    """
    digits = _only_digits(value)
    if digits is None or len(digits) < 2:
        return False
    total = 0
    for index, digit in enumerate(reversed(digits)):
        parcel = int(digit)
        if index % 2 == 1:
            parcel *= 2
            if parcel > 9:
                parcel -= 9
        total += parcel
    return total % 10 == 0
