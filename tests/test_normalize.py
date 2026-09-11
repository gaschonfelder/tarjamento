"""Testes da normalização e do rastreamento de offsets."""

from __future__ import annotations

import unicodedata

import pytest

from redator.normalize import normalize, span_to_original, to_original

# Casos em que o NFKC muda o comprimento, confirmados contra a tabela Unicode.
LIGADURA_FI = "ﬁ"  # ﬁ  -> "fi"          (1 -> 2)
METRO_SEG2 = "㎨"  # ㎨  -> "m∕s2"        (1 -> 4)
MEIO = "½"  # ½  -> "1⁄2"                (1 -> 3)
E_COMBINANTE = "é"  # e + acento agudo -> "é"  (2 -> 1)

NBSP = " "
ESPACO_FINO = " "
ESPACO_OGAMICO = " "  # Zs que o NFKC nao converte
EN_DASH = "–"
EM_DASH = "—"
HIFEN_TIPO = "‐"
HIFEN_NAO_QUEBRAVEL = "‑"
TRACO_FIGURA = "‒"


# --------------------------------------------------------------------------- #
# Forma do mapa
# --------------------------------------------------------------------------- #


def test_texto_vazio() -> None:
    normalizado, mapa = normalize("")
    assert normalizado == ""
    assert mapa == [0]


@pytest.mark.parametrize(
    "texto",
    [
        "a",
        "CPF 529.982.247-25",
        "Rua das Acacias, 184",
        "linha 1\nlinha 2",
        "tab\tseparado",
    ],
)
def test_texto_sem_nada_a_normalizar_tem_mapa_identidade(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    assert normalizado == texto
    assert mapa == list(range(len(texto) + 1))


@pytest.mark.parametrize(
    "texto",
    ["", "abc", f"a{NBSP}b", f"x{LIGADURA_FI}y", f"n{E_COMBINANTE}o", METRO_SEG2],
)
def test_mapa_tem_uma_entrada_a_mais_e_termina_no_fim(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    assert len(mapa) == len(normalizado) + 1
    assert mapa[-1] == len(texto)


@pytest.mark.parametrize(
    "texto",
    ["abc", f"a{NBSP}b", f"x{LIGADURA_FI}y", f"n{E_COMBINANTE}o", f"{MEIO}{EM_DASH}"],
)
def test_mapa_e_monotonico_e_dentro_do_original(texto: str) -> None:
    _, mapa = normalize(texto)
    assert mapa == sorted(mapa)
    assert all(0 <= indice <= len(texto) for indice in mapa)


# --------------------------------------------------------------------------- #
# NFKC alterando comprimento
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (LIGADURA_FI, "fi"),
        (f"a{LIGADURA_FI}b", "afib"),
        (METRO_SEG2, "m∕s2"),
        (MEIO, "1⁄2"),
        ("ＡＢ", "AB"),
    ],
)
def test_nfkc_expande_um_caractere_em_varios(texto: str, esperado: str) -> None:
    normalizado, mapa = normalize(texto)
    assert normalizado == esperado
    assert len(mapa) == len(normalizado) + 1


def test_expansao_aponta_todos_os_pedacos_para_o_mesmo_original() -> None:
    """Os dois caracteres de "fi" vieram do unico caractere no indice 1."""
    normalizado, mapa = normalize(f"a{LIGADURA_FI}b")
    assert normalizado == "afib"
    assert mapa == [0, 1, 1, 2, 3]


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (E_COMBINANTE, "é"),
        (f"caf{E_COMBINANTE}", "café"),
        ("가", "가"),  # jamo Hangul: dois starters que compoem
    ],
)
def test_nfkc_funde_varios_caracteres_em_um(texto: str, esperado: str) -> None:
    normalizado, _ = normalize(texto)
    assert normalizado == esperado


def test_fusao_mapeia_para_o_inicio_do_bloco() -> None:
    normalizado, mapa = normalize(f"caf{E_COMBINANTE}!")
    assert normalizado == "café!"
    # O "e" acentuado ocupa os indices 3 e 4 do original.
    assert mapa == [0, 1, 2, 3, 5, 6]
    assert span_to_original(3, 4, mapa) == (3, 5)


def test_normalizacao_confere_com_o_nfkc_do_texto_inteiro() -> None:
    texto = f"a{LIGADURA_FI}b {E_COMBINANTE} {METRO_SEG2}\n{MEIO}"
    normalizado, _ = normalize(texto)
    preparado = texto  # nada aqui e hifen nem espaco exotico
    assert normalizado == unicodedata.normalize("NFKC", preparado)


# --------------------------------------------------------------------------- #
# Hífens e espaços
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "hifen", [EN_DASH, EM_DASH, HIFEN_TIPO, HIFEN_NAO_QUEBRAVEL, TRACO_FIGURA]
)
def test_hifen_tipografico_vira_ascii(hifen: str) -> None:
    normalizado, mapa = normalize(f"529.982.247{hifen}25")
    assert normalizado == "529.982.247-25"
    assert mapa == list(range(15))


def test_hifen_ascii_fica_como_esta() -> None:
    normalizado, _ = normalize("529.982.247-25")
    assert normalizado == "529.982.247-25"


