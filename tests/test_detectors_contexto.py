"""Testes dos detectores contextuais e de contato."""

from __future__ import annotations

import pytest

from redator.detectors import Detector
from redator.detectors.contato import (
    CONFIANCA_ANCORADA,
    CONFIANCA_FRACA,
    CONFIANCA_PADRAO,
    DDDS_VALIDOS,
    DETECTORES_CONTATO,
    detector_cep,
    detector_cpf_mascarado,
    detector_email,
    detector_telefone,
)
from redator.detectors.contextual import (
    DETECTORES_CONTEXTUAIS,
    detector_agencia_conta,
    detector_chave_pix,
    detector_cid,
    detector_data_nascimento,
    detector_rg,
)
from redator.entities import EntityType

TODOS = [*DETECTORES_CONTATO, *DETECTORES_CONTEXTUAIS]


@pytest.mark.parametrize("detector", TODOS, ids=lambda d: d.name)
def test_satisfaz_o_protocolo(detector: Detector) -> None:
    assert isinstance(detector, Detector)
    assert detector.name


# --------------------------------------------------------------------------- #
# Âncora obrigatória nos contextuais
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("detector", "valor"),
    [
        (detector_rg, "42.815.739-6"),
        (detector_agencia_conta, "00284715-9"),
        (detector_chave_pix, "550e8400-e29b-41d4-a716-446655440000"),
        (detector_cid, "F41.1"),
        (detector_data_nascimento, "18/04/1985"),
    ],
    ids=lambda a: getattr(a, "name", ""),
)
def test_sem_ancora_nao_devolve_nada(detector: Detector, valor: str) -> None:
    assert detector.detect(valor) == []
    assert detector.detect(f"O numero {valor} aparece solto.") == []


@pytest.mark.parametrize(
    ("detector", "linha", "valor"),
    [
        (detector_rg, "RG: 42.815.739-6", "42.815.739-6"),
        (detector_rg, "RG nº 33.742.918-2", "33.742.918-2"),
        (detector_rg, "RG:\n428157396", "428157396"),
        (detector_rg, "Cédula de Identidade RG nº 42.815.739-6", "42.815.739-6"),
        (detector_rg, "documento de identidade 42.815.739-6", "42.815.739-6"),
        (detector_agencia_conta, "Agência: 1847-3", "1847-3"),
        (detector_agencia_conta, "Conta Corrente: 00284715-9", "00284715-9"),
        (detector_agencia_conta, "Ag. 0001", "0001"),
        (detector_agencia_conta, "C/C: 9182746-2", "9182746-2"),
        (detector_cid, "CID: F41.1", "F41.1"),
        (detector_cid, "CID-10: J45", "J45"),
        (detector_data_nascimento, "Data de nascimento: 18/04/1985", "18/04/1985"),
        (detector_data_nascimento, "nascido em 18/04/1985", "18/04/1985"),
        (detector_data_nascimento, "nascida em 02.01.1979", "02.01.1979"),
    ],
    ids=lambda a: getattr(a, "name", ""),
)
def test_com_ancora_acha_e_preenche_context(
    detector: Detector, linha: str, valor: str
) -> None:
    achadas = detector.detect(linha)
    assert len(achadas) == 1, linha
    assert achadas[0].text == valor
    assert achadas[0].context is not None
    assert achadas[0].confidence == CONFIANCA_ANCORADA
    assert linha[achadas[0].start : achadas[0].end] == valor


def test_rg_nao_engole_o_orgao_emissor() -> None:
    """O orgao pode vir depois, mas o dado e o numero."""
    achadas = detector_rg.detect("RG nº 42.815.739-6 SSP/SP")
    assert len(achadas) == 1
    assert achadas[0].text == "42.815.739-6"


def test_ancora_de_outro_tipo_nao_serve_ao_contextual() -> None:
    assert detector_rg.detect("CPF: 42.815.739-6") == []
    assert detector_agencia_conta.detect("Protocolo: 00284715-9") == []


