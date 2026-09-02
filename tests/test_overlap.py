"""Testes do resolvedor de sobreposições."""

from __future__ import annotations

import itertools

import pytest

from redator.entities import Entity, EntityType
from redator.overlap import (
    discard_spurious_fragments,
    resolve_entities,
    resolve_overlaps,
)


def ent(
    start: int,
    end: int,
    *,
    type: EntityType = EntityType.CPF,
    confidence: float = 0.9,
    validated: bool = False,
    detector: str = "teste",
) -> Entity:
    return Entity(
        type=type,
        start=start,
        end=end,
        text="x" * (end - start),
        confidence=confidence,
        detector=detector,
        validated=validated,
    )


def spans(entities: list[Entity]) -> list[tuple[int, int]]:
    return [entity.span for entity in entities]


# --------------------------------------------------------------------------- #
# Casos degenerados
# --------------------------------------------------------------------------- #


def test_lista_vazia() -> None:
    assert resolve_overlaps([]) == []


def test_entidade_unica() -> None:
    unica = ent(0, 14)
    assert resolve_overlaps([unica]) == [unica]


def test_nao_muta_a_entrada() -> None:
    entrada = [ent(10, 20), ent(0, 14), ent(5, 12)]
    copia = list(entrada)
    resolve_overlaps(entrada)
    assert entrada == copia
    assert spans(entrada) == [(10, 20), (0, 14), (5, 12)]


# --------------------------------------------------------------------------- #
# Ordenação do resultado
# --------------------------------------------------------------------------- #


def test_resultado_ordenado_por_start() -> None:
    entrada = [ent(50, 60), ent(0, 10), ent(20, 30), ent(10, 20)]
    assert spans(resolve_overlaps(entrada)) == [(0, 10), (10, 20), (20, 30), (50, 60)]


def test_mesmo_start_ordena_por_end_decrescente() -> None:
    """A externa vem antes da que ela contém."""
    externa = ent(0, 40, type=EntityType.ENDERECO)
    interna = ent(0, 20, type=EntityType.CEP, validated=True)
    assert spans(resolve_overlaps([interna, externa])) == [(0, 40), (0, 20)]
    assert spans(resolve_overlaps([externa, interna])) == [(0, 40), (0, 20)]


def test_ordenacao_de_aninhamento_em_tres_niveis() -> None:
    entidades = [ent(20, 30), ent(0, 50), ent(0, 40)]
    assert spans(resolve_overlaps(entidades)) == [(0, 50), (0, 40), (20, 30)]


# --------------------------------------------------------------------------- #
# Contenção: aninhados convivem
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("externa", "interna"),
    [
        ((0, 40), (10, 20)),  # interna no miolo
        ((0, 40), (0, 20)),  # bordas alinhadas à esquerda
        ((0, 40), (20, 40)),  # bordas alinhadas à direita
        ((0, 40), (39, 40)),  # interna de um caractere
    ],
)
def test_contencao_preserva_ambas(
    externa: tuple[int, int], interna: tuple[int, int]
) -> None:
    resultado = resolve_overlaps([ent(*interna), ent(*externa)])
    assert spans(resultado) == [externa, interna]


def test_contencao_de_tres_niveis_preserva_todas() -> None:
    endereco = ent(0, 60, type=EntityType.ENDERECO)
    cep_com_rotulo = ent(40, 55, type=EntityType.CEP)
    cep = ent(46, 55, type=EntityType.CEP, validated=True)
    resultado = resolve_overlaps([cep, endereco, cep_com_rotulo])
    assert spans(resultado) == [(0, 60), (40, 55), (46, 55)]


def test_endereco_longo_nao_engole_cep_validado_contido() -> None:
    """O motivo da regra: NER extenso e frouxo não pode apagar um DV curto."""
    endereco = ent(0, 48, type=EntityType.ENDERECO, confidence=0.72, validated=False)
    cep = ent(39, 48, type=EntityType.CEP, confidence=0.99, validated=True)
    resultado = resolve_overlaps([endereco, cep])
    assert spans(resultado) == [(0, 48), (39, 48)]
    assert [e.type for e in resultado] == [EntityType.ENDERECO, EntityType.CEP]


def test_contida_sobrevive_quando_a_container_perde_para_terceira() -> None:
    """A container cai numa disputa parcial, mas a aninhada nela permanece."""
    endereco = ent(0, 30, type=EntityType.ENDERECO, validated=False)
    cep = ent(5, 14, type=EntityType.CEP, validated=True)  # contido no ENDERECO
    cpf = ent(25, 45, type=EntityType.CPF, validated=True)  # parcial com ENDERECO
    resultado = resolve_overlaps([endereco, cep, cpf])
    assert spans(resultado) == [(5, 14), (25, 45)]


