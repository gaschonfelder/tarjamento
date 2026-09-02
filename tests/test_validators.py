"""Testes dos validadores de dígito verificador.

Os números válidos são construídos aqui a partir de uma base, calculando o DV
correto — nenhum documento real aparece no arquivo.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence

import pytest

from redator.validators import (
    is_valid_cnh,
    is_valid_cnpj,
    is_valid_cns,
    is_valid_cpf,
    is_valid_luhn,
    is_valid_pis,
    is_valid_processo_cnj,
    is_valid_titulo_eleitor,
)

# --------------------------------------------------------------------------- #
# Geradores
# --------------------------------------------------------------------------- #


def dv_mod11(digits: str, weights: Sequence[int]) -> int:
    """DV na convenção CPF/CNPJ/PIS: resto < 2 vira 0."""
    total = sum(int(digit) * weight for digit, weight in zip(digits, weights))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def gen_cpf(base: str) -> str:
    assert len(base) == 9
    dv1 = dv_mod11(base, range(10, 1, -1))
    dv2 = dv_mod11(f"{base}{dv1}", range(11, 1, -1))
    return f"{base}{dv1}{dv2}"


def gen_cnpj(base: str) -> str:
    assert len(base) == 12
    dv1 = dv_mod11(base, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    dv2 = dv_mod11(f"{base}{dv1}", (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    return f"{base}{dv1}{dv2}"


def gen_pis(base: str) -> str:
    assert len(base) == 10
    return f"{base}{dv_mod11(base, (3, 2, 9, 8, 7, 6, 5, 4, 3, 2))}"


def gen_titulo(base: str, uf: int) -> str:
    """base = 8 dígitos sequenciais; uf = código de 1 a 28."""
    assert len(base) == 8
    resto_zero = 1 if uf in (1, 2) else 0
    uf_digits = f"{uf:02d}"

    remainder = sum(int(d) * w for d, w in zip(base, range(2, 10))) % 11
    dv1 = resto_zero if remainder == 0 else (0 if remainder == 10 else remainder)

    remainder = (int(uf_digits[0]) * 7 + int(uf_digits[1]) * 8 + dv1 * 9) % 11
    dv2 = resto_zero if remainder == 0 else (0 if remainder == 10 else remainder)

    return f"{base}{uf_digits}{dv1}{dv2}"


def gen_cnh(base: str) -> str:
    assert len(base) == 9
    remainder = sum(int(d) * w for d, w in zip(base, range(9, 0, -1))) % 11
    desconto = 2 if remainder >= 10 else 0
    dv1 = 0 if remainder >= 10 else remainder

    descontado = (
        sum(int(d) * w for d, w in zip(base, range(1, 10))) % 11 - desconto
    ) % 11
    dv2 = 0 if descontado >= 10 else descontado

    return f"{base}{dv1}{dv2}"


def gen_cns_definitivo(base: str) -> str:
    """base = 11 dígitos começando em 1 ou 2."""
    assert len(base) == 11 and base[0] in "12"
    total = sum(int(d) * (15 - i) for i, d in enumerate(base))
    dv = 11 - total % 11
    if dv == 11:
        dv = 0
    if dv == 10:
        return f"{base}001{11 - (total + 2) % 11}"
    return f"{base}000{dv}"


def gen_cns_provisorio(base: str) -> str:
    """base = 13 dígitos começando em 7, 8 ou 9; os 2 últimos são procurados."""
    assert len(base) == 13 and base[0] in "789"
    for sufixo in range(100):
        candidato = f"{base}{sufixo:02d}"
        if sum(int(d) * (15 - i) for i, d in enumerate(candidato)) % 11 == 0:
            return candidato
    raise AssertionError(f"nenhum sufixo fecha o CNS para a base {base}")


def gen_processo_cnj(
    sequencial: str, ano: str, ramo: str, tribunal: str, origem: str
) -> str:
    base = f"{sequencial}{ano}{ramo}{tribunal}{origem}"
    assert len(base) == 18
    dv = 98 - int(f"{base}00") % 97
    return f"{sequencial}{dv:02d}{ano}{ramo}{tribunal}{origem}"


def gen_luhn(base: str) -> str:
    total = 0
    for index, digit in enumerate(reversed(f"{base}0")):
        parcel = int(digit)
        if index % 2 == 1:
            parcel *= 2
            if parcel > 9:
                parcel -= 9
        total += parcel
    return f"{base}{(10 - total % 10) % 10}"


def corromper(numero: str, indice: int = -1) -> str:
    """Troca um dígito para quebrar o DV, preservando o comprimento."""
    posicao = indice % len(numero)
    trocado = str((int(numero[posicao]) + 1) % 10)
    return f"{numero[:posicao]}{trocado}{numero[posicao + 1 :]}"


def mascarar(numero: str, formato: str) -> str:
    """Aplica uma máscara com ``#`` como marcador de dígito."""
    digitos: Iterator[str] = iter(numero)
    return "".join(next(digitos) if char == "#" else char for char in formato)