# --------------------------------------------------------------------------- #
# Chave PIX aceita os quatro formatos
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "valor",
    [
        "550e8400-e29b-41d4-a716-446655440000",
        "juliana.ferreira@example.com",
        "529.982.247-25",
        "+55 (15) 99842-7316",
    ],
)
def test_chave_pix_aceita_os_quatro_formatos(valor: str) -> None:
    achadas = detector_chave_pix.detect(f"Chave PIX: {valor}")
    assert len(achadas) == 1
    assert achadas[0].text == valor
    assert achadas[0].type is EntityType.CHAVE_PIX


def test_chave_pix_emprestada_tem_confianca_menor_que_a_aleatoria() -> None:
    """Quando o valor tem tipo proprio, CHAVE_PIX cede o span para ele.

    O golden set anota a chave CPF como CPF e a chave e-mail como EMAIL, com
    contexto "chave_pix". Só a chave aleatoria é CHAVE_PIX de fato, e por isso
    só ela sai com confianca cheia.
    """
    aleatoria = detector_chave_pix.detect(
        "Chave PIX aleatória: 550e8400-e29b-41d4-a716-446655440000"
    )
    emprestada = detector_chave_pix.detect("Chave PIX (CPF): 529.982.247-25")
    assert aleatoria[0].confidence > emprestada[0].confidence


# --------------------------------------------------------------------------- #
# Telefone
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "variante",
    [
        "(15) 99842-7316",
        "15 99842 7316",
        "15998427316",
        "+55 15 99842-7316",
        "+55 (15) 99842 7316",
        "+55 (15) 99842-7316",
        "(15) 3238-0000",
    ],
)
def test_telefone_aceita_as_variantes_dos_fixtures(variante: str) -> None:
    achadas = detector_telefone.detect(f"Telefone: {variante}")
    assert len(achadas) == 1, variante
    assert achadas[0].text == variante


@pytest.mark.parametrize("ddd", [20, 23, 25, 26, 29, 30, 36, 39, 40, 50, 52, 90])
def test_telefone_rejeita_ddd_nao_atribuido(ddd: int) -> None:
    assert ddd not in DDDS_VALIDOS
    assert detector_telefone.detect(f"Telefone: ({ddd}) 99842-7316") == []


@pytest.mark.parametrize("ddd", [11, 15, 21, 31, 41, 51, 61, 71, 81, 91, 99])
def test_telefone_aceita_ddd_atribuido(ddd: int) -> None:
    assert ddd in DDDS_VALIDOS
    assert len(detector_telefone.detect(f"Telefone: ({ddd}) 99842-7316")) == 1


@pytest.mark.parametrize(
    "numero",
    [
        "(15) 89842-7316",  # celular de 9 digitos que nao comeca em 9
        "(15) 1238-0000",  # fixo comecando em 1
        "(15) 6238-0000",  # fixo comecando em 6
    ],
)
def test_telefone_rejeita_assinante_implausivel(numero: str) -> None:
    assert detector_telefone.detect(f"Telefone: {numero}") == []


@pytest.mark.parametrize(
    "cpf", ["52998224725", "11144477735", "12345678909", "98765432100"]
)
def test_cpf_de_11_digitos_nao_vira_telefone(cpf: str) -> None:
    """O filtro de DDD e de assinante e o que separa os dois comprimentos."""
    assert detector_telefone.detect(cpf) == []


def test_telefone_sem_ancora_ainda_e_detectado() -> None:
    achadas = detector_telefone.detect("Ligue (15) 99842-7316 hoje")
    assert len(achadas) == 1
    assert achadas[0].confidence == CONFIANCA_PADRAO


