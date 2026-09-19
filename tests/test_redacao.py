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
from redator.entities import Entity, EntityType
from redator.pdf import bboxes_for_entity, bboxes_for_span, extract_pdf, process_pdf
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


def _pdf_com_cpf(caminho: Path) -> Path:
    """Um PDF minimo com um CPF, para ter ao menos uma entidade TARJAR."""
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 100), "CPF nº 529.982.247-25", fontname="helv", fontsize=11)
    documento.save(caminho)
    documento.close()
    return caminho


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
# tarja parcial de CPF (padrao DOU) — so em origem nativa
# --------------------------------------------------------------------------- #


def _cpf_e_entidades(caminho: Path) -> tuple[Entity, dict[int, list[EntidadeComAcao]]]:
    pagina = extract_pdf(caminho).pages[0]
    (cpf,) = [e for e in detect_all(pagina.text, DETECTORES) if e.type is EntityType.CPF]
    return cpf, _entidades_por_pagina(caminho)


def test_cpf_nativo_mantem_os_6_digitos_do_meio_e_a_pontuacao(tmp_path: Path) -> None:
    caminho = _pdf_com_cpf(tmp_path / "cpf.pdf")

    redigir_pdf(caminho, tmp_path / "redigido.pdf", _entidades_por_pagina(caminho))

    texto_saida = extract_pdf(tmp_path / "redigido.pdf").pages[0].text
    assert ".982.247-" in texto_saida


def test_cpf_nativo_remove_as_pontas(tmp_path: Path) -> None:
    caminho = _pdf_com_cpf(tmp_path / "cpf.pdf")

    redigir_pdf(caminho, tmp_path / "redigido.pdf", _entidades_por_pagina(caminho))

    texto_saida = extract_pdf(tmp_path / "redigido.pdf").pages[0].text
    assert "529" not in texto_saida
    assert "-25" not in texto_saida


def test_cpf_nativo_nao_reconstroi_por_justaposicao(tmp_path: Path) -> None:
    """Nem juntando todo digito que sobrou na pagina da para montar de volta

    os 11 originais — 5 foram removidos do CONTEUDO, nao so escondidos
    visualmente. Se a redacao coisesse algo errado (ex.: so cobrisse com
    preto sem apagar o texto), os digitos ainda estariam todos ali, na
    ordem certa, e este teste pegaria isso.
    """
    caminho = _pdf_com_cpf(tmp_path / "cpf.pdf")

    redigir_pdf(caminho, tmp_path / "redigido.pdf", _entidades_por_pagina(caminho))

    texto_saida = extract_pdf(tmp_path / "redigido.pdf").pages[0].text
    digitos_restantes = "".join(c for c in texto_saida if c.isdigit())
    assert "52998224725" not in digitos_restantes


def test_cpf_nativo_gera_5_redact_annots_nao_1(tmp_path: Path) -> None:
    """Prova estrutural: uma caixa por digito oculto, nao uma cobrindo tudo."""
    caminho = _pdf_com_cpf(tmp_path / "cpf.pdf")
    cpf, _ = _cpf_e_entidades(caminho)
    pagina = extract_pdf(caminho).pages[0]

    assert len(bboxes_for_entity(pagina, cpf)) == 5


def test_relatorio_conta_cpf_parcial_normalmente_como_tarjada(tmp_path: Path) -> None:
    caminho = _pdf_com_cpf(tmp_path / "cpf.pdf")

    relatorio = redigir_pdf(
        caminho, tmp_path / "redigido.pdf", _entidades_por_pagina(caminho)
    )

    assert relatorio.total_entidades_tarjadas == 1
    assert relatorio.verificacao.aprovado is True


def test_cpf_parcial_aprovado_na_verificacao_pos_redacao(tmp_path: Path) -> None:
    """O que sobra (6 digitos soltos + pontuacao) nao fecha DV de CPF novo,

    entao a re-deteccao na verificacao nao acha nada ali — ausencia de match
    e sucesso, nao "nao achei o CPF original, deve ter sumido, ok" por
    engano: aqui o CPF original de verdade sumiu, de proposito.
    """
    caminho = _pdf_com_cpf(tmp_path / "cpf.pdf")
    entidades = _entidades_por_pagina(caminho)

    relatorio = redigir_pdf(caminho, tmp_path / "redigido.pdf", entidades)

    assert relatorio.verificacao.aprovado is True
    assert relatorio.verificacao.vazamentos == []


# --------------------------------------------------------------------------- #
# CPF_MASCARADO: nunca recebe redacao automatica
# --------------------------------------------------------------------------- #


