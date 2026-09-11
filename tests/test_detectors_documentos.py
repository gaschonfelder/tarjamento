"""Testes dos detectores de documentos conferidos por dígito verificador."""

from __future__ import annotations

from pathlib import Path

import pytest

from redator.detectors import Detector
from redator.detectors.documentos import (
    CONFIANCA_AMBIGUA,
    CONFIANCA_ANCORADA,
    CONFIANCA_CANONICA,
    CONFIANCA_IRREGULAR,
    DETECTORES_DOCUMENTOS,
    DetectorDocumento,
    detector_cartao_credito,
    detector_cnh,
    detector_cnpj,
    detector_cns,
    detector_cpf,
    detector_pis,
    detector_processo_cnj,
    detector_titulo_eleitor,
)
from redator.entities import EntityType
from redator.pipeline import detect_all

TEXTOS = Path(__file__).parent / "fixtures" / "textos"

# Tipos sob responsabilidade desta tarefa.
TIPOS_DESTA_TAREFA = frozenset(
    {
        EntityType.CPF,
        EntityType.CNPJ,
        EntityType.PIS,
        EntityType.CNH,
        EntityType.TITULO_ELEITOR,
        EntityType.CNS,
        EntityType.PROCESSO_CNJ,
        EntityType.CARTAO_CREDITO,
    }
)
NOMES_DESTA_TAREFA = frozenset(tipo.name for tipo in TIPOS_DESTA_TAREFA)

# Valores validos. Os de 11/12/14/15 digitos vem dos fixtures (DV conferido
# por tests/fixtures/conferir_numeros.py); CNJ e cartao foram gerados, porque
# nenhum fixture tem esses tipos.
CPF_VALIDO = "529.982.247-25"
CNPJ_VALIDO = "46.634.044/0001-74"
PIS_VALIDO = "120.44567.89-1"
CNH_VALIDA = "02650306461"
TITULO_VALIDO = "0425 5879 0141"
CNS_VALIDO = "174 5987 4356 0003"
CNJ_VALIDO = "0001234-08.2023.8.26.0100"
CARTAO_VALIDO = "4111 1111 1111 1111"


def so_digitos(valor: str) -> str:
    return "".join(c for c in valor if c.isdigit())


# --------------------------------------------------------------------------- #
# Contrato
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("detector", DETECTORES_DOCUMENTOS, ids=lambda d: d.name)
def test_satisfaz_o_protocolo(detector: DetectorDocumento) -> None:
    assert isinstance(detector, Detector)
    assert detector.name
    assert detector.entity_type in TIPOS_DESTA_TAREFA


def test_os_oito_tipos_tem_detector() -> None:
    assert {d.entity_type for d in DETECTORES_DOCUMENTOS} == TIPOS_DESTA_TAREFA


# --------------------------------------------------------------------------- #
# Cada detector acha o seu
# --------------------------------------------------------------------------- #

CASOS_VALIDOS = [
    (detector_cpf, CPF_VALIDO, EntityType.CPF),
    (detector_cnpj, CNPJ_VALIDO, EntityType.CNPJ),
    (detector_pis, PIS_VALIDO, EntityType.PIS),
    (detector_cnh, CNH_VALIDA, EntityType.CNH),
    (detector_titulo_eleitor, TITULO_VALIDO, EntityType.TITULO_ELEITOR),
    (detector_cns, CNS_VALIDO, EntityType.CNS),
    (detector_processo_cnj, CNJ_VALIDO, EntityType.PROCESSO_CNJ),
    (detector_cartao_credito, CARTAO_VALIDO, EntityType.CARTAO_CREDITO),
]


@pytest.mark.parametrize(
    ("detector", "valor", "tipo"), CASOS_VALIDOS, ids=lambda a: getattr(a, "name", "")
)
def test_acha_valor_valido_isolado(
    detector: DetectorDocumento, valor: str, tipo: EntityType
) -> None:
    achadas = detector.detect(valor)
    assert len(achadas) == 1
    entidade = achadas[0]
    assert entidade.type is tipo
    assert entidade.text == valor
    assert entidade.span == (0, len(valor))
    assert entidade.validated is True
    assert entidade.detector == detector.name


@pytest.mark.parametrize(("detector", "valor", "tipo"), CASOS_VALIDOS)
def test_acha_valor_valido_no_meio_da_frase(
    detector: DetectorDocumento, valor: str, tipo: EntityType
) -> None:
    texto = f"Conforme o documento {valor}, fica acordado."
    achadas = detector.detect(texto)
    assert len(achadas) == 1
    assert achadas[0].text == valor
    assert texto[achadas[0].start : achadas[0].end] == valor


