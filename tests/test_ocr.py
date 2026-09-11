"""Testes do OCR.

Duas familias. A primeira nao precisa do binario: valida estruturas, o
Protocol, a montagem da pagina a partir do formato que o Tesseract devolve,
a granularidade por palavra, e o caminho de PDF digitalizado com um motor
falso. A segunda roda o Tesseract de verdade e e PULADA, com aviso claro,
quando ele nao esta instalado — nunca falha por ausencia do binario.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from pathlib import Path
from types import ModuleType
from typing import Any

import pymupdf
import pytest
from PIL import Image

from redator.detectors import TODOS_DETECTORES
from redator.entities import EntityType
from redator.ocr import (
    LIMIAR_CONFIANCA_PADRAO,
    OcrEngine,
    TesseractEngine,
    extract_pdf_scanned,
    montar_pagina_de_dados,
    tesseract_disponivel,
)
from redator.pdf import (
    CharBox,
    DocumentExtraction,
    LowConfidenceWord,
    PageExtraction,
    bboxes_for_span,
    extract_pdf,
    gerar_pdf_debug,
    process_pdf,
)

TESSERACT = tesseract_disponivel()
requer_tesseract = pytest.mark.skipif(
    not TESSERACT,
    reason="Tesseract não encontrado — instale e configure para rodar este teste",
)

DETECTORES = list(TODOS_DETECTORES)
CPF = "529.982.247-25"
LINHA_CPF = f"CPF nº {CPF}"
DIGITOS_CPF = "52998224725"

BBox = tuple[float, float, float, float]

# --------------------------------------------------------------------------- #
# O que image_to_data(output_type=DICT) devolve, montado a mao
# --------------------------------------------------------------------------- #

CHAVES = (
    "level",
    "page_num",
    "block_num",
    "par_num",
    "line_num",
    "word_num",
    "left",
    "top",
    "width",
    "height",
    "conf",
    "text",
)

# (block, par, line, word, left, top, width, height, conf, text)
PALAVRAS_FALSAS: list[tuple[int, int, int, int, int, int, int, int, float, str]] = [
    (1, 1, 1, 1, 80, 80, 90, 40, 96.0, "CPF"),
    (1, 1, 1, 2, 190, 80, 50, 40, 91.0, "nº"),
    (1, 1, 1, 3, 260, 80, 380, 40, 88.5, CPF),
    (1, 1, 2, 1, 80, 150, 160, 40, 45.0, "segunda"),  # abaixo do limiar
    (1, 1, 2, 2, 260, 150, 100, 40, 93.0, "linha"),
]
TEXTO_FALSO = f"{LINHA_CPF}\nsegunda linha"


def dados_falsos() -> dict[str, list[Any]]:
    dados: dict[str, list[Any]] = {chave: [] for chave in CHAVES}

    def linha(
        level: int,
        b: int,
        p: int,
        ln: int,
        w: int,
        left: int,
        top: int,
        width: int,
        height: int,
        conf: float,
        text: str,
    ) -> None:
        for chave, valor in zip(
            CHAVES, (level, 1, b, p, ln, w, left, top, width, height, conf, text)
        ):
            dados[chave].append(valor)

    # Nivel de pagina, como o Tesseract emite: texto vazio e conf -1.
    linha(1, 0, 0, 0, 0, 0, 0, 1600, 300, -1, "")
    for palavra in PALAVRAS_FALSAS:
        linha(5, *palavra)
    return dados


class EngineFalso:
    """Devolve sempre a pagina de dados_falsos(), sem OCR nenhum."""

    def __init__(self) -> None:
        self.chamadas = 0

    def extract_text(self, imagem: Image.Image) -> PageExtraction:
        self.chamadas += 1
        return montar_pagina_de_dados(dados_falsos(), LIMIAR_CONFIANCA_PADRAO)


def contem_cpf_aproximado(texto: str) -> bool:
    """Tolerante a erro de OCR: os digitos batem, ou a linha e quase igual."""
    if DIGITOS_CPF in re.sub(r"\D", "", texto):
        return True
    melhor = max(
        (
            SequenceMatcher(None, LINHA_CPF, linha).ratio()
            for linha in texto.splitlines()
        ),
        default=0.0,
    )
    return melhor >= 0.8


def extrator_falso(caminho: str | Path) -> DocumentExtraction:
    return extract_pdf_scanned(caminho, engine=EngineFalso())


# =========================================================================== #
# Sem o binario
# =========================================================================== #


def test_tesseract_engine_satisfaz_o_protocolo() -> None:
    """Construir o motor nao exige o binario — so extract_text exige."""
    assert isinstance(TesseractEngine(), OcrEngine)
    assert isinstance(EngineFalso(), OcrEngine)


def test_charbox_de_pdf_nativo_nao_tem_confianca() -> None:
    caixa = CharBox(char="a", bbox=(0.0, 0.0, 1.0, 1.0), page=0)
    assert caixa.confidence is None
    pagina = PageExtraction(page=0, text="a", char_boxes=[caixa])
    assert pagina.low_confidence_words == []


def test_pagina_montada_tem_texto_e_invariante() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    assert pagina.text == TEXTO_FALSO
    assert len(pagina.text) == len(pagina.char_boxes)
    for indice, caixa in enumerate(pagina.char_boxes):
        assert caixa.char == pagina.text[indice]


def test_cada_caractere_carrega_a_caixa_e_a_confianca_da_palavra() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    inicio = pagina.text.index(CPF)
    for caixa in pagina.char_boxes[inicio : inicio + len(CPF)]:
        assert caixa.bbox == (260.0, 80.0, 640.0, 120.0)
        assert caixa.confidence == 88.5


def test_espaco_sintetico_entre_palavras_e_o_vao() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    espaco = pagina.char_boxes[len("CPF")]
    assert espaco.char == " "
    assert espaco.bbox == (170.0, 80.0, 190.0, 120.0)  # fim de "CPF" -> inicio de "nº"
    assert espaco.confidence is None


def test_quebra_de_linha_tem_largura_zero() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    quebra = pagina.char_boxes[pagina.text.index("\n")]
    assert quebra.char == "\n"
    assert quebra.bbox[0] == quebra.bbox[2]


def test_niveis_que_nao_sao_palavra_sao_ignorados() -> None:
    """A linha de pagina (conf -1, texto vazio) nao vira caractere."""
    pagina = montar_pagina_de_dados(dados_falsos())
    assert all(c.confidence is None or c.confidence >= 0 for c in pagina.char_boxes)


def test_palavra_abaixo_do_limiar_entra_no_texto_e_fica_registrada() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    assert "segunda" in pagina.text  # nao foi omitida
    assert len(pagina.low_confidence_words) == 1
    (palavra,) = pagina.low_confidence_words
    assert palavra == LowConfidenceWord(
        text="segunda",
        bbox=(80.0, 150.0, 240.0, 190.0),
        confidence=45.0,
        start=pagina.text.index("segunda"),
        end=pagina.text.index("segunda") + len("segunda"),
        page=0,
    )
    assert pagina.text[palavra.start : palavra.end] == palavra.text


@pytest.mark.parametrize(
    ("limiar", "esperadas"),
    [(30.0, []), (60.0, ["segunda"]), (95.0, ["nº", CPF, "segunda", "linha"])],
)
def test_limiar_de_confianca_e_configuravel(
    limiar: float, esperadas: list[str]
) -> None:
    pagina = montar_pagina_de_dados(dados_falsos(), limiar_confianca=limiar)
    assert [p.text for p in pagina.low_confidence_words] == esperadas


def test_dados_vazios_dao_pagina_vazia() -> None:
    dados: dict[str, list[Any]] = {chave: [] for chave in CHAVES}
    pagina = montar_pagina_de_dados(dados)
    assert pagina.text == ""
    assert pagina.char_boxes == []


# --------------------------------------------------------------------------- #
# bboxes_for_span com granularidade por palavra
# --------------------------------------------------------------------------- #


def test_span_parcial_dentro_da_palavra_devolve_a_palavra_inteira() -> None:
    """Metade do CPF -> a caixa e a do CPF inteiro; nao da para ser mais fino."""
    pagina = montar_pagina_de_dados(dados_falsos())
    inicio = pagina.text.index(CPF)
    (caixa,) = bboxes_for_span(pagina, inicio, inicio + 7)  # "529.982"
    assert caixa == (260.0, 80.0, 640.0, 120.0)


def test_span_sobre_duas_palavras_da_mesma_linha_e_um_retangulo() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    (caixa,) = bboxes_for_span(pagina, 0, len("CPF nº"))
    assert caixa == (80.0, 80.0, 240.0, 120.0)


def test_span_que_cruza_linhas_da_um_retangulo_por_linha() -> None:
    pagina = montar_pagina_de_dados(dados_falsos())
    inicio = pagina.text.index(CPF)
    fim = pagina.text.index("segunda") + len("segunda")
    caixas = bboxes_for_span(pagina, inicio, fim)
    assert caixas == [(260.0, 80.0, 640.0, 120.0), (80.0, 150.0, 240.0, 190.0)]


# --------------------------------------------------------------------------- #
# Imagem em branco: atalho que nao chama o motor
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cor", ["white", "black", (200, 200, 200)])
def test_imagem_de_uma_cor_so_devolve_vazio_sem_chamar_o_tesseract(
    cor: str | tuple[int, int, int],
) -> None:
    """Roda mesmo sem o binario: o motor nem tenta reconhecer uma imagem lisa."""
    pagina = TesseractEngine().extract_text(Image.new("RGB", (400, 200), cor))
    assert pagina.text == ""
    assert pagina.char_boxes == []
    assert pagina.low_confidence_words == []


# --------------------------------------------------------------------------- #
# extract_pdf_scanned com motor falso
# --------------------------------------------------------------------------- #


def test_pdf_escaneado_nao_tem_camada_de_texto(pdf_escaneado: Path) -> None:
    """O fixture e mesmo so imagem: o extrator nativo nao acha nada nele."""
    assert extract_pdf(pdf_escaneado).pages[0].text == ""


def test_extract_pdf_scanned_devolve_o_formato_nativo(pdf_escaneado: Path) -> None:
    motor = EngineFalso()
    documento = extract_pdf_scanned(pdf_escaneado, engine=motor)
    assert isinstance(documento, DocumentExtraction)
    assert motor.chamadas == 1
    assert [p.page for p in documento.pages] == [0]
    pagina = documento.pages[0]
    assert pagina.text == TEXTO_FALSO
    assert len(pagina.text) == len(pagina.char_boxes)
    assert all(c.page == 0 for c in pagina.char_boxes)


def test_caixas_do_ocr_saem_em_pontos_dentro_da_pagina(pdf_escaneado: Path) -> None:
    """Pixels da imagem viram pontos do PDF, pela razao exata pagina/pixmap."""
    documento = pymupdf.open(str(pdf_escaneado))
    try:
        rect = documento[0].rect
        pixmap = documento[0].get_pixmap(dpi=300)
        escala = rect.width / pixmap.width
    finally:
        documento.close()

    pagina = extract_pdf_scanned(pdf_escaneado, engine=EngineFalso()).pages[0]
    primeira = pagina.char_boxes[0]
    assert primeira.bbox[0] == pytest.approx(80.0 * escala)
    for caixa in pagina.char_boxes:
        assert rect.x0 <= caixa.bbox[0] <= caixa.bbox[2] <= rect.x1
        assert rect.y0 <= caixa.bbox[1] <= caixa.bbox[3] <= rect.y1
    (palavra,) = pagina.low_confidence_words
    assert palavra.page == 0
    assert palavra.bbox[0] == pytest.approx(80.0 * escala)


def test_extract_pdf_scanned_renderiza_todas_as_paginas(
    gerador: ModuleType, tmp_path: Path
) -> None:
    caminho = gerador.gerar_pdf_paginas(tmp_path / "tres.pdf", [["a"], ["b"], ["c"]])
    motor = EngineFalso()
    documento = extract_pdf_scanned(caminho, engine=motor)
    assert motor.chamadas == 3
    assert [p.page for p in documento.pages] == [0, 1, 2]


def test_pdf_em_branco_pelo_motor_padrao_nao_precisa_do_binario(
    pdf_vazio: Path,
) -> None:
    """Pagina lisa e atalhada antes do pytesseract: funciona sem Tesseract."""
    documento = extract_pdf_scanned(pdf_vazio)
    assert documento.pages[0].text == ""
    assert documento.pages[0].char_boxes == []


# --------------------------------------------------------------------------- #
# process_pdf e gerar_pdf_debug com o extrator injetado
# --------------------------------------------------------------------------- #


def test_process_pdf_com_extrator_ocr_acha_o_cpf(pdf_escaneado: Path) -> None:
    resultado = process_pdf(pdf_escaneado, DETECTORES, extrator=extrator_falso)
    cpfs = [e for e in resultado[0] if e.type is EntityType.CPF]
    assert len(cpfs) == 1
    assert cpfs[0].text == CPF
    assert cpfs[0].validated is True
    assert cpfs[0].context is not None  # "CPF nº" na mesma linha reconstruida


def test_process_pdf_com_extrator_nativo_nao_acha_nada_no_escaneado(
    pdf_escaneado: Path,
) -> None:
    """A diferenca entre os dois extratores, lado a lado."""
    assert process_pdf(pdf_escaneado, DETECTORES) == {0: []}


def test_offsets_do_ocr_batem_com_o_texto_da_pagina(pdf_escaneado: Path) -> None:
    pagina = extrator_falso(pdf_escaneado).pages[0]
    for entidade in process_pdf(pdf_escaneado, DETECTORES, extrator=extrator_falso)[0]:
        assert pagina.text[entidade.start : entidade.end] == entidade.text


def test_gerar_pdf_debug_com_extrator_ocr(pdf_escaneado: Path, tmp_path: Path) -> None:
    entidades = process_pdf(pdf_escaneado, DETECTORES, extrator=extrator_falso)
    saida = gerar_pdf_debug(
        pdf_escaneado, tmp_path / "debug.pdf", entidades, extrator=extrator_falso
    )
    documento = pymupdf.open(str(saida))
    try:
        assert len(list(documento[0].annots())) == len(entidades[0]) == 1
        assert len(documento[0].get_drawings()) >= 1
    finally:
        documento.close()


def test_gerar_pdf_debug_exige_o_mesmo_extrator(
    pdf_escaneado: Path, tmp_path: Path
) -> None:
    """Entidades do OCR com o extrator nativo: os offsets nao existem naquele texto."""
    entidades = process_pdf(pdf_escaneado, DETECTORES, extrator=extrator_falso)
    with pytest.raises(IndexError):
        gerar_pdf_debug(pdf_escaneado, tmp_path / "debug.pdf", entidades)


# =========================================================================== #
# Com o binario — pulados quando o Tesseract nao esta instalado
# =========================================================================== #


@pytest.fixture
def imagem_cpf(gerador: ModuleType) -> Image.Image:
    if gerador.localizar_fonte() is None:
        pytest.skip("nenhuma fonte TrueType conhecida para renderizar a imagem")
    return gerador.renderizar_imagem([LINHA_CPF])


@requer_tesseract
def test_ocr_le_o_cpf_de_uma_imagem_sintetica(imagem_cpf: Image.Image) -> None:
    pagina = TesseractEngine().extract_text(imagem_cpf)
    assert pagina.text.strip(), "OCR nao devolveu texto nenhum"
    assert contem_cpf_aproximado(pagina.text), pagina.text


@requer_tesseract
def test_ocr_caixas_sao_por_palavra_e_cabem_na_imagem(imagem_cpf: Image.Image) -> None:
    pagina = TesseractEngine().extract_text(imagem_cpf)
    assert len(pagina.text) == len(pagina.char_boxes)
    visiveis = [c for c in pagina.char_boxes if not c.char.isspace()]
    assert visiveis
    for caixa in visiveis:
        x0, y0, x1, y1 = caixa.bbox
        assert 0 <= x0 < x1 <= imagem_cpf.width
        assert 0 <= y0 < y1 <= imagem_cpf.height
        assert caixa.confidence is not None
    # Granularidade por palavra: bem menos caixas distintas que caracteres.
    assert len({c.bbox for c in visiveis}) < len(visiveis)


@requer_tesseract
def test_ocr_bboxes_for_span_sobre_pagina_real(imagem_cpf: Image.Image) -> None:
    pagina = TesseractEngine().extract_text(imagem_cpf)
    caixas = bboxes_for_span(pagina, 0, len(pagina.text))
    assert caixas
    assert all(c[2] > c[0] and c[3] > c[1] for c in caixas)


@requer_tesseract
def test_extract_pdf_scanned_le_pdf_sem_camada_de_texto(pdf_escaneado: Path) -> None:
    assert extract_pdf(pdf_escaneado).pages[0].text == ""
    pagina = extract_pdf_scanned(pdf_escaneado).pages[0]
    assert contem_cpf_aproximado(pagina.text), pagina.text


@requer_tesseract
def test_integracao_process_pdf_sobre_pdf_escaneado(pdf_escaneado: Path) -> None:
    """Fase 2 inteira sobre OCR: o CPF aparece, talvez com confianca menor."""
    resultado = process_pdf(pdf_escaneado, DETECTORES, extrator=extract_pdf_scanned)
    cpfs = [e for e in resultado[0] if e.type is EntityType.CPF]
    assert cpfs, "nenhum CPF encontrado no texto OCRado"
    cpf = cpfs[0]
    assert re.sub(r"\D", "", cpf.text) == DIGITOS_CPF
    assert cpf.validated is True
    assert 0 < cpf.confidence <= 1.0

    pagina = extract_pdf_scanned(pdf_escaneado).pages[0]
    assert pagina.text[cpf.start : cpf.end] == cpf.text
    assert all(
        c.confidence is not None
        for c in pagina.char_boxes[cpf.start : cpf.end]
        if not c.char.isspace()
    )


@requer_tesseract
def test_palavras_de_baixa_confianca_sao_coerentes_com_o_texto(
    imagem_cpf: Image.Image,
) -> None:
    motor = TesseractEngine()
    pagina = motor.extract_text(imagem_cpf)
    for palavra in pagina.low_confidence_words:
        assert palavra.confidence < motor.limiar_confianca
        assert pagina.text[palavra.start : palavra.end] == palavra.text
