"""Testes do sistema de âncoras de contexto."""

from __future__ import annotations

import pytest

from redator.anchors import (
    ANCORAS_NEGATIVAS,
    ANCORAS_POSITIVAS,
    buscar_ancora,
    contexto_de_endereco,
    tem_ancora_negativa,
    tipo_ancorado,
)
from redator.entities import EntityType


def posicao(texto: str, alvo: str) -> int:
    return texto.index(alvo)


# --------------------------------------------------------------------------- #
# Forma das tabelas
# --------------------------------------------------------------------------- #


def test_todo_entity_type_tem_lista_de_ancoras() -> None:
    assert set(ANCORAS_POSITIVAS) == set(EntityType)


@pytest.mark.parametrize("tipo", list(EntityType))
def test_nenhuma_lista_de_ancoras_esta_vazia(tipo: EntityType) -> None:
    assert ANCORAS_POSITIVAS[tipo]


def test_ancoras_negativas_nao_colidem_com_as_positivas() -> None:
    """Uma excecao deliberada: "processo" e rotulo de CNJ e de numero interno."""
    positivas = {
        rotulo.casefold()
        for rotulos in ANCORAS_POSITIVAS.values()
        for rotulo in rotulos
    }
    negativas = {rotulo.casefold() for rotulo in ANCORAS_NEGATIVAS}
    assert positivas & negativas == {"processo"}


# --------------------------------------------------------------------------- #
# buscar_ancora
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("texto", "alvo", "tipo", "esperado"),
    [
        ("CPF: 529.982.247-25", "529", EntityType.CPF, "CPF"),
        ("CPF nº 529.982.247-25", "529", EntityType.CPF, "CPF nº"),
        (
            "inscrito no CPF sob o nº 529.982.247-25",
            "529",
            EntityType.CPF,
            "inscrito no CPF",
        ),
        ("CPF do titular: 529.982.247-25", "529", EntityType.CPF, "CPF do titular"),
        ("Chave PIX (CPF): 529.982.247-25", "529", EntityType.CPF, "CPF"),
        ("CNPJ nº 46.634.044/0001-74", "46", EntityType.CNPJ, "CNPJ nº"),
        ("Cédula de Identidade RG nº 42.815.739-6", "42", EntityType.RG, "RG nº"),
        (
            "documento de identidade 42.815.739-6",
            "42",
            EntityType.RG,
            "documento de identidade",
        ),
        ("Registro CNH: 02650306461", "026", EntityType.CNH, "Registro CNH"),
        ("PIS/PASEP: 120.44567.89-1", "120", EntityType.PIS, "PIS/PASEP"),
        (
            "Telefone institucional: (15) 3238-0000",
            "(15",
            EntityType.TELEFONE,
            "Telefone",
        ),
        ("Sorocaba/SP, CEP 18035-000", "18035", EntityType.CEP, "CEP"),
        ("Agência: 1847-3", "1847", EntityType.AGENCIA_CONTA, "Agência"),
    ],
)
def test_busca_por_tipo(texto: str, alvo: str, tipo: EntityType, esperado: str) -> None:
    """Entre rotulos que casam na mesma posicao, vence o mais longo."""
    encontrada = buscar_ancora(texto, posicao(texto, alvo), tipo=tipo)
    assert encontrada is not None
    assert encontrada.casefold() == esperado.casefold()


def test_sem_ancora_devolve_none() -> None:
    texto = "Marcelo Henrique de Almeida       529.982.247-25"
    assert buscar_ancora(texto, posicao(texto, "529"), tipo=EntityType.CPF) is None


def test_ancora_de_outro_tipo_nao_serve() -> None:
    texto = "CNPJ: 529.982.247-25"
    assert buscar_ancora(texto, 6, tipo=EntityType.CPF) is None
    assert buscar_ancora(texto, 6, tipo=EntityType.CNPJ) is not None


def test_busca_sem_tipo_devolve_a_mais_proxima() -> None:
    texto = "portador do documento de identidade 42.815.739-6 e CPF 529.982.247-25"
    assert buscar_ancora(texto, posicao(texto, "529")) == "CPF"