@pytest.mark.parametrize(("detector", "valor", "tipo"), CASOS_VALIDOS)
def test_dv_errado_nao_vira_entidade(
    detector: DetectorDocumento, valor: str, tipo: EntityType
) -> None:
    """Numero que nao valida nao e documento: o detector devolve lista vazia."""
    digitos = so_digitos(valor)
    quebrado = digitos[:-1] + str((int(digitos[-1]) + 1) % 10)
    assert detector.detect(quebrado) == []


# --------------------------------------------------------------------------- #
# Tolerância a formatação
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "variante",
    [
        "529.982.247-25",
        "52998224725",
        "529 982 247 25",
        "529-982-247.25",
        "529.982.247.25",
        "529/982/247-25",
    ],
)
def test_cpf_tolera_as_variantes_dos_fixtures(variante: str) -> None:
    achadas = detector_cpf.detect(f"CPF {variante} fim")
    assert len(achadas) == 1, variante
    assert achadas[0].text == variante


@pytest.mark.parametrize(
    ("variante", "esperada"),
    [
        ("529.982.247-25", CONFIANCA_CANONICA),  # mascara oficial
        ("52998224725", CONFIANCA_CANONICA),  # so digitos
        ("529 982 247 25", CONFIANCA_IRREGULAR),
        ("529-982-247.25", CONFIANCA_IRREGULAR),
        ("529.982.247.25", CONFIANCA_IRREGULAR),
    ],
)
def test_confianca_do_cpf_por_formatacao(variante: str, esperada: float) -> None:
    achadas = detector_cpf.detect(variante)
    assert achadas[0].confidence == esperada


@pytest.mark.parametrize(
    ("detector", "valor"),
    [
        (detector_cnpj, CNPJ_VALIDO),
        (detector_titulo_eleitor, TITULO_VALIDO),
        (detector_cns, CNS_VALIDO),
        (detector_processo_cnj, CNJ_VALIDO),
        (detector_cartao_credito, CARTAO_VALIDO),
    ],
)
def test_mascara_oficial_tem_confianca_canonica(
    detector: DetectorDocumento, valor: str
) -> None:
    assert detector.detect(valor)[0].confidence == CONFIANCA_CANONICA


def test_so_existem_os_niveis_declarados_de_confianca() -> None:
    niveis = set()
    for txt in sorted(TEXTOS.glob("*.txt")):
        with txt.open(encoding="utf-8", newline="") as arquivo:
            texto = arquivo.read()
        for detector in DETECTORES_DOCUMENTOS:
            niveis |= {e.confidence for e in detector.detect(texto)}
    assert niveis <= {
        CONFIANCA_ANCORADA,
        CONFIANCA_CANONICA,
        CONFIANCA_IRREGULAR,
        CONFIANCA_AMBIGUA,
    }


# --------------------------------------------------------------------------- #
# Fronteira alfanumérica
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "texto",
    [
        "52998224725-A",  # sufixo alfabetico
        "A-52998224725",  # prefixo alfabetico
        "BR52998224725SP",  # prefixo e sufixo
        "52998224725SP",
        "BR52998224725",
        "529982247250",  # um digito a mais
        "052998224725",  # um digito a mais na frente
        "52998224725.0",  # continua num grupo numerico
        "0.52998224725",
        "04.122.7001.2001.3.3.90.39.00",  # dotacao orcamentaria
        "529.982.247-25-03",  # continua depois do DV
    ],
)
def test_fronteira_rejeita_candidato_colado(texto: str) -> None:
    assert detector_cpf.detect(texto) == [], texto


@pytest.mark.parametrize(
    "texto",
    [
        "52998224725",
        "CPF 52998224725",
        "52998224725 cadastrado",
        "CPF: 52998224725.",
        "(52998224725)",
        "CPF:52998224725",
        "cpf=52998224725;",
        "linha\n52998224725\nlinha",
    ],
)
def test_fronteira_aceita_vizinho_nao_alfanumerico(texto: str) -> None:
    assert len(detector_cpf.detect(texto)) == 1, texto


def test_versao_de_sistema_nao_vira_documento() -> None:
    """10.24.7.25 tem grupos demais e digitos de menos."""
    assert detector_cpf.detect("Versao do sistema: 10.24.7.25") == []


def test_cnpj_nao_vira_cartao() -> None:
    """46634044000174 fecha o Luhn por acaso; a forma escrita e que decide."""
    from redator.validators import is_valid_luhn

    assert is_valid_luhn(so_digitos(CNPJ_VALIDO)) is True
    assert detector_cartao_credito.detect(CNPJ_VALIDO) == []
    assert len(detector_cnpj.detect(CNPJ_VALIDO)) == 1


def test_telefone_com_ddi_nao_vira_cartao() -> None:
    assert detector_cartao_credito.detect("+55 15 99842-7316") == []


@pytest.mark.parametrize(
    "variante", ["4111111111111111", "4111 1111 1111 1111", "4111-1111-1111-1111"]
)
def test_cartao_aceita_agrupamento_real(variante: str) -> None:
    assert len(detector_cartao_credito.detect(variante)) == 1