# --------------------------------------------------------------------------- #
# Amostras válidas
# --------------------------------------------------------------------------- #

CPFS = [gen_cpf(b) for b in ("123456789", "529982247", "000000019", "987654321")]
CNPJS = [gen_cnpj(b) for b in ("112223330001", "343289840001", "000000000191")]
PIS = [gen_pis(b) for b in ("1201234567", "1234567890", "0000000001")]
CNHS = [gen_cnh(b) for b in ("123456789", "047568731", "000000001", "999999998")]
TITULOS = [gen_titulo("12345678", uf) for uf in (1, 2, 13, 26, 28)]
CNS_DEFINITIVOS = [gen_cns_definitivo(b) for b in ("10000000000", "23456789012")]
CNS_PROVISORIOS = [gen_cns_provisorio(b) for b in ("7000000000000", "8981234567890")]
PROCESSOS = [
    gen_processo_cnj("0001234", "2023", "8", "26", "0100"),
    gen_processo_cnj("5001234", "2019", "4", "03", "6100"),
]
CARTOES = [
    gen_luhn(b) for b in ("411111111111111", "555555555555444", "37828224631000")
]


# --------------------------------------------------------------------------- #
# Válidos
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("numero", CPFS)
def test_cpf_valido(numero: str) -> None:
    assert is_valid_cpf(numero) is True


@pytest.mark.parametrize("numero", CNPJS)
def test_cnpj_valido(numero: str) -> None:
    assert is_valid_cnpj(numero) is True


@pytest.mark.parametrize("numero", PIS)
def test_pis_valido(numero: str) -> None:
    assert is_valid_pis(numero) is True


@pytest.mark.parametrize("numero", CNHS)
def test_cnh_valida(numero: str) -> None:
    assert is_valid_cnh(numero) is True


@pytest.mark.parametrize("numero", TITULOS)
def test_titulo_valido(numero: str) -> None:
    assert is_valid_titulo_eleitor(numero) is True


@pytest.mark.parametrize("numero", CNS_DEFINITIVOS + CNS_PROVISORIOS)
def test_cns_valido(numero: str) -> None:
    assert is_valid_cns(numero) is True


@pytest.mark.parametrize("numero", PROCESSOS)
def test_processo_valido(numero: str) -> None:
    assert is_valid_processo_cnj(numero) is True


@pytest.mark.parametrize("numero", CARTOES)
def test_luhn_valido(numero: str) -> None:
    assert is_valid_luhn(numero) is True


# --------------------------------------------------------------------------- #
# DV incorreto
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("validador", "numeros"),
    [
        (is_valid_cpf, CPFS),
        (is_valid_cnpj, CNPJS),
        (is_valid_pis, PIS),
        (is_valid_cnh, CNHS),
        (is_valid_titulo_eleitor, TITULOS),
        (is_valid_cns, CNS_DEFINITIVOS + CNS_PROVISORIOS),
        (is_valid_processo_cnj, PROCESSOS),
        (is_valid_luhn, CARTOES),
    ],
)
def test_dv_incorreto_no_ultimo_digito(
    validador: Callable[[str], bool], numeros: list[str]
) -> None:
    for numero in numeros:
        assert validador(corromper(numero)) is False, numero