# --------------------------------------------------------------------------- #
# E-mail
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "valor",
    [
        "marcelo.almeida@example.com",
        "MARCELO.ALMEIDA@EXAMPLE.COM",
        "juliana.ferreira@example.com",
        "atendimento@fundacao-exemplo.gov.br",
    ],
)
def test_email_acha_as_variantes_dos_fixtures(valor: str) -> None:
    achadas = detector_email.detect(f"Contato {valor} para retorno.")
    assert len(achadas) == 1
    assert achadas[0].text == valor


@pytest.mark.parametrize("texto", ["sem arroba", "a@", "@dominio.com", "a@b"])
def test_email_rejeita_o_que_nao_e_email(texto: str) -> None:
    assert detector_email.detect(texto) == []


def test_email_com_ancora_tem_confianca_maxima() -> None:
    ancorado = detector_email.detect("E-mail: marcelo.almeida@example.com")
    solto = detector_email.detect("veja marcelo.almeida@example.com agora")
    assert ancorado[0].confidence == CONFIANCA_ANCORADA
    assert solto[0].confidence == CONFIANCA_PADRAO


# --------------------------------------------------------------------------- #
# CEP: o padrão mais frágil
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("valor", ["18045-310", "18045310"])
def test_cep_acha_com_e_sem_hifen(valor: str) -> None:
    achadas = detector_cep.detect(f"CEP {valor}")
    assert len(achadas) == 1
    assert achadas[0].text == valor
    assert achadas[0].confidence == CONFIANCA_ANCORADA


def test_cep_com_contexto_de_endereco_sem_rotulo() -> None:
    achadas = detector_cep.detect("Rua das Acácias, 184, Jardim Europa, 18045-310")
    assert len(achadas) == 1
    assert achadas[0].confidence == CONFIANCA_PADRAO
    assert achadas[0].requires_review is False


def test_cep_sem_rotulo_nem_endereco_sai_fraco_e_para_revisao() -> None:
    achadas = detector_cep.detect("Sequência registrada: 18045310")
    assert len(achadas) == 1
    assert achadas[0].confidence == CONFIANCA_FRACA
    assert achadas[0].requires_review is True


def test_cep_nao_casa_dentro_de_numero_maior() -> None:
    assert detector_cep.detect("CEP 180453101") == []
    assert detector_cep.detect("CEP 1804531") == []


# --------------------------------------------------------------------------- #
# CPF mascarado
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "valor",
    [
        "529.XXX.XXX-25",
        "111.XXX.XXX-35",
        "123.XXX.XXX-09",
        "***.982.247-**",
        "***.***.***-**",
    ],
)
def test_cpf_mascarado_acha_os_dois_formatos(valor: str) -> None:
    achadas = detector_cpf_mascarado.detect(f"CPF: {valor}")
    assert len(achadas) == 1
    assert achadas[0].text == valor
    assert achadas[0].type is EntityType.CPF_MASCARADO


def test_cpf_inteiro_nao_e_cpf_mascarado() -> None:
    """Sem nenhum grupo oculto e CPF comum, que tem detector proprio."""
    assert detector_cpf_mascarado.detect("CPF: 529.982.247-25") == []


@pytest.mark.parametrize("valor", ["529.XXX.XXX-25", "***.982.247-**"])
def test_cpf_mascarado_sempre_requer_revisao(valor: str) -> None:
    """redator.redacao nunca tarja isto automaticamente — sem o sinal, o
    revisor nao saberia que precisa decidir manualmente."""
    (achada,) = detector_cpf_mascarado.detect(f"CPF: {valor}")
    assert achada.requires_review is True


# --------------------------------------------------------------------------- #
# Âncora negativa também suprime aqui
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("detector", "linha"),
    [
        (detector_cep, "Código interno: 18045310"),
        (detector_telefone, "Código de rastreamento: (15) 99842-7316"),
        (detector_agencia_conta, "Lote: 000184"),
        (detector_rg, "Protocolo: 428157396"),
    ],
    ids=lambda a: getattr(a, "name", ""),
)
def test_ancora_negativa_suprime(detector: Detector, linha: str) -> None:
    assert detector.detect(linha) == []