# --------------------------------------------------------------------------- #
# Sobreposição parcial: disputa
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("a_span", "b_span", "vencedor"),
    [
        ((0, 15), (10, 20), (0, 15)),  # mesmo tamanho, decide o menor start
        ((0, 10), (8, 25), (8, 25)),  # o maior vence
        ((0, 10), (9, 11), (0, 10)),  # um unico caractere em comum
        ((10, 20), (0, 15), (0, 15)),  # mesmo tamanho, fora de ordem
    ],
)
def test_sobreposicao_parcial_mantem_apenas_o_vencedor(
    a_span: tuple[int, int], b_span: tuple[int, int], vencedor: tuple[int, int]
) -> None:
    resultado = resolve_overlaps([ent(*a_span), ent(*b_span)])
    assert spans(resultado) == [vencedor]


@pytest.mark.parametrize(
    ("a_span", "b_span"),
    [
        ((0, 10), (10, 20)),  # adjacentes
        ((10, 20), (0, 10)),  # adjacentes, fora de ordem
        ((0, 5), (30, 40)),  # disjuntos
    ],
)
def test_sem_intersecao_preserva_ambas(
    a_span: tuple[int, int], b_span: tuple[int, int]
) -> None:
    resultado = resolve_overlaps([ent(*a_span), ent(*b_span)])
    assert spans(resultado) == sorted([a_span, b_span])


# --------------------------------------------------------------------------- #
# Cadeias
# --------------------------------------------------------------------------- #


def test_cadeia_de_tres_o_do_meio_perde_e_as_pontas_sobrevivem() -> None:
    """A cruza B, B cruza C, A e C sao disjuntos: B cai, A e C ficam."""
    a = ent(0, 10)  # len 10
    b = ent(8, 14)  # len 6, cruza A e C
    c = ent(12, 22)  # len 10
    resultado = resolve_overlaps([a, b, c])
    assert spans(resultado) == [(0, 10), (12, 22)]


def test_cadeia_o_maior_do_meio_derruba_as_pontas() -> None:
    a = ent(0, 6)
    b = ent(4, 18)  # o mais longo, cruza A e C
    c = ent(16, 22)
    assert spans(resolve_overlaps([a, b, c])) == [(4, 18)]


def test_invariante_nenhuma_sobreposicao_parcial_remanescente() -> None:
    entrada = [
        ent(0, 10),
        ent(8, 14),
        ent(12, 22),
        ent(14, 20),  # contida em (12, 22)
        ent(30, 40, confidence=0.5),
        ent(35, 45, confidence=0.99),
        ent(44, 50),
        ent(0, 60, type=EntityType.ENDERECO),  # contém boa parte das acima
    ]
    resultado = resolve_overlaps(entrada)
    for a, b in itertools.combinations(resultado, 2):
        assert not a.partially_overlaps(b), f"{a.span} cruza {b.span}"
        assert a.span != b.span, f"span {a.span} duplicado"


@pytest.mark.parametrize("permutacao", list(itertools.permutations(range(4))))
def test_independente_da_ordem_de_entrada(permutacao: tuple[int, ...]) -> None:
    base = [
        ent(0, 10, type=EntityType.CPF),
        ent(8, 14, type=EntityType.TELEFONE),
        ent(12, 22, type=EntityType.EMAIL),
        ent(30, 36, type=EntityType.CEP),
    ]
    embaralhado = [base[i] for i in permutacao]
    assert resolve_overlaps(embaralhado) == resolve_overlaps(base)
    assert spans(resolve_overlaps(embaralhado)) == [(0, 10), (12, 22), (30, 36)]


@pytest.mark.parametrize("permutacao", list(itertools.permutations(range(4))))
def test_ordem_de_entrada_nao_afeta_aninhamento(permutacao: tuple[int, ...]) -> None:
    base = [
        ent(0, 30, type=EntityType.ENDERECO),
        ent(5, 14, type=EntityType.CEP, validated=True),
        ent(25, 45, type=EntityType.CPF, validated=True),
        ent(50, 60, type=EntityType.EMAIL),
    ]
    embaralhado = [base[i] for i in permutacao]
    assert resolve_overlaps(embaralhado) == resolve_overlaps(base)
    assert spans(resolve_overlaps(embaralhado)) == [(5, 14), (25, 45), (50, 60)]


# --------------------------------------------------------------------------- #
# Critérios de desempate, um a um
# --------------------------------------------------------------------------- #