@pytest.mark.parametrize(
    ("validador", "numeros"),
    [
        (is_valid_cpf, CPFS),
        (is_valid_cnpj, CNPJS),
        (is_valid_pis, PIS),
        (is_valid_cnh, CNHS),
        (is_valid_cns, CNS_DEFINITIVOS + CNS_PROVISORIOS),
        (is_valid_processo_cnj, PROCESSOS),
        (is_valid_luhn, CARTOES),
    ],
)
def test_dv_incorreto_em_digito_do_meio(
    validador: Callable[[str], bool], numeros: list[str]
) -> None:
    for numero in numeros:
        assert validador(corromper(numero, 5)) is False, numero


# --------------------------------------------------------------------------- #
# Pontos cegos conhecidos do módulo 11
# --------------------------------------------------------------------------- #


def test_cpf_nao_detecta_alteracao_do_primeiro_digito() -> None:
    """Limite real do algoritmo, não defeito do validador.

    O primeiro dígito pesa 11 no segundo DV, e 11 ≡ 0 (mod 11), logo ele não
    influencia o DV2. Quando a alteração também colapsa o DV1 na regra
    ``resto < 2 -> 0``, o número alterado continua fechando.
    """
    assert is_valid_cpf("12345678909") is True
    assert is_valid_cpf("22345678909") is True


def test_cns_provisorio_nao_detecta_alteracao_da_quinta_posicao() -> None:
    """Mesma classe de ponto cego: a quinta posição pesa 11 na soma."""
    numero = CNS_PROVISORIOS[0]
    assert is_valid_cns(numero) is True
    assert is_valid_cns(corromper(numero, 4)) is True


# --------------------------------------------------------------------------- #
# Dígitos repetidos
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("validador", "comprimento"),
    [
        (is_valid_cpf, 11),
        (is_valid_cnpj, 14),
        (is_valid_pis, 11),
        (is_valid_cnh, 11),
    ],
)
@pytest.mark.parametrize("digito", "0123456789")
def test_digitos_repetidos_sao_rejeitados(
    validador: Callable[[str], bool], comprimento: int, digito: str
) -> None:
    assert validador(digito * comprimento) is False


def test_cpf_repetido_fecharia_o_dv_sem_a_regra() -> None:
    """Sanidade: 111.111.111-11 é rejeitado pela regra, não pelo módulo 11."""
    assert dv_mod11("111111111", range(10, 1, -1)) == 1
    assert dv_mod11("1111111111", range(11, 1, -1)) == 1
    assert is_valid_cpf("111.111.111-11") is False


# --------------------------------------------------------------------------- #
# Comprimento errado, vazio, letras e pontuação
# --------------------------------------------------------------------------- #

VALIDADORES_COM_AMOSTRA: list[tuple[Callable[[str], bool], str]] = [
    (is_valid_cpf, CPFS[0]),
    (is_valid_cnpj, CNPJS[0]),
    (is_valid_pis, PIS[0]),
    (is_valid_cnh, CNHS[0]),
    (is_valid_titulo_eleitor, TITULOS[0]),
    (is_valid_cns, CNS_DEFINITIVOS[0]),
    (is_valid_processo_cnj, PROCESSOS[0]),
]


@pytest.mark.parametrize(("validador", "numero"), VALIDADORES_COM_AMOSTRA)
def test_um_digito_a_menos(validador: Callable[[str], bool], numero: str) -> None:
    assert validador(numero[:-1]) is False


@pytest.mark.parametrize(("validador", "numero"), VALIDADORES_COM_AMOSTRA)
def test_um_digito_a_mais(validador: Callable[[str], bool], numero: str) -> None:
    assert validador(f"{numero}7") is False