@pytest.mark.parametrize("espaco", [NBSP, ESPACO_FINO, ESPACO_OGAMICO, "　", " "])
def test_espaco_unicode_vira_espaco_comum(espaco: str) -> None:
    normalizado, mapa = normalize(f"CPF{espaco}529")
    assert normalizado == "CPF 529"
    assert mapa == list(range(8))


def test_espaco_comum_fica_como_esta() -> None:
    normalizado, _ = normalize("CPF 529")
    assert normalizado == "CPF 529"


# --------------------------------------------------------------------------- #
# O que NÃO pode mudar
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "texto",
    [
        "linha 1\nlinha 2",
        "linha 1\r\nlinha 2",
        "\n\n\n",
        "fim\n",
        "\rcarriage",
        "a b",  # separador de linha Unicode (Zl), nao e Zs
        "a b",  # separador de paragrafo (Zp)
    ],
)
def test_quebras_de_linha_preservadas(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    assert normalizado == texto
    assert mapa == list(range(len(texto) + 1))


@pytest.mark.parametrize(
    "texto",
    ["a  b", "a     b", "  inicio", "fim   ", "col1        col2", "a \n  b"],
)
def test_espacos_multiplos_preservados(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    assert normalizado == texto
    assert mapa == list(range(len(texto) + 1))


@pytest.mark.parametrize("texto", ["CPF", "cpf", "CpF", "MARCELO almeida"])
def test_caixa_preservada(texto: str) -> None:
    normalizado, _ = normalize(texto)
    assert normalizado == texto


def test_nbsp_multiplo_nao_colapsa() -> None:
    normalizado, _ = normalize(f"a{NBSP}{NBSP}{NBSP}b")
    assert normalizado == "a   b"


# --------------------------------------------------------------------------- #
# to_original e span_to_original
# --------------------------------------------------------------------------- #

TEXTOS_ROUND_TRIP = [
    "",
    "abc",
    "CPF 529.982.247-25",
    f"CPF{NBSP}529.982.247{EN_DASH}25",
    f"a{LIGADURA_FI}b",
    f"caf{E_COMBINANTE} quente",
    f"{METRO_SEG2} por {MEIO}",
    "linha 1\nlinha 2\n",
]


@pytest.mark.parametrize("texto", TEXTOS_ROUND_TRIP)
def test_to_original_aceita_todo_indice_valido(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    for indice in range(len(normalizado) + 1):
        assert 0 <= to_original(indice, mapa) <= len(texto)


@pytest.mark.parametrize("texto", TEXTOS_ROUND_TRIP)
def test_to_original_rejeita_indice_fora(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    with pytest.raises(IndexError):
        to_original(len(normalizado) + 1, mapa)
    with pytest.raises(IndexError):
        to_original(-1, mapa)


@pytest.mark.parametrize("texto", TEXTOS_ROUND_TRIP)
def test_span_completo_cobre_o_texto_inteiro(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    assert span_to_original(0, len(normalizado), mapa) == (0, len(texto))


@pytest.mark.parametrize("texto", TEXTOS_ROUND_TRIP)
def test_todo_span_devolve_intervalo_valido(texto: str) -> None:
    normalizado, mapa = normalize(texto)
    for start in range(len(normalizado) + 1):
        for end in range(start, len(normalizado) + 1):
            inicio, fim = span_to_original(start, end, mapa)
            assert 0 <= inicio <= fim <= len(texto)
            if start < end:
                assert fim > inicio, f"span ({start},{end}) virou vazio"


def test_span_no_inicio_e_no_fim_do_texto() -> None:
    texto = "CPF 529.982.247-25"
    normalizado, mapa = normalize(texto)
    assert span_to_original(0, 3, mapa) == (0, 3)
    assert texto[0:3] == "CPF"
    assert span_to_original(4, len(normalizado), mapa) == (4, len(texto))
    assert texto[4:] == "529.982.247-25"


def test_span_recupera_o_trecho_original_com_mascara_tipografica() -> None:
    """O detector ve hifen ASCII; o span devolve o traco original."""
    texto = f"CPF{NBSP}529.982.247{EN_DASH}25 fim"
    normalizado, mapa = normalize(texto)
    assert normalizado == "CPF 529.982.247-25 fim"
    inicio, fim = span_to_original(4, 18, mapa)
    assert texto[inicio:fim] == f"529.982.247{EN_DASH}25"


def test_span_dentro_de_uma_expansao_alarga_para_o_caractere_inteiro() -> None:
    """So o "f" do "fi": nao da para recortar meio caractere original."""
    texto = f"a{LIGADURA_FI}b"
    normalizado, mapa = normalize(texto)
    assert normalizado == "afib"
    inicio, fim = span_to_original(1, 2, mapa)
    assert (inicio, fim) == (1, 2)
    assert texto[inicio:fim] == LIGADURA_FI


def test_span_invertido_e_erro() -> None:
    _, mapa = normalize("abcdef")
    with pytest.raises(ValueError):
        span_to_original(4, 2, mapa)


def test_span_vazio_continua_vazio() -> None:
    _, mapa = normalize("abcdef")
    assert span_to_original(3, 3, mapa) == (3, 3)
