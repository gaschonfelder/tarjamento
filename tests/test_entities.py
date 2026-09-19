"""Testes do modelo de entidades e dos metadados legais."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from redator.entities import (
    ENTITY_METADATA,
    DetectionMethod,
    Entity,
    EntityType,
    LegalCategory,
)
from redator.masking import cpf_char_indices_to_hide, mask_cpf


def make_entity(
    start: int = 0,
    end: int = 10,
    *,
    type: EntityType = EntityType.CPF,
    text: str = "123.456.789-00",
    confidence: float = 0.9,
    detector: str = "teste",
    **kwargs: object,
) -> Entity:
    return Entity(
        type=type,
        start=start,
        end=end,
        text=text,
        confidence=confidence,
        detector=detector,
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- #
# Metadados
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("entity_type", "metodo"),
    [
        (EntityType.CPF, DetectionMethod.VALIDADO_DV),
        (EntityType.CNPJ, DetectionMethod.VALIDADO_DV),
        (EntityType.PIS, DetectionMethod.VALIDADO_DV),
        (EntityType.CNH, DetectionMethod.VALIDADO_DV),
        (EntityType.TITULO_ELEITOR, DetectionMethod.VALIDADO_DV),
        (EntityType.CNS, DetectionMethod.VALIDADO_DV),
        (EntityType.PROCESSO_CNJ, DetectionMethod.VALIDADO_DV),
        (EntityType.CARTAO_CREDITO, DetectionMethod.VALIDADO_DV),
        (EntityType.CPF_MASCARADO, DetectionMethod.PADRAO),
        (EntityType.EMAIL, DetectionMethod.PADRAO),
        (EntityType.TELEFONE, DetectionMethod.PADRAO),
        (EntityType.CEP, DetectionMethod.PADRAO),
        (EntityType.RG, DetectionMethod.CONTEXTUAL),
        (EntityType.DATA_NASCIMENTO, DetectionMethod.CONTEXTUAL),
        (EntityType.AGENCIA_CONTA, DetectionMethod.CONTEXTUAL),
        (EntityType.CHAVE_PIX, DetectionMethod.CONTEXTUAL),
        (EntityType.CID, DetectionMethod.CONTEXTUAL),
        (EntityType.NOME, DetectionMethod.NER),
        (EntityType.ENDERECO, DetectionMethod.NER),
    ],
)
def test_metodo_de_deteccao(entity_type: EntityType, metodo: DetectionMethod) -> None:
    assert entity_type.metodo is metodo
    assert entity_type.metadata.metodo is metodo


@pytest.mark.parametrize(
    ("entity_type", "categoria"),
    [
        (EntityType.CNPJ, LegalCategory.PESSOA_JURIDICA),
        (EntityType.CID, LegalCategory.SENSIVEL),
        (EntityType.NOME, LegalCategory.PUBLICO_OBRIGATORIO),
        (EntityType.PROCESSO_CNJ, LegalCategory.PUBLICO_OBRIGATORIO),
        (EntityType.CPF, LegalCategory.PESSOAL),
        (EntityType.CPF_MASCARADO, LegalCategory.PESSOAL),
        (EntityType.RG, LegalCategory.PESSOAL),
        (EntityType.PIS, LegalCategory.PESSOAL),
        (EntityType.CNH, LegalCategory.PESSOAL),
        (EntityType.TITULO_ELEITOR, LegalCategory.PESSOAL),
        (EntityType.CNS, LegalCategory.PESSOAL),
        (EntityType.CARTAO_CREDITO, LegalCategory.PESSOAL),
        (EntityType.EMAIL, LegalCategory.PESSOAL),
        (EntityType.TELEFONE, LegalCategory.PESSOAL),
        (EntityType.CEP, LegalCategory.PESSOAL),
        (EntityType.DATA_NASCIMENTO, LegalCategory.PESSOAL),
        (EntityType.AGENCIA_CONTA, LegalCategory.PESSOAL),
        (EntityType.CHAVE_PIX, LegalCategory.PESSOAL),
        (EntityType.ENDERECO, LegalCategory.PESSOAL),
    ],
)
def test_categoria_legal(entity_type: EntityType, categoria: LegalCategory) -> None:
    assert entity_type.categoria is categoria
    assert entity_type.metadata.categoria is categoria


def test_todo_tipo_tem_metadados() -> None:
    assert set(ENTITY_METADATA) == set(EntityType)


# --------------------------------------------------------------------------- #
# Validação
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("start", "end", "confidence"),
    [
        (-1, 5, 0.5),
        (-10, -5, 0.5),
        (5, 5, 0.5),
        (5, 4, 0.5),
        (0, 10, -0.1),
        (0, 10, 1.1),
        (0, 10, 42.0),
    ],
)
def test_entidade_invalida_levanta_value_error(
    start: int, end: int, confidence: float
) -> None:
    with pytest.raises(ValueError):
        make_entity(start, end, confidence=confidence)


@pytest.mark.parametrize(
    ("start", "end", "confidence"),
    [(0, 1, 0.0), (0, 1, 1.0), (0, 14, 0.5), (100, 114, 0.999)],
)
def test_entidade_valida_nos_limites(start: int, end: int, confidence: float) -> None:
    entity = make_entity(start, end, confidence=confidence)
    assert entity.span == (start, end)


def test_entidade_e_imutavel() -> None:
    entity = make_entity()
    with pytest.raises(FrozenInstanceError):
        entity.start = 5  # type: ignore[misc]


def test_defaults() -> None:
    entity = make_entity()
    assert entity.validated is False
    assert entity.context is None
    assert entity.requires_review is False


# --------------------------------------------------------------------------- #
# Propriedades
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("start", "end", "length"),
    [(0, 1, 1), (0, 14, 14), (10, 24, 14), (100, 101, 1)],
)
def test_length_e_span(start: int, end: int, length: int) -> None:
    entity = make_entity(start, end)
    assert entity.length == length
    assert entity.span == (start, end)


@pytest.mark.parametrize(
    ("a_span", "b_span", "esperado"),
    [
        ((0, 10), (0, 10), True),  # idênticos
        ((0, 10), (2, 5), True),  # contido
        ((2, 5), (0, 10), True),  # contém
        ((0, 10), (5, 15), True),  # parcial à direita
        ((5, 15), (0, 10), True),  # parcial à esquerda
        ((0, 10), (9, 20), True),  # um caractere em comum
        ((0, 10), (10, 20), False),  # adjacentes
        ((10, 20), (0, 10), False),  # adjacentes, invertidos
        ((0, 5), (10, 20), False),  # disjuntos
    ],
)
def test_overlaps(
    a_span: tuple[int, int], b_span: tuple[int, int], esperado: bool
) -> None:
    a = make_entity(*a_span)
    b = make_entity(*b_span)
    assert a.overlaps(b) is esperado
    assert b.overlaps(a) is esperado


@pytest.mark.parametrize(
    ("externa", "interna", "esperado"),
    [
        ((0, 40), (10, 20), True),  # no miolo
        ((0, 40), (0, 20), True),  # borda esquerda alinhada
        ((0, 40), (20, 40), True),  # borda direita alinhada
        ((0, 40), (39, 40), True),  # um unico caractere
        ((0, 40), (0, 40), False),  # span identico nao e contencao
        ((0, 40), (30, 50), False),  # cruza a borda
        ((0, 40), (40, 50), False),  # adjacente
        ((10, 20), (0, 40), False),  # direcao invertida
    ],
)
def test_contains(
    externa: tuple[int, int], interna: tuple[int, int], esperado: bool
) -> None:
    assert make_entity(*externa).contains(make_entity(*interna)) is esperado


@pytest.mark.parametrize(
    ("a_span", "b_span", "esperado"),
    [
        ((0, 15), (10, 20), True),  # cruzamento verdadeiro
        ((0, 10), (9, 11), True),  # um unico caractere em comum
        ((0, 40), (10, 20), False),  # contencao
        ((10, 20), (0, 40), False),  # contencao, invertida
        ((0, 40), (0, 20), False),  # contencao com borda alinhada
        ((0, 40), (0, 40), False),  # span identico
        ((0, 10), (10, 20), False),  # adjacentes
        ((0, 5), (30, 40), False),  # disjuntos
    ],
)
def test_partially_overlaps(
    a_span: tuple[int, int], b_span: tuple[int, int], esperado: bool
) -> None:
    a = make_entity(*a_span)
    b = make_entity(*b_span)
    assert a.partially_overlaps(b) is esperado
    assert b.partially_overlaps(a) is esperado


@pytest.mark.parametrize(
    ("a_span", "b_span"),
    [
        ((0, 15), (10, 20)),
        ((0, 40), (10, 20)),
        ((0, 40), (0, 40)),
        ((0, 10), (10, 20)),
        ((0, 5), (30, 40)),
    ],
)
def test_contencao_e_cruzamento_sao_mutuamente_exclusivos(
    a_span: tuple[int, int], b_span: tuple[int, int]
) -> None:
    a = make_entity(*a_span)
    b = make_entity(*b_span)
    assert not (a.partially_overlaps(b) and (a.contains(b) or b.contains(a)))
    # Toda intersecao é exatamente uma das três: contenção, span idêntico ou
    # cruzamento parcial.
    if a.overlaps(b):
        assert (
            a.contains(b)
            or b.contains(a)
            or a.span == b.span
            or a.partially_overlaps(b)
        )


# --------------------------------------------------------------------------- #
# mask_cpf
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("123.456.789-00", "***.456.789-**"),
        ("12345678900", "***.456.789-**"),
        ("123 456 789 00", "***.456.789-**"),
        ("00000000191", "***.000.001-**"),
        ("CPF: 529.982.247-25", "***.982.247-**"),
    ],
)
def test_mask_cpf(entrada: str, esperado: str) -> None:
    assert mask_cpf(entrada) == esperado


@pytest.mark.parametrize(
    "entrada",
    ["", "123", "1234567890", "123456789000", "123.456.789-0", "abcdefghijk"],
)
def test_mask_cpf_rejeita_tamanho_errado(entrada: str) -> None:
    with pytest.raises(ValueError):
        mask_cpf(entrada)


# --------------------------------------------------------------------------- #
# cpf_char_indices_to_hide
# --------------------------------------------------------------------------- #


def test_cpf_char_indices_to_hide_com_pontuacao() -> None:
    # "529.982.247-25": indices 0,1,2,3,4,5,6,7,8,9,10,11,12,13
    #                    5  2  9  .  9  8  2  .  2  4  7  -  2  5
    # digitos ficam em  0  1  2     4  5  6     8  9 10    12 13
    # ocultos: os 3 primeiros (0,1,2) e os 2 ultimos (12,13) dos digitos
    assert cpf_char_indices_to_hide("529.982.247-25") == [0, 1, 2, 12, 13]


def test_cpf_char_indices_to_hide_sem_pontuacao() -> None:
    # 11 digitos corridos: ocultos sao as 3 primeiras e as 2 ultimas posicoes
    assert cpf_char_indices_to_hide("52998224725") == [0, 1, 2, 9, 10]


def test_cpf_char_indices_to_hide_indices_ocultos_sao_todos_digitos() -> None:
    """Nunca aponta para pontuacao — so ha o que ocultar, nunca o que pular."""
    texto = "529.982.247-25"
    for indice in cpf_char_indices_to_hide(texto):
        assert texto[indice].isdigit()


def test_cpf_char_indices_to_hide_visiveis_sao_o_meio() -> None:
    """O complemento dos indices ocultos e exatamente os 6 digitos do meio e a pontuacao."""
    texto = "529.982.247-25"
    ocultos = set(cpf_char_indices_to_hide(texto))
    visiveis = "".join(c for i, c in enumerate(texto) if i not in ocultos)
    assert visiveis == ".982.247-"


def test_cpf_char_indices_to_hide_rejeita_tamanho_errado() -> None:
    with pytest.raises(ValueError):
        cpf_char_indices_to_hide("123.456.789-0")


def test_cpf_char_indices_to_hide_mesma_regra_de_mask_cpf() -> None:
    """As duas funcoes tem que concordar: os digitos ocultos aqui sao os
    digitos que mask_cpf substitui por asterisco."""
    texto = "529.982.247-25"
    ocultos = set(cpf_char_indices_to_hide(texto))
    digitos_ocultos = "".join(c for i, c in enumerate(texto) if i in ocultos and c.isdigit())
    assert digitos_ocultos == "52925"
    assert mask_cpf(texto) == "***.982.247-**"