TODOS_VALIDADORES: list[Callable[[str], bool]] = [
    is_valid_cpf,
    is_valid_cnpj,
    is_valid_pis,
    is_valid_cnh,
    is_valid_titulo_eleitor,
    is_valid_cns,
    is_valid_processo_cnj,
    is_valid_luhn,
]


@pytest.mark.parametrize("validador", TODOS_VALIDADORES)
@pytest.mark.parametrize(
    "entrada",
    [
        "",
        "   ",
        "...",
        "---",
        "./ -",
        "abcdefghijk",
        "CPF nao informado",
        "1234567890a",
        "123.456.789-0X",
        "１２３４５６７８９０１",  # dígitos de largura total
    ],
)
def test_entrada_nao_numerica_e_rejeitada(
    validador: Callable[[str], bool], entrada: str
) -> None:
    assert validador(entrada) is False


@pytest.mark.parametrize("validador", TODOS_VALIDADORES)
def test_nenhum_validador_levanta_excecao(validador: Callable[[str], bool]) -> None:
    for entrada in ("", "0", "-", "9" * 40, "..--//  ", "\n", "1e10"):
        assert validador(entrada) in (True, False)


# --------------------------------------------------------------------------- #
# Normalização: com e sem máscara dão o mesmo resultado
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("validador", "numero", "formato"),
    [
        (is_valid_cpf, CPFS[0], "###.###.###-##"),
        (is_valid_cnpj, CNPJS[0], "##.###.###/####-##"),
        (is_valid_pis, PIS[0], "###.#####.##-#"),
        (is_valid_cnh, CNHS[0], "###.###.###-##"),
        (is_valid_titulo_eleitor, TITULOS[0], "####.####.####"),
        (is_valid_cns, CNS_DEFINITIVOS[0], "### #### #### ####"),
        (is_valid_cns, CNS_PROVISORIOS[0], "### #### #### ####"),
        (is_valid_processo_cnj, PROCESSOS[0], "#######-##.####.#.##.####"),
        (is_valid_luhn, CARTOES[0], "#### #### #### ####"),
    ],
)
def test_mascara_nao_muda_o_resultado(
    validador: Callable[[str], bool], numero: str, formato: str
) -> None:
    mascarado = mascarar(numero, formato)
    assert mascarado != numero
    assert validador(mascarado) is True
    assert validador(numero) is True


@pytest.mark.parametrize(
    ("validador", "numero", "formato"),
    [
        (is_valid_cpf, CPFS[0], "###.###.###-##"),
        (is_valid_cnpj, CNPJS[0], "##.###.###/####-##"),
        (is_valid_processo_cnj, PROCESSOS[0], "#######-##.####.#.##.####"),
    ],
)
def test_mascara_nao_salva_dv_errado(
    validador: Callable[[str], bool], numero: str, formato: str
) -> None:
    assert validador(mascarar(corromper(numero), formato)) is False


# --------------------------------------------------------------------------- #
# Título de eleitor: dependência da UF
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("uf", range(1, 29))
def test_titulo_aceita_toda_uf_valida(uf: int) -> None:
    assert is_valid_titulo_eleitor(gen_titulo("30112233", uf)) is True


@pytest.mark.parametrize("uf_invalida", ["00", "29", "30", "50", "99"])
def test_titulo_rejeita_uf_fora_da_faixa(uf_invalida: str) -> None:
    valido = gen_titulo("12345678", 13)
    fora = f"{valido[:8]}{uf_invalida}{valido[10:]}"
    assert is_valid_titulo_eleitor(fora) is False


def test_titulo_mesma_base_muda_dv_conforme_a_uf() -> None:
    """O segundo DV depende da UF, então o mesmo sequencial gera números diferentes."""
    sp = gen_titulo("12345678", 1)
    rj = gen_titulo("12345678", 19)
    assert sp[:8] == rj[:8]
    assert sp[10:] != rj[10:]
    assert is_valid_titulo_eleitor(sp) is True
    assert is_valid_titulo_eleitor(rj) is True
    # Trocar a UF sem recalcular o DV invalida o número.
    assert is_valid_titulo_eleitor(f"{sp[:8]}19{sp[10:]}") is False