def test_cpf_mascarado_nao_e_tocado(gerador: ModuleType, tmp_path: Path) -> None:
    caminho = gerador.gerar_pdf(tmp_path / "mascarado.pdf", ["CPF: ***.982.247-**"])
    entidades = _entidades_por_pagina(caminho)
    (item,) = entidades[0]
    assert item.entity.type is EntityType.CPF_MASCARADO
    assert item.acao.value == "tarjar"  # PERFIL_PADRAO nao muda

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, entidades)

    assert relatorio.total_entidades_tarjadas == 0
    assert relatorio.total_entidades_publicadas == 0
    assert relatorio.total_cpf_mascarado_sinalizados == 1
    assert "982.247" in extract_pdf(saida).pages[0].text


def test_cpf_mascarado_intocado_e_aprovado_na_verificacao(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """redator.redacao nunca desenha nada sobre CPF_MASCARADO — a verificacao

    tem de concordar que isso e sucesso, nao vazamento (ver docstring de
    ambos os modulos: cobrar a ausencia de algo que nunca deveria sumir
    reprovaria todo documento com um CPF ja mascarado).
    """
    caminho = gerador.gerar_pdf(tmp_path / "mascarado.pdf", ["CPF: ***.982.247-**"])
    entidades = _entidades_por_pagina(caminho)

    relatorio = redigir_pdf(caminho, tmp_path / "redigido.pdf", entidades)

    assert relatorio.verificacao.aprovado is True
    assert relatorio.verificacao.vazamentos == []


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

    Amostra o pixel dentro da PRIMEIRA caixa parcial (um dos 3 primeiros
    digitos, ocultos no padrao DOU) — nao o centro do span inteiro do CPF,
    que agora cai bem no meio visivel (preservado) e ficaria branco.
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

    pagina_extraida = extract_pdf(caminho).pages[0]
    (cpf,) = [e for e in detect_all(pagina_extraida.text, DETECTORES) if e.type is EntityType.CPF]
    (entidade_com_acao,) = aplicar_perfil([cpf])
    x0, y0, x1, y1 = bboxes_for_entity(pagina_extraida, cpf)[0]

    saida = tmp_path / "redigido.pdf"
    redigir_pdf(caminho, saida, {0: [entidade_com_acao]})

    documento_saida = pymupdf.open(saida)
    try:
        pagina_saida = documento_saida[0]
        assert len(pagina_saida.get_images()) == 1, "a imagem inteira nao pode sumir"
        pix = pagina_saida.get_pixmap()
        # dentro da caixa do digito oculto: preenchido de preto pela redacao.
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


# --------------------------------------------------------------------------- #
# limpeza de metadados, AcroForm, anexos e JavaScript
#
# Incondicional: acontece em toda chamada a redigir_pdf, nao e parametro.
# Cada teste monta um PDF a mao com pymupdf (o gerador de fixtures nao cobre
# metadado/AcroForm/anexo), roda redigir_pdf com uma unica entidade TARJAR
# qualquer (a limpeza de documento nao depende de haver entidade nenhuma),
# e confirma no arquivo de SAIDA, nao so no relatorio. ``_pdf_com_cpf`` esta
# definida no topo do arquivo — reaproveitada tambem pelos testes de tarja
# parcial, logo depois do bloco introdutorio.
# --------------------------------------------------------------------------- #


def test_nada_extra_para_remover_relatorio_fica_todo_falso_ou_zero(
    pdf_documentos: Path, tmp_path: Path
) -> None:
    """Baseline: PDF sem metadado customizado, sem AcroForm, sem anexo, sem JS."""
    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(pdf_documentos, saida, _entidades_por_pagina(pdf_documentos))

    assert relatorio.metadados_removidos is False
    assert relatorio.acroform_removido is False
    assert relatorio.anexos_removidos == 0
    assert relatorio.javascript_removido is False


def test_metadados_customizados_de_info_somem(tmp_path: Path) -> None:
    """Campo customizado em /Info, fora do que set_metadata sabe nomear, some."""
    caminho = tmp_path / "metadados.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.set_metadata(
        {"author": "Fulano de Tal", "title": "Oficio com CPF 529.982.247-25"}
    )
    _, temp = documento.xref_get_key(-1, "Info")
    info_xref = int(temp.replace("0 R", ""))
    documento.xref_set_key(info_xref, "CampoCustomizado", "(529.982.247-25)")
    documento.save(caminho)
    documento.close()

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, {0: []})

    assert relatorio.metadados_removidos is True
    documento_saida = pymupdf.open(saida)
    try:
        metadata = documento_saida.metadata
        assert not metadata["author"]
        assert not metadata["title"]
    finally:
        documento_saida.close()
    bruto = saida.read_bytes()
    assert b"CampoCustomizado" not in bruto
    assert b"Fulano de Tal" not in bruto
    assert b"529.982.247-25" not in bruto


