"""Testes da redação real de PDF: conteúdo removido, não desenhado por cima.

A prova de que uma entidade foi tarjada de verdade é o TEXTO EXTRAÍDO do
resultado não conter mais o dado — nunca a aparência visual. Por isso todo
teste aqui roda ``extract_pdf`` de novo no arquivo de SAÍDA, o mesmo caminho
que a Fase 2 já usa para o de entrada.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType

import pymupdf
import pytest

from redator.detectors import TODOS_DETECTORES
from redator.entities import EntityType
from redator.pdf import bboxes_for_span, extract_pdf, process_pdf
from redator.perfil import EntidadeComAcao, aplicar_perfil
from redator.pipeline import detect_all
from redator.redacao import RelatorioRedacao, redigir_pdf

DETECTORES = list(TODOS_DETECTORES)


def _entidades_por_pagina(caminho: Path) -> dict[int, list[EntidadeComAcao]]:
    return {
        pagina: aplicar_perfil(entidades)
        for pagina, entidades in process_pdf(caminho, DETECTORES).items()
    }


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# o conteudo tarjado some de verdade; o publicado permanece
# --------------------------------------------------------------------------- #


def test_cpf_tarjado_some_do_texto_extraido(pdf_documentos: Path, tmp_path: Path):
    entidades = _entidades_por_pagina(pdf_documentos)

    redigir_pdf(pdf_documentos, tmp_path / "redigido.pdf", entidades)

    texto_saida = extract_pdf(tmp_path / "redigido.pdf").pages[0].text
    assert "529.982.247-25" not in texto_saida


def test_cnpj_publicado_continua_no_texto_extraido(
    pdf_documentos: Path, tmp_path: Path
):
    """CNPJ e PUBLICAR no PERFIL_PADRAO — a redação nao pode tocar nele."""
    entidades = _entidades_por_pagina(pdf_documentos)

    redigir_pdf(pdf_documentos, tmp_path / "redigido.pdf", entidades)

    texto_saida = extract_pdf(tmp_path / "redigido.pdf").pages[0].text
    assert "46.634.044/0001-74" in texto_saida


# --------------------------------------------------------------------------- #
# a entrada nunca e alterada
# --------------------------------------------------------------------------- #


def test_entrada_nao_e_alterada(pdf_documentos: Path, tmp_path: Path):
    hash_antes = _sha256(pdf_documentos)

    redigir_pdf(
        pdf_documentos, tmp_path / "redigido.pdf", _entidades_por_pagina(pdf_documentos)
    )

    assert _sha256(pdf_documentos) == hash_antes


def test_saida_igual_a_entrada_e_erro(pdf_documentos: Path) -> None:
    with pytest.raises(ValueError, match="in-place"):
        redigir_pdf(pdf_documentos, pdf_documentos, {0: []})


def test_saida_igual_a_entrada_nao_toca_em_nada_antes_de_levantar(
    pdf_documentos: Path,
) -> None:
    """A checagem de path e a primeira coisa: nem o arquivo de entrada é lido."""
    hash_antes = _sha256(pdf_documentos)
    with pytest.raises(ValueError):
        redigir_pdf(pdf_documentos, pdf_documentos, {0: []})
    assert _sha256(pdf_documentos) == hash_antes


# --------------------------------------------------------------------------- #
# multiplas paginas: redacao de uma nao afeta o texto das outras
# --------------------------------------------------------------------------- #


def test_redacao_em_uma_pagina_nao_afeta_o_texto_das_outras(
    gerador: ModuleType, tmp_path: Path
) -> None:
    caminho = gerador.gerar_pdf_paginas(
        tmp_path / "duas.pdf",
        [
            ["CPF nº 529.982.247-25"],
            ["CPF nº 111.444.777-35"],
        ],
    )
    entidades = _entidades_por_pagina(caminho)
    assert set(entidades) == {0, 1}

    redigir_pdf(caminho, tmp_path / "redigido.pdf", entidades)

    paginas_saida = extract_pdf(tmp_path / "redigido.pdf").pages
    assert "529.982.247-25" not in paginas_saida[0].text
    assert "111.444.777-35" not in paginas_saida[1].text
    # nenhuma pagina vazou o CPF da outra
    assert "111.444.777-35" not in paginas_saida[0].text
    assert "529.982.247-25" not in paginas_saida[1].text


# --------------------------------------------------------------------------- #
# RelatorioRedacao
# --------------------------------------------------------------------------- #


def test_relatorio_contagens_e_hashes(pdf_documentos: Path, tmp_path: Path) -> None:
    entidades = _entidades_por_pagina(pdf_documentos)
    total_tarjadas = sum(
        1 for lista in entidades.values() for e in lista if e.acao.value == "tarjar"
    )
    total_publicadas = sum(
        1 for lista in entidades.values() for e in lista if e.acao.value == "publicar"
    )

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(pdf_documentos, saida, entidades)

    assert isinstance(relatorio, RelatorioRedacao)
    assert relatorio.total_entidades_tarjadas == total_tarjadas
    assert relatorio.total_entidades_publicadas == total_publicadas
    assert relatorio.paginas_processadas == len(entidades)
    assert relatorio.hash_original == _sha256(pdf_documentos)
    assert relatorio.hash_resultado == _sha256(saida)
    # e o hash do resultado nao pode ser o do original: algo mudou de fato
    assert relatorio.hash_resultado != relatorio.hash_original


def test_relatorio_sem_nenhuma_entidade_tarjada(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """So PUBLICAR na pagina: total_entidades_tarjadas e zero, nada some."""
    caminho = gerador.gerar_pdf(
        tmp_path / "so_cnpj.pdf", ["CNPJ: 46.634.044/0001-74"]
    )
    entidades = _entidades_por_pagina(caminho)

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, entidades)

    assert relatorio.total_entidades_tarjadas == 0
    assert relatorio.total_entidades_publicadas >= 1
    assert "46.634.044/0001-74" in extract_pdf(saida).pages[0].text


# --------------------------------------------------------------------------- #
# desenho, imagem de fundo e link sob a area redigida
#
# Estes tres testes nao olham so o texto extraido: abrem o PDF de saida com
# PyMuPDF e inspecionam desenhos, pixels e anotacoes diretamente, porque a
# pergunta aqui e sobre o que apply_redactions faz com conteudo que NAO e
# texto — e isso e configuravel (parametros images/graphics), com um default
# que nao e o mais seguro para forma vetorial. Ver o docstring do modulo
# para o porque de cada parametro escolhido.
# --------------------------------------------------------------------------- #


def _cpf_e_bbox(caminho: Path) -> tuple[EntidadeComAcao, tuple[float, float, float, float]]:
    """A entidade CPF (com sua acao) e o bbox exato do texto, via deteccao real."""
    pagina = extract_pdf(caminho).pages[0]
    (cpf,) = [
        e for e in detect_all(pagina.text, DETECTORES) if e.type is EntityType.CPF
    ]
    (bbox,) = bboxes_for_span(pagina, cpf.start, cpf.end)
    (entidade_com_acao,) = aplicar_perfil([cpf])
    return entidade_com_acao, bbox


def test_forma_desenhada_sob_a_entidade_e_removida(tmp_path: Path) -> None:
    """Um retangulo (nao texto) exatamente sob o CPF some do resultado.

    Simula uma tarja grafica pre-existente, ou qualquer elemento decorativo
    desenhado nas mesmas coordenadas do texto detectado. Achado ao investigar
    este caso: com o default de ``apply_redactions`` (``graphics=
    REMOVE_IF_COVERED``), uma forma cujas bordas coincidem EXATAMENTE com a
    area de redacao sobrevive — por isso o modulo usa
    ``REMOVE_IF_TOUCHED`` explicitamente. Este teste teria falhado antes
    dessa escolha.
    """
    caminho = tmp_path / "forma.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 100), "CPF nº 529.982.247-25", fontname="helv", fontsize=11)
    documento.save(caminho)
    documento.close()

    entidade_com_acao, bbox = _cpf_e_bbox(caminho)

    # desenha o retangulo vermelho DEPOIS de saber o bbox exato do texto —
    # nas mesmas coordenadas, como uma tarja ou elemento grafico preexistente.
    documento = pymupdf.open(caminho)
    documento[0].draw_rect(pymupdf.Rect(*bbox), color=(1, 0, 0), fill=(1, 0, 0))
    documento.saveIncr()
    documento.close()

    saida = tmp_path / "redigido.pdf"
    redigir_pdf(caminho, saida, {0: [entidade_com_acao]})

    documento_saida = pymupdf.open(saida)
    try:
        vermelhos = [
            d for d in documento_saida[0].get_drawings() if d.get("fill") == (1.0, 0.0, 0.0)
        ]
    finally:
        documento_saida.close()
    assert vermelhos == []


def test_imagem_de_fundo_so_perde_os_pixels_sob_a_entidade(tmp_path: Path) -> None:
    """Uma imagem grande de fundo (ex.: pagina escaneada) nao some inteira.

    O default de ``apply_redactions`` para imagem e ``PDF_REDACT_IMAGE_
    PIXELS``: apaga so os pixels sob a area marcada, nao a imagem inteira.
    E o comportamento certo para um carimbo/texto pequeno sobre uma imagem
    grande — ``PDF_REDACT_IMAGE_REMOVE`` faria a pagina toda desaparecer.
    """
    caminho = tmp_path / "imagem.pdf"
    imagem_branca = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 400), False)
    imagem_branca.set_rect(imagem_branca.irect, (255, 255, 255))

    documento = pymupdf.open()
    pagina = documento.new_page(width=400, height=400)
    pagina.insert_image(pymupdf.Rect(0, 0, 400, 400), pixmap=imagem_branca)
    pagina.insert_text((20, 30), "CPF nº 529.982.247-25", fontname="helv", fontsize=11)
    documento.save(caminho)
    documento.close()

    entidade_com_acao, bbox = _cpf_e_bbox(caminho)

    saida = tmp_path / "redigido.pdf"
    redigir_pdf(caminho, saida, {0: [entidade_com_acao]})

    documento_saida = pymupdf.open(saida)
    try:
        pagina_saida = documento_saida[0]
        assert len(pagina_saida.get_images()) == 1, "a imagem inteira nao pode sumir"
        pix = pagina_saida.get_pixmap()
        # dentro da area do CPF: preenchido de preto pela redacao.
        x0, y0, x1, y1 = bbox
        assert pix.pixel(int((x0 + x1) / 2), int((y0 + y1) / 2)) == (0, 0, 0)
        # bem longe da entidade, na mesma imagem: continua branco.
        assert pix.pixel(380, 380) == (255, 255, 255)
    finally:
        documento_saida.close()


def test_link_colidindo_com_a_redacao_nao_sobrevive(tmp_path: Path) -> None:
    """Um link (ex.: QR/URL de verificacao) sob a area redigida some junto.

    Nao e o tratamento completo de QR code (ler a imagem, decidir se o
    proprio codigo precisa ser coberto) — isso fica para tarefa futura. Aqui
    so confirma que uma anotacao de link cuja area colide com uma redacao
    nao sobrevive: ela deixa de apontar para qualquer lugar.
    """
    caminho = tmp_path / "link.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 100), "CPF nº 529.982.247-25", fontname="helv", fontsize=11)
    documento.save(caminho)
    documento.close()

    entidade_com_acao, bbox = _cpf_e_bbox(caminho)

    documento = pymupdf.open(caminho)
    documento[0].insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(*bbox),
            "uri": "https://exemplo.invalido/verificar",
        }
    )
    documento.saveIncr()
    documento.close()

    # confirma que o link existe de fato na entrada, antes de redigir
    entrada_com_link = pymupdf.open(caminho)
    try:
        assert entrada_com_link[0].get_links(), "o link nao foi gravado na entrada"
    finally:
        entrada_com_link.close()

    saida = tmp_path / "redigido.pdf"
    redigir_pdf(caminho, saida, {0: [entidade_com_acao]})

    documento_saida = pymupdf.open(saida)
    try:
        assert documento_saida[0].get_links() == []
    finally:
        documento_saida.close()