def test_titulo_sp_e_mg_usam_a_regra_do_resto_zero() -> None:
    """Base com resto zero: em SP/MG o DV1 é 1, nas demais UFs é 0."""
    base = "00000000"  # soma zero, logo resto zero
    assert gen_titulo(base, 1)[10] == "1"
    assert gen_titulo(base, 2)[10] == "1"
    assert gen_titulo(base, 13)[10] == "0"
    for uf in (1, 2, 13):
        assert is_valid_titulo_eleitor(gen_titulo(base, uf)) is True
    # O DV de SP não serve para uma UF que usa a regra comum.
    assert is_valid_titulo_eleitor(f"{base}13{gen_titulo(base, 1)[10:]}") is False


# --------------------------------------------------------------------------- #
# CNS: os dois algoritmos
# --------------------------------------------------------------------------- #


def test_cns_definitivo_comeca_em_1_ou_2() -> None:
    for numero in CNS_DEFINITIVOS:
        assert numero[0] in "12"
        assert is_valid_cns(numero) is True


def test_cns_provisorio_comeca_em_7_8_ou_9() -> None:
    for numero in CNS_PROVISORIOS:
        assert numero[0] in "789"
        assert is_valid_cns(numero) is True


def test_cns_definitivo_carrega_sufixo_000_ou_001() -> None:
    for numero in CNS_DEFINITIVOS:
        assert numero[11:14] in ("000", "001")


def test_cns_provisorio_fecha_por_soma_ponderada() -> None:
    for numero in CNS_PROVISORIOS:
        assert sum(int(d) * (15 - i) for i, d in enumerate(numero)) % 11 == 0


@pytest.mark.parametrize("prefixo", ["0", "3", "4", "5", "6"])
def test_cns_rejeita_primeiro_digito_fora_de_12789(prefixo: str) -> None:
    provisorio = CNS_PROVISORIOS[0]
    assert is_valid_cns(f"{prefixo}{provisorio[1:]}") is False


def test_cns_provisorio_nao_passa_pela_regra_do_definitivo() -> None:
    """Um provisório válido não satisfaz o algoritmo de PIS + sufixo."""
    provisorio = CNS_PROVISORIOS[0]
    assert provisorio[11:14] not in ("000", "001") or is_valid_cns(provisorio)
    trocado = f"1{provisorio[1:]}"
    assert is_valid_cns(trocado) is False


# --------------------------------------------------------------------------- #
# Luhn
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("numero", "esperado"),
    [
        ("00", True),  # soma zero
        ("18", True),
        ("26", True),
        ("0", False),  # curto demais
        ("", False),
        ("19", False),
    ],
)
def test_luhn_casos_curtos(numero: str, esperado: bool) -> None:
    assert is_valid_luhn(numero) is esperado


def test_luhn_aceita_comprimentos_de_cartao_variados() -> None:
    for tamanho in (12, 13, 15, 18):
        numero = gen_luhn("4" + "2" * (tamanho - 2))
        assert len(numero) == tamanho
        assert is_valid_luhn(numero) is True


# --------------------------------------------------------------------------- #
# Processo CNJ
# --------------------------------------------------------------------------- #


def test_processo_dv_ocupa_as_posicoes_8_e_9() -> None:
    numero = gen_processo_cnj("0001234", "2023", "8", "26", "0100")
    assert len(numero) == 20
    assert numero[:7] == "0001234"
    assert numero[9:13] == "2023"
    assert is_valid_processo_cnj(numero) is True


@pytest.mark.parametrize("indice", [0, 3, 6, 9, 12, 15, 19])
def test_processo_qualquer_digito_alterado_quebra_o_dv(indice: int) -> None:
    numero = gen_processo_cnj("0001234", "2023", "8", "26", "0100")
    assert is_valid_processo_cnj(corromper(numero, indice)) is False
