"""Formatação de valores mascarados, e a mesma regra em forma de posições.

``mask_cpf`` formata um CPF já conhecido como texto novo — serve para exibição.
``cpf_char_indices_to_hide`` responde a mesma pergunta ("quais dos 11 dígitos
ficam ocultos?") mas devolve ÍNDICES no texto original, não um texto novo: é o
que a redação por caractere (``redator.pdf.pipeline.bboxes_for_entity``) usa
para tarjar só os dígitos das pontas num PDF de verdade, sem tocar na
pontuação nem nos 6 do meio. As duas funções derivam da mesma constante — a
regra "3 primeiros + 2 últimos" existe uma vez só.
"""

from __future__ import annotations

__all__ = ["cpf_char_indices_to_hide", "mask_cpf"]

#: Índices DENTRO DA SEQUÊNCIA DE 11 DÍGITOS (não do texto com pontuação) que
#: ficam ocultos no padrão DOU: os 3 primeiros e os 2 últimos. Os 6 do meio —
#: índices 3 a 8 — permanecem visíveis. Fonte única da regra.
_INDICES_OCULTOS_NOS_DIGITOS = (0, 1, 2, 9, 10)


def _posicoes_dos_digitos(cpf: str) -> list[int]:
    """Os índices de ``cpf`` que são dígitos, na ordem em que aparecem.

    Levanta se não houver exatamente 11 — um CPF, com ou sem pontuação, tem
    sempre 11 dígitos. Serve de validação para as duas funções do módulo.
    """
    posicoes = [indice for indice, char in enumerate(cpf) if char.isdigit()]
    if len(posicoes) != 11:
        raise ValueError(f"CPF deve ter 11 dígitos, recebido {len(posicoes)}: {cpf!r}")
    return posicoes


def mask_cpf(cpf: str) -> str:
    """Formata um CPF como ``***.456.789-**``, preservando os 6 dígitos do meio.

    Aceita o CPF com ou sem pontuação. Não valida dígito verificador — isto aqui
    é só formatação.
    """
    posicoes = _posicoes_dos_digitos(cpf)
    digits = "".join(cpf[i] for i in posicoes)
    return f"***.{digits[3:6]}.{digits[6:9]}-**"


def cpf_char_indices_to_hide(cpf: str) -> list[int]:
    """Os índices de ``cpf`` (com pontuação, se houver) a deixar OCULTOS.

    Mesma regra de :func:`mask_cpf` — os 3 primeiros e os 2 últimos dígitos —,
    mas em posições do texto original em vez de um texto novo formatado.
    Pontuação nunca entra: só índices de dígitos podem aparecer aqui.
    """
    posicoes = _posicoes_dos_digitos(cpf)
    ocultar = {posicoes[i] for i in _INDICES_OCULTOS_NOS_DIGITOS}
    return sorted(ocultar)