def test_criterio_1_validated_vence_mesmo_sendo_muito_mais_curta() -> None:
    """Evidencia de DV vale mais que extensao da deteccao."""
    endereco = ent(0, 30, type=EntityType.ENDERECO, confidence=1.0, validated=False)
    cpf = ent(25, 39, type=EntityType.CPF, confidence=0.30, validated=True)
    assert resolve_overlaps([endereco, cpf]) == [cpf]
    assert resolve_overlaps([cpf, endereco]) == [cpf]


def test_criterio_2_empate_de_validated_maior_comprimento_vence() -> None:
    curta = ent(0, 10, validated=True, confidence=1.0)
    longa = ent(5, 25, validated=True, confidence=0.3)
    assert resolve_overlaps([curta, longa]) == [longa]


def test_criterio_3_empate_de_validated_e_comprimento_maior_confianca_vence() -> None:
    fraca = ent(0, 10, confidence=0.60, validated=True, type=EntityType.CEP)
    forte = ent(3, 13, confidence=0.95, validated=True, type=EntityType.CPF)
    assert resolve_overlaps([fraca, forte]) == [forte]


def test_criterio_4_empate_total_menor_start_vence() -> None:
    primeira = ent(0, 10, confidence=0.9, validated=True, type=EntityType.CPF)
    segunda = ent(3, 13, confidence=0.9, validated=True, type=EntityType.CPF)
    assert resolve_overlaps([segunda, primeira]) == [primeira]


def test_criterio_5_mesmo_span_desempata_por_nome_do_tipo() -> None:
    """Ultimo recurso: ordem alfabetica do EntityType, so para ser deterministico."""
    cpf = ent(0, 10, confidence=0.9, validated=True, type=EntityType.CPF)
    telefone = ent(0, 10, confidence=0.9, validated=True, type=EntityType.TELEFONE)
    assert resolve_overlaps([telefone, cpf]) == [cpf]
    assert resolve_overlaps([cpf, telefone]) == [cpf]


@pytest.mark.parametrize(
    ("a", "b", "esperado_type"),
    [
        (
            ent(0, 10, type=EntityType.CEP, confidence=0.9, validated=True),
            ent(0, 10, type=EntityType.CNPJ, confidence=0.9, validated=True),
            EntityType.CEP,
        ),
        (
            ent(0, 10, type=EntityType.NOME, confidence=0.9, validated=True),
            ent(0, 10, type=EntityType.EMAIL, confidence=0.9, validated=True),
            EntityType.EMAIL,
        ),
    ],
)
def test_desempate_alfabetico_e_estavel(
    a: Entity, b: Entity, esperado_type: EntityType
) -> None:
    assert resolve_overlaps([a, b])[0].type is esperado_type
    assert resolve_overlaps([b, a])[0].type is esperado_type


# --------------------------------------------------------------------------- #
# Spans idênticos competem — não são contenção
# --------------------------------------------------------------------------- #


def test_span_identico_compete_por_validated() -> None:
    cpf = ent(0, 14, type=EntityType.CPF, confidence=0.50, validated=True)
    telefone = ent(0, 14, type=EntityType.TELEFONE, confidence=1.0, validated=False)
    assert resolve_overlaps([telefone, cpf]) == [cpf]
    assert resolve_overlaps([cpf, telefone]) == [cpf]


def test_span_identico_nunca_devolve_as_duas() -> None:
    a = ent(0, 14, type=EntityType.CPF, confidence=0.9, validated=False)
    b = ent(0, 14, type=EntityType.TELEFONE, confidence=0.9, validated=False)
    assert len(resolve_overlaps([a, b])) == 1


# --------------------------------------------------------------------------- #
# Caso concreto: CPF vs. falso TELEFONE
# --------------------------------------------------------------------------- #


def test_cpf_validado_vence_telefone_que_cruza_sua_borda() -> None:
    texto = "Cliente CPF 123.456.789-00 / 3456 cadastrado."
    inicio = texto.index("123")
    cpf = Entity(
        type=EntityType.CPF,
        start=inicio,
        end=inicio + len("123.456.789-00"),
        text="123.456.789-00",
        confidence=0.95,
        detector="cpf_dv",
        validated=True,
    )
    # Falso positivo que comeca no miolo do CPF e vaza para depois dele.
    telefone = Entity(
        type=EntityType.TELEFONE,
        start=inicio + 4,
        end=inicio + len("123.456.789-00 / 3456"),
        text="456.789-00 / 3456",
        confidence=1.0,
        detector="telefone_padrao",
    )
    assert cpf.partially_overlaps(telefone)
    assert resolve_overlaps([telefone, cpf]) == [cpf]
    assert resolve_overlaps([cpf, telefone]) == [cpf]