# --------------------------------------------------------------------------- #
# A janela é presa à linha
# --------------------------------------------------------------------------- #


def test_valor_no_inicio_da_linha_usa_a_linha_anterior() -> None:
    texto = "RG:\n42.815.739-6"
    assert buscar_ancora(texto, 4, tipo=EntityType.RG) == "RG"


def test_rotulo_com_texto_extra_na_linha_anterior_ainda_ancora() -> None:
    texto = "RG com órgão:\n42.815.739-6 SSP/SP"
    assert buscar_ancora(texto, 14, tipo=EntityType.RG) == "RG"


def test_janela_nao_atravessa_linha_em_branco() -> None:
    texto = "CPF:\n\n529.982.247-25"
    assert buscar_ancora(texto, posicao(texto, "529"), tipo=EntityType.CPF) is None


def test_janela_nao_volta_duas_linhas() -> None:
    texto = "CPF:\nMarcelo Henrique de Almeida\n529.982.247-25"
    assert buscar_ancora(texto, posicao(texto, "529"), tipo=EntityType.CPF) is None


def test_cabecalho_de_tabela_nao_ancora_as_linhas_de_dados() -> None:
    """O caso que quebraria a tabela inteira se a janela fosse so por caracteres.

    Em "NOME;CPF;LOTE;VALOR" o "LOTE" e ancora negativa. Preso a linha, ele nao
    alcanca os CPFs das linhas seguintes.
    """
    texto = "NOME;CPF;LOTE;VALOR\nMarcelo Henrique de Almeida;529.982.247-25;03"
    inicio = posicao(texto, "529")
    assert tem_ancora_negativa(texto, inicio) is False
    assert buscar_ancora(texto, inicio, tipo=EntityType.CPF) is None


def test_janela_respeita_o_limite_de_caracteres() -> None:
    texto = f"CPF{' ' * 60}529.982.247-25"
    assert buscar_ancora(texto, posicao(texto, "529"), tipo=EntityType.CPF) is None
    assert buscar_ancora(texto, posicao(texto, "529"), 80, tipo=EntityType.CPF) == "CPF"


# --------------------------------------------------------------------------- #
# Âncoras negativas
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "linha",
    [
        "Código interno: 52998224725",
        "Código patrimonial: 11144477735",
        "Número de série: 529-982-247-25",
        "Código de rastreamento: BR52998224725SP",
        "Total de registros processados: 52998224725",
        "Identificador do lote: 12345678909",
        "Chave de integração: 98765432100",
        "Protocolo nº 2026.09.08.001842",
        "Nota de Empenho: 2026NE004587",
        "Dotação orçamentária: 04.122.7001.2001",
        "Versão do sistema: 10.24.7.25",
        "Build: 2026.09.08.001842",
        "Ficha orçamentária: 184",
        "Lote: 03",
        "Item: 17",
    ],
)
def test_rotulo_administrativo_e_ancora_negativa(linha: str) -> None:
    posicao_do_numero = next(i for i, c in enumerate(linha) if c.isdigit() and i > 3)
    assert tem_ancora_negativa(linha, posicao_do_numero) is True


@pytest.mark.parametrize(
    "linha",
    [
        "CPF: 52998224725",
        "CNPJ nº 46.634.044/0001-74",
        "Telefone: (15) 99842-7316",
        "Agência: 1847-3",
        "Chave PIX (CPF): 529.982.247-25",
    ],
)
def test_rotulo_de_dado_pessoal_nao_e_ancora_negativa(linha: str) -> None:
    inicio = next(
        i for i, c in enumerate(linha) if c.isdigit() and linha[i - 1] in " ("
    )
    assert tem_ancora_negativa(linha, inicio) is False


def test_ancora_positiva_posterior_cancela_a_negativa() -> None:
    """ "Processo" e negativa, mas o rotulo do proprio tipo vem depois."""
    texto = "Processo nº 0001234-08.2023.8.26.0100"
    inicio = posicao(texto, "0001234")
    assert tipo_ancorado(texto, inicio, tipos=[EntityType.PROCESSO_CNJ]) is not None
    assert tem_ancora_negativa(texto, inicio) is False


