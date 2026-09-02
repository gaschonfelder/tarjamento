"""Formatação de valores mascarados."""

from __future__ import annotations

__all__ = ["mask_cpf"]


def mask_cpf(cpf: str) -> str:
    """Formata um CPF como ``***.456.789-**``, preservando os 6 dígitos do meio.

    Aceita o CPF com ou sem pontuação. Não valida dígito verificador — isto aqui
    é só formatação.
    """
    digits = "".join(char for char in cpf if char.isdigit())
    if len(digits) != 11:
        raise ValueError(f"CPF deve ter 11 dígitos, recebido {len(digits)}: {cpf!r}")
    return f"***.{digits[3:6]}.{digits[6:9]}-**"