def test_telefone_falso_contido_no_cpf_e_preservado() -> None:
    """Consequencia da regra de contencao: o miolo nao compete mais.

    O trecho ja fica tarjado pelo CPF que o contem, mas a entidade espuria
    permanece no resultado — cabe ao detector nao emiti-la.
    """
    cpf = ent(12, 26, type=EntityType.CPF, confidence=0.95, validated=True)
    telefone = ent(16, 26, type=EntityType.TELEFONE, confidence=0.80)
    assert cpf.contains(telefone)
    assert spans(resolve_overlaps([telefone, cpf])) == [(12, 26), (16, 26)]


# --------------------------------------------------------------------------- #
# discard_spurious_fragments
# --------------------------------------------------------------------------- #


def test_fragmento_descarta_lista_vazia() -> None:
    assert discard_spurious_fragments([]) == []


def test_fragmento_entidade_unica_sobrevive() -> None:
    unica = ent(0, 14, type=EntityType.CPF, validated=True)
    assert discard_spurious_fragments([unica]) == [unica]


def test_fragmento_nao_muta_a_entrada() -> None:
    cpf = ent(12, 26, type=EntityType.CPF, validated=True)
    telefone = ent(16, 26, type=EntityType.TELEFONE)
    entrada = [cpf, telefone]
    copia = list(entrada)
    discard_spurious_fragments(entrada)
    assert entrada == copia
    assert len(entrada) == 2


def test_telefone_falso_dentro_de_cpf_validado_e_descartado() -> None:
    cpf = ent(12, 26, type=EntityType.CPF, confidence=0.95, validated=True)
    telefone = ent(16, 26, type=EntityType.TELEFONE, confidence=0.80)
    assert discard_spurious_fragments([cpf, telefone]) == [cpf]
    assert discard_spurious_fragments([telefone, cpf]) == [cpf]


@pytest.mark.parametrize(
    "interna_type",
    [EntityType.TELEFONE, EntityType.CEP, EntityType.EMAIL, EntityType.CPF_MASCARADO],
)
def test_fragmento_de_metodo_padrao_e_descartado(interna_type: EntityType) -> None:
    cpf = ent(0, 14, type=EntityType.CPF, validated=True)
    fragmento = ent(4, 14, type=interna_type)
    assert discard_spurious_fragments([cpf, fragmento]) == [cpf]


@pytest.mark.parametrize(
    "interna_type",
    [
        EntityType.RG,
        EntityType.DATA_NASCIMENTO,
        EntityType.AGENCIA_CONTA,
        EntityType.CID,
    ],
)
def test_fragmento_de_metodo_contextual_e_descartado(interna_type: EntityType) -> None:
    cnpj = ent(0, 18, type=EntityType.CNPJ, validated=True)
    fragmento = ent(4, 14, type=interna_type)
    assert discard_spurious_fragments([cnpj, fragmento]) == [cnpj]


def test_cep_validado_dentro_de_endereco_ner_e_preservado() -> None:
    """Par estrutural: a externa e de NER, entao nada e descartado."""
    endereco = ent(0, 48, type=EntityType.ENDERECO, confidence=0.72)
    cep = ent(39, 48, type=EntityType.CEP, confidence=0.99, validated=True)
    resultado = discard_spurious_fragments([endereco, cep])
    assert resultado == [endereco, cep]


def test_cpf_validado_dentro_de_endereco_ner_e_preservado() -> None:
    endereco = ent(0, 60, type=EntityType.ENDERECO)
    cpf = ent(20, 34, type=EntityType.CPF, validated=True)
    assert discard_spurious_fragments([endereco, cpf]) == [endereco, cpf]


def test_cep_nao_validado_dentro_de_endereco_ner_e_preservado() -> None:
    """Mesmo com a interna fraca, NER na externa nunca dispara o descarte."""
    endereco = ent(0, 48, type=EntityType.ENDERECO)
    cep = ent(39, 48, type=EntityType.CEP, validated=False)
    assert discard_spurious_fragments([endereco, cep]) == [endereco, cep]


def test_telefone_dentro_de_telefone_e_preservado() -> None:
    """A externa nao e VALIDADO_DV, entao a regra nao se aplica."""
    externo = ent(0, 20, type=EntityType.TELEFONE)
    interno = ent(5, 15, type=EntityType.TELEFONE)
    assert discard_spurious_fragments([externo, interno]) == [externo, interno]


