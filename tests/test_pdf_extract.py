"""Testes da camada de extração PDF -> texto + posição.

Os PDFs são gerados em ``tmp_path`` a cada execução pelo gerador em
``tests/fixtures/pdf/``. Nenhum binário é versionado.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType

import pymupdf
import pytest

from redator.detectors import TODOS_DETECTORES
from redator.entities import EntityType
from redator.pdf import (
    CharBox,
    DocumentExtraction,
    PageExtraction,
    bboxes_for_span,
    extract_pdf,
)
from redator.pipeline import detect_all

BBox = tuple[float, float, float, float]


def rect_da_pagina(caminho: Path, numero: int = 0) -> BBox:
    documento = pymupdf.open(str(caminho))
    try:
        rect = documento[numero].rect
        return (rect.x0, rect.y0, rect.x1, rect.y1)
    finally:
        documento.close()


def nao_degenerado(bbox: BBox) -> bool:
    return bbox[2] > bbox[0] and bbox[3] > bbox[1]


# --------------------------------------------------------------------------- #
# Extração básica
# --------------------------------------------------------------------------- #


def test_extrai_uma_pagina(pdf_documentos: Path) -> None:
    documento = extract_pdf(pdf_documentos)
    assert isinstance(documento, DocumentExtraction)
    assert len(documento.pages) == 1
    assert documento.pages[0].page == 0


@pytest.mark.parametrize(
    "esperado",
    [
        "CPF",
        "529.982.247-25",
        "CNPJ",
        "46.634.044/0001-74",
        "Telefone",
        "(15) 99842-7316",
        "CPF nº 529.982.247-25",
    ],
)
def test_texto_contem_o_que_foi_inserido(pdf_documentos: Path, esperado: str) -> None:
    texto = extract_pdf(pdf_documentos).pages[0].text
    assert esperado in texto, texto


def test_acentos_sobrevivem_a_extracao(pdf_cep: Path) -> None:
    texto = extract_pdf(pdf_cep).pages[0].text
    assert "Acácias" in texto
    assert "nº" in texto


def test_linhas_separadas_por_quebra_sem_quebra_final(pdf_cep: Path) -> None:
    texto = extract_pdf(pdf_cep).pages[0].text
    assert texto.count("\n") == 1
    assert not texto.endswith("\n")


def test_aceita_str_e_path(pdf_documentos: Path) -> None:
    por_path = extract_pdf(pdf_documentos)
    por_str = extract_pdf(str(pdf_documentos))
    assert por_path.pages[0].text == por_str.pages[0].text


# --------------------------------------------------------------------------- #
# A invariante: um CharBox por caractere
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "nome", ["pdf_documentos", "pdf_cep", "pdf_quebrado", "pdf_vazio", "pdf_so_imagem"]
)
def test_texto_e_caixas_tem_o_mesmo_comprimento(
    nome: str, request: pytest.FixtureRequest
) -> None:
    caminho: Path = request.getfixturevalue(nome)
    for pagina in extract_pdf(caminho).pages:
        assert len(pagina.text) == len(pagina.char_boxes), pagina.page


def test_cada_caixa_corresponde_ao_caractere_na_mesma_posicao(
    pdf_documentos: Path,
) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    for indice, caixa in enumerate(pagina.char_boxes):
        assert caixa.char == pagina.text[indice]


def test_page_extraction_rejeita_comprimentos_diferentes() -> None:
    """A invariante é verificada na construção, não só por convenção."""
    with pytest.raises(ValueError, match="posicao a posicao"):
        PageExtraction(
            page=0,
            text="abc",
            char_boxes=[CharBox(char="a", bbox=(0.0, 0.0, 1.0, 1.0), page=0)],
        )


def test_toda_caixa_carrega_o_numero_da_pagina(pdf_documentos: Path) -> None:
    for pagina in extract_pdf(pdf_documentos).pages:
        assert all(caixa.page == pagina.page for caixa in pagina.char_boxes)


# --------------------------------------------------------------------------- #
# Geometria
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("nome", ["pdf_documentos", "pdf_cep", "pdf_quebrado"])
def test_toda_caixa_cabe_na_pagina(nome: str, request: pytest.FixtureRequest) -> None:
    caminho: Path = request.getfixturevalue(nome)
    x0, y0, x1, y1 = rect_da_pagina(caminho)
    for pagina in extract_pdf(caminho).pages:
        for caixa in pagina.char_boxes:
            bx0, by0, bx1, by1 = caixa.bbox
            assert x0 <= bx0 <= x1, (caixa.char, caixa.bbox)
            assert x0 <= bx1 <= x1, (caixa.char, caixa.bbox)
            assert y0 <= by0 <= y1, (caixa.char, caixa.bbox)
            assert y0 <= by1 <= y1, (caixa.char, caixa.bbox)


def test_caixas_de_caractere_visivel_nao_sao_degeneradas(pdf_documentos: Path) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    visiveis = [c for c in pagina.char_boxes if not c.char.isspace()]
    assert visiveis
    assert all(nao_degenerado(c.bbox) for c in visiveis)


def test_caixas_avancam_da_esquerda_para_a_direita(pdf_documentos: Path) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    primeira_linha = pagina.text.index("\n")
    xs = [c.bbox[0] for c in pagina.char_boxes[:primeira_linha]]
    assert xs == sorted(xs)


# --------------------------------------------------------------------------- #
# bboxes_for_span
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "alvo", ["529.982.247-25", "46.634.044/0001-74", "CPF", "(15) 99842-7316"]
)
def test_span_numa_linha_devolve_um_retangulo(pdf_documentos: Path, alvo: str) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    inicio = pagina.text.index(alvo)
    caixas = bboxes_for_span(pagina, inicio, inicio + len(alvo))
    assert len(caixas) == 1
    assert nao_degenerado(caixas[0])


def test_retangulo_cobre_os_caracteres_do_span(pdf_documentos: Path) -> None:
    """A união tem de conter cada caixa individual, e nada mais largo."""
    pagina = extract_pdf(pdf_documentos).pages[0]
    alvo = "529.982.247-25"
    inicio = pagina.text.index(alvo)
    fim = inicio + len(alvo)
    (uniao,) = bboxes_for_span(pagina, inicio, fim)
    individuais = [c.bbox for c in pagina.char_boxes[inicio:fim]]
    assert uniao[0] == min(b[0] for b in individuais)
    assert uniao[2] == max(b[2] for b in individuais)
    assert uniao[1] == min(b[1] for b in individuais)
    assert uniao[3] == max(b[3] for b in individuais)


def test_span_e_mais_estreito_que_a_linha_inteira(pdf_documentos: Path) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    alvo = "529.982.247-25"
    inicio = pagina.text.index(alvo)
    (recorte,) = bboxes_for_span(pagina, inicio, inicio + len(alvo))
    (linha,) = bboxes_for_span(pagina, 0, pagina.text.index("\n"))
    assert recorte[0] > linha[0]
    assert recorte[2] - recorte[0] < linha[2] - linha[0]


def test_span_que_cruza_duas_linhas_devolve_dois_retangulos(
    pdf_quebrado: Path,
) -> None:
    """O CPF partido entre linhas: dois retangulos, nao um envolvendo o vao."""
    pagina = extract_pdf(pdf_quebrado).pages[0]
    alvo = "529.982.\n247-25"
    inicio = pagina.text.index(alvo)
    caixas = bboxes_for_span(pagina, inicio, inicio + len(alvo))

    assert len(caixas) == 2
    assert all(nao_degenerado(c) for c in caixas)
    primeira, segunda = caixas
    # A segunda linha comeca mais a esquerda e mais abaixo.
    assert segunda[1] > primeira[3] or segunda[1] > primeira[1]
    assert segunda[0] < primeira[0]


def test_quebra_de_linha_nao_entra_na_uniao(pdf_quebrado: Path) -> None:
    """O \\n tem caixa de largura zero e e separador, nao tinta."""
    pagina = extract_pdf(pdf_quebrado).pages[0]
    quebra = pagina.text.index("\n")
    caixa_da_quebra = pagina.char_boxes[quebra]
    assert caixa_da_quebra.char == "\n"
    assert caixa_da_quebra.bbox[0] == caixa_da_quebra.bbox[2]
    assert bboxes_for_span(pagina, quebra, quebra + 1) == []


def test_span_vazio_nao_devolve_retangulo(pdf_documentos: Path) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    assert bboxes_for_span(pagina, 5, 5) == []


def test_span_do_texto_inteiro_devolve_um_retangulo_por_linha(
    pdf_documentos: Path,
) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    caixas = bboxes_for_span(pagina, 0, len(pagina.text))
    assert len(caixas) == pagina.text.count("\n") + 1


@pytest.mark.parametrize(("inicio", "fim"), [(-1, 5), (0, 10_000), (-3, -1)])
def test_span_fora_da_pagina_e_erro(
    pdf_documentos: Path, inicio: int, fim: int
) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    with pytest.raises(IndexError):
        bboxes_for_span(pagina, inicio, fim)


def test_span_invertido_e_erro(pdf_documentos: Path) -> None:
    pagina = extract_pdf(pdf_documentos).pages[0]
    with pytest.raises(ValueError):
        bboxes_for_span(pagina, 10, 3)


# --------------------------------------------------------------------------- #
# Páginas sem texto
# --------------------------------------------------------------------------- #


def test_pagina_em_branco(pdf_vazio: Path) -> None:
    documento = extract_pdf(pdf_vazio)
    assert len(documento.pages) == 1
    assert documento.pages[0].text == ""
    assert documento.pages[0].char_boxes == []


def test_pagina_so_com_imagem(pdf_so_imagem: Path) -> None:
    """PDF digitalizado e entrada legitima: devolve vazio, nao excecao."""
    documento = extract_pdf(pdf_so_imagem)
    assert len(documento.pages) == 1
    assert documento.pages[0].text == ""
    assert documento.pages[0].char_boxes == []


def test_span_em_pagina_vazia_nao_quebra(pdf_vazio: Path) -> None:
    pagina = extract_pdf(pdf_vazio).pages[0]
    assert bboxes_for_span(pagina, 0, 0) == []


def test_varias_paginas_em_branco(gerador: ModuleType, tmp_path: Path) -> None:
    caminho = gerador.gerar_pdf_vazio(tmp_path / "tres.pdf", paginas=3)
    documento = extract_pdf(caminho)
    assert [p.page for p in documento.pages] == [0, 1, 2]
    assert all(p.text == "" for p in documento.pages)


def test_texto_do_documento_concatena_as_paginas(pdf_documentos: Path) -> None:
    documento = extract_pdf(pdf_documentos)
    assert documento.text == documento.pages[0].text


# --------------------------------------------------------------------------- #
# Tabela por colunas posicionadas: a fileira visual vira uma linha de texto
# --------------------------------------------------------------------------- #


def test_cabecalho_da_tabela_fica_na_mesma_linha(pdf_tabela_posicionada: Path) -> None:
    """ "Nome" e "CPF" sao celulas separadas no PDF; no texto sao uma linha so."""
    texto = extract_pdf(pdf_tabela_posicionada).pages[0].text
    cabecalho = texto.split("\n")[0]
    assert re.fullmatch(r"Nome +CPF", cabecalho), repr(cabecalho)


def test_fileira_de_dados_fica_na_mesma_linha(pdf_tabela_posicionada: Path) -> None:
    linhas = extract_pdf(pdf_tabela_posicionada).pages[0].text.split("\n")
    assert re.fullmatch(r"Marcelo Henrique de Almeida +529\.982\.247-25", linhas[1])
    assert re.fullmatch(r"Juliana Cristina Ferreira +111\.444\.777-35", linhas[2])


def test_tabela_tem_uma_linha_de_texto_por_fileira(
    pdf_tabela_posicionada: Path,
) -> None:
    texto = extract_pdf(pdf_tabela_posicionada).pages[0].text
    assert texto.count("\n") == 2


def test_espaco_sintetico_entre_celulas_preenche_o_vao(
    pdf_tabela_posicionada: Path,
) -> None:
    """Um unico espaco, cuja caixa vai do fim de "Almeida" ao inicio do CPF."""
    pagina = extract_pdf(pdf_tabela_posicionada).pages[0]
    fim_nome = pagina.text.index("Almeida") + len("Almeida")
    inicio_cpf = pagina.text.index("529.982.247-25")
    assert inicio_cpf == fim_nome + 1

    espaco = pagina.char_boxes[fim_nome]
    assert espaco.char == " "
    assert espaco.bbox[0] == pagina.char_boxes[fim_nome - 1].bbox[2]
    assert espaco.bbox[2] == pagina.char_boxes[inicio_cpf].bbox[0]
    assert espaco.bbox[2] - espaco.bbox[0] > 50  # o vao entre as colunas e real
    assert nao_degenerado(espaco.bbox)


def test_span_na_fileira_reconstruida_e_um_retangulo_so(
    pdf_tabela_posicionada: Path,
) -> None:
    pagina = extract_pdf(pdf_tabela_posicionada).pages[0]
    inicio = pagina.text.index("Almeida")
    fim = pagina.text.index("529.982.247-25") + len("529.982.247-25")
    caixas = bboxes_for_span(pagina, inicio, fim)
    assert len(caixas) == 1
    assert nao_degenerado(caixas[0])


def test_tres_colunas_fundem_na_ordem_horizontal(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """Celulas escritas fora de ordem saem da esquerda para a direita."""
    caminho = gerador.gerar_pdf_celulas(
        tmp_path / "tres.pdf",
        [
            (300.0, 100.0, "meio", 11.0),
            (72.0, 100.0, "esquerda", 11.0),
            (450.0, 100.0, "direita", 11.0),
        ],
    )
    texto = extract_pdf(caminho).pages[0].text
    assert re.fullmatch(r"esquerda +meio +direita", texto), repr(texto)


def test_celulas_com_fonte_muito_maior_nao_fundem(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """Sobrepoem-se em y, mas a razao de fonte (11pt x 32pt) passa do limite.

    E o caso 2 do criterio: titulo grande ao lado de corpo pequeno continua
    em linhas separadas. O controle com 11pt x 11pt funde normalmente.
    """
    grande = gerador.gerar_pdf_celulas(
        tmp_path / "grande.pdf",
        [(72.0, 100.0, "CPF:", 11.0), (200.0, 100.0, "529.982.247-25", 32.0)],
    )
    assert "\n" in extract_pdf(grande).pages[0].text

    controle = gerador.gerar_pdf_celulas(
        tmp_path / "controle.pdf",
        [(72.0, 100.0, "CPF:", 11.0), (200.0, 100.0, "529.982.247-25", 11.0)],
    )
    assert "\n" not in extract_pdf(controle).pages[0].text


def test_regressao_3b_fonte_maior_na_mesma_line_continua_partindo(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """Dois spans encostados na mesma line do rawdict, 11pt e 32pt.

    Aqui nao ha fusao de lines em jogo — o PyMuPDF ja entrega uma line so. O
    que se preserva e bboxes_for_span partir o retangulo por fonte, como ja
    fazia: um cabecalho grande nao vira a mesma caixa que a nota ao lado.
    """
    x = 72.0 + pymupdf.get_text_length("CPF nº ", fontname="helv", fontsize=11)
    caminho = gerador.gerar_pdf_celulas(
        tmp_path / "3b.pdf",
        [(72.0, 100.0, "CPF nº ", 11.0), (x, 100.0, "529.982.247-25", 32.0)],
    )
    pagina = extract_pdf(caminho).pages[0]
    assert pagina.text == "CPF nº 529.982.247-25"  # uma line, sem quebra
    assert len(bboxes_for_span(pagina, 0, len(pagina.text))) == 2

    controle = gerador.gerar_pdf_celulas(
        tmp_path / "3b_controle.pdf",
        [(72.0, 100.0, "CPF nº ", 11.0), (x, 100.0, "529.982.247-25", 11.0)],
    )
    pagina = extract_pdf(controle).pages[0]
    assert len(bboxes_for_span(pagina, 0, len(pagina.text))) == 1


def test_caso_a_espaco_literal_nao_muda(gerador: ModuleType, tmp_path: Path) -> None:
    """A tabela escrita com espacos de preenchimento sai identica ao inserido."""
    linhas = [f"{nome:<34}{cpf}" for nome, cpf in gerador.TABELA_POSICIONADA]
    caminho = gerador.gerar_pdf(tmp_path / "literal.pdf", linhas)
    texto = extract_pdf(caminho).pages[0].text
    assert texto == "\n".join(linhas)
    assert texto.split("\n")[1].count(" ") == 7 + 3  # 7 de preenchimento + 3 do nome


def test_linhas_empilhadas_nao_fundem(gerador: ModuleType, tmp_path: Path) -> None:
    """Fileiras diferentes (y distintos) continuam separadas por quebra."""
    caminho = gerador.gerar_pdf_celulas(
        tmp_path / "empilhadas.pdf",
        [(72.0, 100.0, "primeira", 11.0), (72.0, 130.0, "segunda", 11.0)],
    )
    assert extract_pdf(caminho).pages[0].text == "primeira\nsegunda"


# --------------------------------------------------------------------------- #
# Pipeline sobre a fileira reconstruida
# --------------------------------------------------------------------------- #


def test_pipeline_acha_cpf_ancorado_no_formulario_posicionado(
    pdf_formulario_posicionado: Path,
) -> None:
    """O motivo de tudo isto: o rotulo em outra celula precisa ancorar o valor."""
    texto = extract_pdf(pdf_formulario_posicionado).pages[0].text
    entidades = detect_all(texto, list(TODOS_DETECTORES))

    cpfs = [e for e in entidades if e.type is EntityType.CPF]
    assert len(cpfs) == 1
    assert cpfs[0].text == "529.982.247-25"
    assert cpfs[0].validated is True
    assert cpfs[0].context is not None
    assert cpfs[0].confidence == 0.99

    ceps = [e for e in entidades if e.type is EntityType.CEP]
    assert len(ceps) == 1
    assert ceps[0].context is not None
    assert ceps[0].confidence == 0.99


def test_pipeline_acha_os_cpfs_da_tabela_com_cabecalho(
    pdf_tabela_posicionada: Path,
) -> None:
    """Na tabela com cabecalho, os CPFs vem pelo DV; o rotulo fica em outra linha."""
    texto = extract_pdf(pdf_tabela_posicionada).pages[0].text
    cpfs = sorted(
        (
            e
            for e in detect_all(texto, list(TODOS_DETECTORES))
            if e.type is EntityType.CPF
        ),
        key=lambda e: e.start,
    )
    assert [e.text for e in cpfs] == ["529.982.247-25", "111.444.777-35"]
    assert all(e.validated for e in cpfs)
