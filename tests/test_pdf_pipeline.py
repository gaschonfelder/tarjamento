"""Testes do pipeline PDF -> entidades por página, e do PDF de debug."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pymupdf
import pytest

from redator.detectors import TODOS_DETECTORES
from redator.entities import Entity, EntityType
from redator.pdf import bboxes_for_span, extract_pdf, gerar_pdf_debug, process_pdf

DETECTORES = list(TODOS_DETECTORES)


def por_tipo(entidades: list[Entity], tipo: EntityType) -> list[Entity]:
    return sorted((e for e in entidades if e.type is tipo), key=lambda e: e.start)


def contagens(caminho: Path, numero: int = 0) -> tuple[int, int]:
    """(desenhos, anotacoes) de uma pagina — a medida estrutural do debug."""
    documento = pymupdf.open(str(caminho))
    try:
        pagina = documento[numero]
        return len(pagina.get_drawings()), len(list(pagina.annots()))
    finally:
        documento.close()


# --------------------------------------------------------------------------- #
# process_pdf
# --------------------------------------------------------------------------- #


def test_cpf_rotulado_aparece_na_pagina_certa(pdf_documentos: Path) -> None:
    resultado = process_pdf(pdf_documentos, DETECTORES)
    assert set(resultado) == {0}

    cpfs = por_tipo(resultado[0], EntityType.CPF)
    assert len(cpfs) == 1
    cpf = cpfs[0]
    assert cpf.text == "529.982.247-25"
    assert cpf.validated is True
    assert cpf.confidence == 0.99
    assert cpf.context is not None


def test_offsets_sao_do_texto_da_pagina(pdf_documentos: Path) -> None:
    """O span da entidade recorta exatamente o texto que extract_pdf devolveu."""
    pagina = extract_pdf(pdf_documentos).pages[0]
    for entidade in process_pdf(pdf_documentos, DETECTORES)[0]:
        assert pagina.text[entidade.start : entidade.end] == entidade.text


def test_gerador_base14_nao_preserva_caractere_fora_de_latin1(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """Limitacao do PDF sintetico, fixada para ninguem contar com ela.

    A Helvetica base-14 do gerador so codifica Latin-1: um traco tipografico
    (U+2013) inserido no PDF volta da extracao como U+00B7, ponto medio — e o
    mesmo acontece com em dash, hifen nao-quebravel, espaco fino e ligadura.
    Consequencia: PDF gerado aqui NAO exercita a normalizacao Unicode do
    pipeline. A propriedade "offsets do original, nao do normalizado" esta
    coberta no caminho de texto, em test_pipeline.py; para cobri-la em PDF e
    preciso PDF real, com fonte embutida.
    """
    caminho = gerador.gerar_pdf(tmp_path / "traco.pdf", ["CPF nº 529.982.247–25"])
    texto = extract_pdf(caminho).pages[0].text
    assert "–" not in texto
    assert "·" in texto
    # Com o ponto medio no lugar do traco, o CPF nem chega a ser candidato.
    assert por_tipo(process_pdf(caminho, DETECTORES)[0], EntityType.CPF) == []


def test_todos_os_tipos_da_pagina_saem_ancorados(pdf_documentos: Path) -> None:
    entidades = process_pdf(pdf_documentos, DETECTORES)[0]
    tipos = {e.type for e in entidades}
    assert {EntityType.CPF, EntityType.CNPJ, EntityType.TELEFONE} <= tipos
    assert all(e.context is not None for e in entidades)


@pytest.mark.parametrize("nome", ["pdf_vazio", "pdf_so_imagem"])
def test_pagina_sem_texto_aparece_com_lista_vazia(
    nome: str, request: pytest.FixtureRequest
) -> None:
    caminho: Path = request.getfixturevalue(nome)
    assert process_pdf(caminho, DETECTORES) == {0: []}


def test_sem_detectores_toda_pagina_fica_vazia(pdf_documentos: Path) -> None:
    assert process_pdf(pdf_documentos, []) == {0: []}


def test_entidade_na_segunda_pagina(gerador: ModuleType, tmp_path: Path) -> None:
    """Pagina certa, e offsets relativos ao texto DAQUELA pagina."""
    caminho = gerador.gerar_pdf_paginas(
        tmp_path / "duas.pdf",
        [["Sem dado pessoal nesta pagina."], ["CPF nº 529.982.247-25"]],
    )
    resultado = process_pdf(caminho, DETECTORES)
    assert set(resultado) == {0, 1}
    assert resultado[0] == []

    (cpf,) = por_tipo(resultado[1], EntityType.CPF)
    segunda = extract_pdf(caminho).pages[1]
    assert segunda.text[cpf.start : cpf.end] == cpf.text


def test_pagina_em_branco_no_meio_nao_desloca_as_demais(
    gerador: ModuleType, tmp_path: Path
) -> None:
    caminho = gerador.gerar_pdf_paginas(
        tmp_path / "tres.pdf",
        [["CPF nº 529.982.247-25"], [], ["CPF nº 111.444.777-35"]],
    )
    resultado = process_pdf(caminho, DETECTORES)
    assert set(resultado) == {0, 1, 2}
    assert [e.text for e in por_tipo(resultado[0], EntityType.CPF)] == [
        "529.982.247-25"
    ]
    assert resultado[1] == []
    assert [e.text for e in por_tipo(resultado[2], EntityType.CPF)] == [
        "111.444.777-35"
    ]


# --------------------------------------------------------------------------- #
# Tabela reconstruida, formalizando o que foi visto no relatorio
# --------------------------------------------------------------------------- #


def test_tabela_posicionada_acha_os_cpfs(pdf_tabela_posicionada: Path) -> None:
    cpfs = por_tipo(process_pdf(pdf_tabela_posicionada, DETECTORES)[0], EntityType.CPF)
    assert [e.text for e in cpfs] == ["529.982.247-25", "111.444.777-35"]
    assert all(e.validated for e in cpfs)


def test_formulario_posicionado_acha_cpf_e_cep_ancorados(
    pdf_formulario_posicionado: Path,
) -> None:
    entidades = process_pdf(pdf_formulario_posicionado, DETECTORES)[0]
    (cpf,) = por_tipo(entidades, EntityType.CPF)
    (cep,) = por_tipo(entidades, EntityType.CEP)
    for entidade in (cpf, cep):
        assert entidade.context is not None
        assert entidade.confidence == 0.99


# --------------------------------------------------------------------------- #
# gerar_pdf_debug
# --------------------------------------------------------------------------- #


@pytest.fixture
def debug_documentos(
    pdf_documentos: Path, tmp_path: Path
) -> tuple[Path, Path, dict[int, list[Entity]]]:
    entidades = process_pdf(pdf_documentos, DETECTORES)
    saida = gerar_pdf_debug(pdf_documentos, tmp_path / "debug.pdf", entidades)
    return pdf_documentos, saida, entidades


def test_debug_e_arquivo_novo_que_abre(
    debug_documentos: tuple[Path, Path, dict[int, list[Entity]]],
) -> None:
    original, saida, _ = debug_documentos
    assert saida.exists()
    assert saida.resolve() != original.resolve()
    documento = pymupdf.open(str(saida))
    try:
        assert documento.page_count == 1
    finally:
        documento.close()


def test_debug_tem_mais_desenhos_e_anotacoes_que_o_original(
    debug_documentos: tuple[Path, Path, dict[int, list[Entity]]],
) -> None:
    original, saida, entidades = debug_documentos
    desenhos_antes, anotacoes_antes = contagens(original)
    desenhos_depois, anotacoes_depois = contagens(saida)

    assert desenhos_depois > desenhos_antes
    assert anotacoes_depois > anotacoes_antes
    # Uma anotacao por entidade; ao menos um retangulo por entidade.
    assert anotacoes_depois - anotacoes_antes == len(entidades[0])
    assert desenhos_depois - desenhos_antes >= len(entidades[0])


def test_debug_desenha_o_retangulo_sobre_a_caixa_da_entidade(
    debug_documentos: tuple[Path, Path, dict[int, list[Entity]]],
) -> None:
    original, saida, entidades = debug_documentos
    pagina = extract_pdf(original).pages[0]
    (cpf,) = por_tipo(entidades[0], EntityType.CPF)
    (alvo,) = bboxes_for_span(pagina, cpf.start, cpf.end)

    documento = pymupdf.open(str(saida))
    try:
        rects = [desenho["rect"] for desenho in documento[0].get_drawings()]
    finally:
        documento.close()
    assert any(
        abs(r.x0 - alvo[0]) < 1
        and abs(r.y0 - alvo[1]) < 1
        and abs(r.x1 - alvo[2]) < 1
        and abs(r.y1 - alvo[3]) < 1
        for r in rects
    ), (alvo, rects)


def test_anotacao_carrega_tipo_e_confianca(
    debug_documentos: tuple[Path, Path, dict[int, list[Entity]]],
) -> None:
    _, saida, _ = debug_documentos
    documento = pymupdf.open(str(saida))
    try:
        conteudos = [anotacao.info["content"] for anotacao in documento[0].annots()]
    finally:
        documento.close()
    assert any(c.startswith("CPF") and "0.99" in c for c in conteudos), conteudos
    assert any(c.startswith("CNPJ") for c in conteudos)


def test_debug_nao_altera_o_original(pdf_documentos: Path, tmp_path: Path) -> None:
    antes = pdf_documentos.read_bytes()
    gerar_pdf_debug(
        pdf_documentos, tmp_path / "d.pdf", process_pdf(pdf_documentos, DETECTORES)
    )
    assert pdf_documentos.read_bytes() == antes


def test_debug_recusa_sobrescrever_a_entrada(pdf_documentos: Path) -> None:
    with pytest.raises(ValueError, match="nunca sobrescreve"):
        gerar_pdf_debug(pdf_documentos, pdf_documentos, {0: []})


def test_debug_pagina_inexistente_e_erro(pdf_documentos: Path, tmp_path: Path) -> None:
    with pytest.raises(IndexError):
        gerar_pdf_debug(pdf_documentos, tmp_path / "d.pdf", {7: []})


def test_debug_sem_entidades_e_copia_sem_marcas(
    pdf_documentos: Path, tmp_path: Path
) -> None:
    saida = gerar_pdf_debug(pdf_documentos, tmp_path / "limpo.pdf", {0: []})
    assert contagens(saida) == contagens(pdf_documentos)


def test_entidade_em_duas_linhas_rende_dois_retangulos_e_uma_anotacao(
    pdf_quebrado: Path, tmp_path: Path
) -> None:
    """O CPF partido nao e detectado na Fase 1; a entidade e montada a mao
    so para exercitar o caminho de varios retangulos do debug."""
    pagina = extract_pdf(pdf_quebrado).pages[0]
    alvo = "529.982.\n247-25"
    inicio = pagina.text.index(alvo)
    entidade = Entity(
        type=EntityType.CPF,
        start=inicio,
        end=inicio + len(alvo),
        text=alvo,
        confidence=0.5,
        detector="teste",
    )
    saida = gerar_pdf_debug(pdf_quebrado, tmp_path / "q.pdf", {0: [entidade]})
    desenhos, anotacoes = contagens(saida)
    desenhos_antes, anotacoes_antes = contagens(pdf_quebrado)
    assert desenhos - desenhos_antes == 2
    assert anotacoes - anotacoes_antes == 1


def test_debug_em_pdf_multipagina_marca_so_a_pagina_da_entidade(
    gerador: ModuleType, tmp_path: Path
) -> None:
    caminho = gerador.gerar_pdf_paginas(
        tmp_path / "duas.pdf",
        [["Sem dado pessoal nesta pagina."], ["CPF nº 529.982.247-25"]],
    )
    saida = gerar_pdf_debug(
        caminho, tmp_path / "d.pdf", process_pdf(caminho, DETECTORES)
    )
    assert contagens(saida, 0) == contagens(caminho, 0)
    assert contagens(saida, 1)[1] == 1