def test_externa_de_tipo_dv_mas_nao_validada_nao_descarta() -> None:
    """Tipo VALIDADO_DV sem validated=True nao basta."""
    cpf = ent(0, 14, type=EntityType.CPF, validated=False)
    telefone = ent(4, 14, type=EntityType.TELEFONE)
    assert discard_spurious_fragments([cpf, telefone]) == [cpf, telefone]


def test_cpf_validado_dentro_de_cnpj_validado_e_preservado() -> None:
    """A interna tem DV proprio: e um dado, nao um fragmento."""
    cnpj = ent(0, 18, type=EntityType.CNPJ, validated=True)
    cpf = ent(2, 16, type=EntityType.CPF, validated=True)
    assert discard_spurious_fragments([cnpj, cpf]) == [cnpj, cpf]


def test_nome_ner_dentro_de_cpf_validado_e_preservado() -> None:
    """NER nao esta entre os metodos frageis; so PADRAO e CONTEXTUAL sao."""
    cpf = ent(0, 30, type=EntityType.CPF, validated=True)
    nome = ent(5, 20, type=EntityType.NOME)
    assert discard_spurious_fragments([cpf, nome]) == [cpf, nome]


def test_span_identico_nao_e_contencao_e_nao_descarta() -> None:
    cpf = ent(0, 14, type=EntityType.CPF, validated=True)
    telefone = ent(0, 14, type=EntityType.TELEFONE)
    assert discard_spurious_fragments([cpf, telefone]) == [cpf, telefone]


def test_sobreposicao_parcial_nao_descarta() -> None:
    """O filtro so olha contencao; cruzamento e assunto de resolve_overlaps."""
    cpf = ent(0, 14, type=EntityType.CPF, validated=True)
    telefone = ent(10, 24, type=EntityType.TELEFONE)
    assert discard_spurious_fragments([cpf, telefone]) == [cpf, telefone]


def test_aninhamento_de_tres_niveis_so_o_mais_interno_e_espurio() -> None:
    """ENDERECO (NER) > CPF (DV) > TELEFONE (padrao): so o TELEFONE cai."""
    endereco = ent(0, 60, type=EntityType.ENDERECO, confidence=0.70)
    cpf = ent(10, 24, type=EntityType.CPF, confidence=0.95, validated=True)
    telefone = ent(14, 24, type=EntityType.TELEFONE, confidence=0.80)
    resultado = discard_spurious_fragments([endereco, cpf, telefone])
    assert resultado == [endereco, cpf]
    assert spans(resultado) == [(0, 60), (10, 24)]


def test_fragmento_preserva_a_ordenacao() -> None:
    entidades = [
        ent(40, 54, type=EntityType.CPF, validated=True),
        ent(44, 54, type=EntityType.TELEFONE),  # espurio
        ent(0, 60, type=EntityType.ENDERECO),
        ent(0, 20, type=EntityType.NOME),
    ]
    assert spans(discard_spurious_fragments(entidades)) == [(0, 60), (0, 20), (40, 54)]


# --------------------------------------------------------------------------- #
# resolve_entities: as duas etapas encadeadas
# --------------------------------------------------------------------------- #


def test_resolve_entities_encadeia_as_duas_etapas() -> None:
    endereco = ent(0, 60, type=EntityType.ENDERECO)
    cpf = ent(10, 24, type=EntityType.CPF, confidence=0.95, validated=True)
    telefone_espurio = ent(14, 24, type=EntityType.TELEFONE)
    telefone_cruzado = ent(20, 40, type=EntityType.TELEFONE)  # cruza o CPF, perde
    resultado = resolve_entities([telefone_cruzado, telefone_espurio, cpf, endereco])
    assert resultado == [endereco, cpf]


def test_resolve_entities_equivale_a_composicao_manual() -> None:
    entidades = [
        ent(0, 60, type=EntityType.ENDERECO),
        ent(10, 24, type=EntityType.CPF, validated=True),
        ent(14, 24, type=EntityType.TELEFONE),
        ent(20, 40, type=EntityType.TELEFONE),
        ent(70, 79, type=EntityType.CEP, validated=True),
    ]
    assert resolve_entities(entidades) == discard_spurious_fragments(
        resolve_overlaps(entidades)
    )


def test_resolve_entities_nao_muta_a_entrada() -> None:
    entidades = [
        ent(10, 24, type=EntityType.CPF, validated=True),
        ent(14, 24, type=EntityType.TELEFONE),
    ]
    copia = list(entidades)
    resolve_entities(entidades)
    assert entidades == copia