@pytest.mark.parametrize("variante", ["4111 1111-1111 1111", "41.111.111/1111-111"])
def test_cartao_rejeita_agrupamento_que_nao_e_de_cartao(variante: str) -> None:
    assert detector_cartao_credito.detect(variante) == []


# --------------------------------------------------------------------------- #
# Colisão CNH x PIS — limitação conhecida
# --------------------------------------------------------------------------- #


def test_colisao_cnh_pis_ambos_devolvem_com_confianca_reduzida() -> None:
    """Comportamento CONHECIDO e aceito nesta fase.

    02650306461 fecha o DV de PIS e de CNH. Sem ancora de contexto nao ha como
    saber qual e, entao os dois detectores devolvem, com CONFIANCA_AMBIGUA.
    A desambiguacao por rotulo ("Registro CNH:", "PIS/PASEP:") vem depois.
    """
    from redator.validators import is_valid_cnh, is_valid_pis

    digitos = so_digitos(CNH_VALIDA)
    assert is_valid_pis(digitos) and is_valid_cnh(digitos)

    do_cnh = detector_cnh.detect(CNH_VALIDA)
    do_pis = detector_pis.detect(CNH_VALIDA)
    assert len(do_cnh) == 1 and len(do_pis) == 1
    assert do_cnh[0].confidence == CONFIANCA_AMBIGUA
    assert do_pis[0].confidence == CONFIANCA_AMBIGUA
    assert do_cnh[0].span == do_pis[0].span


def test_colisao_cnh_pis_sem_ancora_o_desempate_e_alfabetico() -> None:
    """Sem rotulo, resolve_entities fica com CNH so porque "CNH" < "PIS".

    Nao ha nada no numero que justifique a escolha: e desempate por criterio
    irrelevante, registrado aqui como limitacao do caso sem ancora.
    """
    resultado = detect_all(f"Registro: {CNH_VALIDA}", list(DETECTORES_DOCUMENTOS))
    assert len(resultado) == 1
    assert resultado[0].type is EntityType.CNH
    assert resultado[0].confidence == CONFIANCA_AMBIGUA


@pytest.mark.parametrize(
    ("rotulo", "esperado"),
    [
        ("Registro CNH: ", EntityType.CNH),
        ("CNH: ", EntityType.CNH),
        ("PIS/PASEP: ", EntityType.PIS),
        ("PIS: ", EntityType.PIS),
        ("NIT: ", EntityType.PIS),
    ],
)
def test_colisao_cnh_pis_a_ancora_decide(rotulo: str, esperado: EntityType) -> None:
    """Com rotulo, so o tipo ancorado e devolvido, e com confianca maxima."""
    resultado = detect_all(f"{rotulo}{CNH_VALIDA}", list(DETECTORES_DOCUMENTOS))
    assert len(resultado) == 1
    assert resultado[0].type is esperado
    assert resultado[0].confidence == CONFIANCA_ANCORADA
    assert resultado[0].context is not None


# --------------------------------------------------------------------------- #
# Âncora negativa suprime, âncora positiva eleva
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "linha",
    [
        "Código interno: 52998224725",
        "Código patrimonial: 11144477735",
        "Número de série: 529-982-247-25",
        "Total de registros processados: 52998224725",
        "Identificador do lote: 12345678909",
        "Chave de integração: 98765432100",
        "Protocolo: 52998224725",
        "Nota de Empenho: 52998224725",
    ],
)
def test_ancora_negativa_suprime_mesmo_com_dv_valido(linha: str) -> None:
    assert detector_cpf.detect(linha) == [], linha


@pytest.mark.parametrize(
    "linha",
    [
        "CPF: 52998224725",
        "CPF nº 529.982.247-25",
        "inscrito no CPF sob o nº 529.982.247-25",
        "CPF do titular: 529.982.247-25",
    ],
)
def test_ancora_positiva_eleva_confianca_e_preenche_context(linha: str) -> None:
    achadas = detector_cpf.detect(linha)
    assert len(achadas) == 1, linha
    assert achadas[0].confidence == CONFIANCA_ANCORADA
    assert achadas[0].context is not None


def test_ancora_do_proprio_tipo_cancela_a_supressao() -> None:
    """ "Processo" e ancora negativa, mas e o rotulo natural do CNJ."""
    achadas = detector_processo_cnj.detect(f"Processo nº {CNJ_VALIDO}")
    assert len(achadas) == 1
    assert achadas[0].confidence == CONFIANCA_ANCORADA


def test_pis_dos_fixtures_nao_colide() -> None:
    """O outro numero de 11 digitos do fixture valida so como PIS."""
    do_pis = detector_pis.detect(PIS_VALIDO)
    assert len(do_pis) == 1
    assert do_pis[0].confidence == CONFIANCA_CANONICA
    assert detector_cnh.detect(so_digitos(PIS_VALIDO)) == []