def test_ancora_negativa_vence_quando_e_a_mais_proxima() -> None:
    texto = "CPF do responsável, código interno: 52998224725"
    assert tem_ancora_negativa(texto, posicao(texto, "529")) is True


def test_sem_rotulo_nenhum_nao_ha_ancora_negativa() -> None:
    assert tem_ancora_negativa("Marcelo Almeida 52998224725", 16) is False


# --------------------------------------------------------------------------- #
# tipo_ancorado
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("rotulo", "esperado"),
    [
        ("Registro CNH: ", EntityType.CNH),
        ("CNH: ", EntityType.CNH),
        ("PIS/PASEP: ", EntityType.PIS),
        ("NIT: ", EntityType.PIS),
    ],
)
def test_tipo_ancorado_resolve_a_colisao(rotulo: str, esperado: EntityType) -> None:
    texto = f"{rotulo}02650306461"
    resultado = tipo_ancorado(
        texto, len(rotulo), tipos=[EntityType.CNH, EntityType.PIS]
    )
    assert resultado is not None
    assert resultado[0] is esperado


def test_tipo_ancorado_sem_rotulo_devolve_none() -> None:
    texto = "Registro: 02650306461"
    assert tipo_ancorado(texto, 10, tipos=[EntityType.CNH, EntityType.PIS]) is None


def test_tipo_ancorado_prefere_o_rotulo_mais_longo_na_mesma_posicao() -> None:
    texto = "Cartão Nacional de Saúde: 174 5987 4356 0003"
    resultado = tipo_ancorado(texto, posicao(texto, "174"))
    assert resultado is not None
    assert resultado[0] is EntityType.CNS


# --------------------------------------------------------------------------- #
# contexto_de_endereco
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "texto",
    [
        "Rua das Acácias, 184, Jardim Europa, 18045-310",
        "Avenida Central, nº 850, sala 04, 18035-210",
        "com sede administrativa no 18035-000",
        "residente e domiciliado no 18045-310",
    ],
)
def test_reconhece_vizinhanca_de_endereco(texto: str) -> None:
    assert contexto_de_endereco(texto, len(texto) - 9) is True


@pytest.mark.parametrize(
    "texto", ["Valor total 18045310", "Sequência numérica: 18045310"]
)
def test_texto_sem_endereco_nao_da_contexto(texto: str) -> None:
    assert contexto_de_endereco(texto, len(texto) - 8) is False


# --------------------------------------------------------------------------- #
# Robustez
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("start", [0, 1, 5])
def test_inicio_do_texto_nao_quebra(start: int) -> None:
    assert buscar_ancora("529.982.247-25", start, tipo=EntityType.CPF) is None
    assert tem_ancora_negativa("529.982.247-25", start) is False


def test_texto_vazio_nao_quebra() -> None:
    assert buscar_ancora("", 0, tipo=EntityType.CPF) is None
    assert tem_ancora_negativa("", 0) is False
    assert contexto_de_endereco("", 0) is False


@pytest.mark.parametrize("rotulo", ["CPF", "cpf", "Cpf", "cPf"])
def test_busca_e_case_insensitive(rotulo: str) -> None:
    texto = f"{rotulo}: 529.982.247-25"
    assert buscar_ancora(texto, len(rotulo) + 2, tipo=EntityType.CPF) is not None


@pytest.mark.parametrize(
    "separador", [": ", " nº ", " n° ", " n. ", ":", " ", " Nº ", ": \n"]
)
def test_tolera_variacoes_do_separador(separador: str) -> None:
    texto = f"CPF{separador}529.982.247-25"
    inicio = posicao(texto, "529")
    encontrada = buscar_ancora(texto, inicio, tipo=EntityType.CPF)
    assert encontrada is not None
    assert encontrada.casefold().startswith("cpf")


def test_rotulo_nao_casa_pedaco_de_palavra() -> None:
    """ "item" nao pode sair de dentro de "itemizado"."""
    assert tem_ancora_negativa("Relatório itemizado 52998224725", 20) is False
    assert buscar_ancora("CPFs anteriores 52998224725", 16, tipo=EntityType.CPF) is None