def test_xmp_e_removido(tmp_path: Path) -> None:
    caminho = tmp_path / "xmp.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.set_xml_metadata(
        "<?xpacket begin='' id=''?>"
        "<x:xmpmeta xmlns:x='adobe:ns:meta/'>"
        "<rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>"
        "<rdf:Description dc:creator='Fulano 529.982.247-25' "
        "xmlns:dc='http://purl.org/dc/elements/1.1/'/>"
        "</rdf:RDF></x:xmpmeta>"
    )
    documento.save(caminho)
    documento.close()

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, {0: []})

    assert relatorio.metadados_removidos is True
    documento_saida = pymupdf.open(saida)
    try:
        assert documento_saida.get_xml_metadata() == ""
    finally:
        documento_saida.close()
    assert b"529.982.247-25" not in saida.read_bytes()


def test_acroform_e_todo_widget_sao_removidos(tmp_path: Path) -> None:
    """Nao redige o campo — remove o AcroForm inteiro, widget incluso."""
    caminho = tmp_path / "form.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "nome_signatario"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
    widget.field_value = "Fulano de Tal 529.982.247-25"
    widget.rect = pymupdf.Rect(50, 50, 200, 70)
    pagina.add_widget(widget)
    documento.save(caminho)
    documento.close()

    entrada_com_form = pymupdf.open(caminho)
    try:
        assert entrada_com_form.is_form_pdf
    finally:
        entrada_com_form.close()

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, {0: []})

    assert relatorio.acroform_removido is True
    documento_saida = pymupdf.open(saida)
    try:
        assert documento_saida.is_form_pdf is False
        assert list(documento_saida[0].widgets()) == []
        # a chave fica com valor "null" (equivalente a ausente no PDF), nao
        # apagada do dicionario — mesma convencao usada em scrub() do PyMuPDF
        # para /Thumb; e o que faz is_form_pdf ja dar False acima.
        tipo, _ = documento_saida.xref_get_key(documento_saida.pdf_catalog(), "AcroForm")
        assert tipo == "null"
    finally:
        documento_saida.close()
    bruto = saida.read_bytes()
    assert b"nome_signatario" not in bruto
    assert b"529.982.247-25" not in bruto


def test_anexo_embutido_e_removido(tmp_path: Path) -> None:
    caminho = tmp_path / "anexo.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.embfile_add(
        "certidao.txt", b"CPF do anexo: 529.982.247-25", desc="anexo sensivel"
    )
    documento.save(caminho)
    documento.close()

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, {0: []})

    assert relatorio.anexos_removidos == 1
    documento_saida = pymupdf.open(saida)
    try:
        assert documento_saida.embfile_count() == 0
    finally:
        documento_saida.close()
    assert b"529.982.247-25" not in saida.read_bytes()


def test_javascript_e_neutralizado(tmp_path: Path) -> None:
    caminho = tmp_path / "js.pdf"
    documento = pymupdf.open()
    documento.new_page()
    js_xref = documento.get_new_xref()
    documento.update_object(
        js_xref, '<</S/JavaScript/JS(app.alert("529.982.247-25"))>>'
    )
    nomes_xref = documento.get_new_xref()
    documento.update_object(nomes_xref, f"<</Names[(Acao) {js_xref} 0 R]>>")
    catalogo = documento.pdf_catalog()
    documento.xref_set_key(catalogo, "Names", f"<</JavaScript {nomes_xref} 0 R>>")
    documento.xref_set_key(catalogo, "OpenAction", f"{js_xref} 0 R")
    documento.save(caminho)
    documento.close()

    saida = tmp_path / "redigido.pdf"
    relatorio = redigir_pdf(caminho, saida, {0: []})

    assert relatorio.javascript_removido is True
    bruto = saida.read_bytes()
    assert b"app.alert" not in bruto
    assert b"529.982.247-25" not in bruto


def test_limpeza_de_documento_nao_atrapalha_a_redacao_de_conteudo(
    tmp_path: Path,
) -> None:
    """Metadado, AcroForm, anexo e JS juntos — o CPF do texto ainda some."""
    caminho = tmp_path / "tudo.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 100), "CPF nº 529.982.247-25", fontname="helv", fontsize=11)
    documento.set_metadata({"author": "Fulano de Tal"})
    documento.embfile_add("anexo.txt", b"nada de especial")
    widget = pymupdf.Widget()
    widget.field_name = "campo"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
    widget.field_value = "valor"
    widget.rect = pymupdf.Rect(300, 300, 400, 320)
    pagina.add_widget(widget)
    documento.save(caminho)
    documento.close()

    saida = tmp_path / "redigido.pdf"
    entidades = _entidades_por_pagina(caminho)
    relatorio = redigir_pdf(caminho, saida, entidades)

    assert relatorio.total_entidades_tarjadas >= 1
    assert relatorio.metadados_removidos is True
    assert relatorio.acroform_removido is True
    assert relatorio.anexos_removidos == 1
    assert "529.982.247-25" not in extract_pdf(saida).pages[0].text
