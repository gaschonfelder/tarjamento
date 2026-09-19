"""Testes da verificação pós-redação.

Um verificador que só é testado com redação correta não prova nada — ele
passaria também se não verificasse coisa alguma. Por isso cada canal tem ao
menos um teste em que o vazamento EXISTE e precisa ser acusado, construído de
um de três jeitos, sem nunca mudar código de produção:

- adulterando o PDF de saída depois de ``redigir_pdf`` (simula um bug que
  deixou algo para trás);
- desligando um passo de limpeza de ``redacao`` com ``monkeypatch`` (o
  relatório da redação continua AFIRMANDO que limpou, e a verificação tem de
  discordar);
- montando à mão um PDF com o canal ativo e verificando-o direto.
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path
from types import ModuleType

import pymupdf
import pytest

import redator.redacao
import redator.verificacao
from redator.detectors import TODOS_DETECTORES
from redator.entities import EntityType
from redator.pdf import process_pdf
from redator.perfil import AcaoRedacao, EntidadeComAcao, aplicar_perfil
from redator.redacao import redigir_pdf
from redator.verificacao import (
    RelatorioVerificacao,
    VazamentoDetectado,
    verificar_redacao,
)

DETECTORES = list(TODOS_DETECTORES)
PDF_MANUAL = Path(__file__).parent / "fixtures" / "pdf_manual"


def _entidades_por_pagina(caminho: Path) -> dict[int, list[EntidadeComAcao]]:
    return {
        pagina: aplicar_perfil(entidades)
        for pagina, entidades in process_pdf(caminho, DETECTORES).items()
    }


def _origens(relatorio: RelatorioVerificacao) -> list[str]:
    return [v.origem for v in relatorio.vazamentos]


def _pdf_simples(caminho: Path, texto: str = "Texto sem dado pessoal.") -> Path:
    documento = pymupdf.open()
    documento.new_page().insert_text((72, 100), texto, fontname="helv", fontsize=11)
    documento.save(caminho)
    documento.close()
    return caminho


# --------------------------------------------------------------------------- #
# redacao correta: aprovada
# --------------------------------------------------------------------------- #


def test_redacao_correta_e_aprovada(pdf_documentos: Path, tmp_path: Path) -> None:
    entidades = _entidades_por_pagina(pdf_documentos)
    saida = tmp_path / "redigido.pdf"
    redigir_pdf(pdf_documentos, saida, entidades)

    relatorio = verificar_redacao(saida, DETECTORES, entidades)

    assert relatorio.aprovado is True
    assert relatorio.vazamentos == []
    assert relatorio.paginas_verificadas == 1


# --------------------------------------------------------------------------- #
# texto
# --------------------------------------------------------------------------- #


def test_cpf_reinserido_apos_a_redacao_e_acusado_com_tipo_e_pagina(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """Simula um bug de redação: o CPF volta a existir no arquivo final."""
    entrada = gerador.gerar_pdf_paginas(
        tmp_path / "duas.pdf",
        [["CPF nº 529.982.247-25"], ["CPF nº 111.444.777-35"]],
    )
    entidades = _entidades_por_pagina(entrada)
    saida = tmp_path / "redigido.pdf"
    assert redigir_pdf(entrada, saida, entidades).verificacao.aprovado is True

    adulterado = tmp_path / "adulterado.pdf"
    documento = pymupdf.open(saida)
    documento[1].insert_text(
        (72, 500), "CPF nº 111.444.777-35", fontname="helv", fontsize=11
    )
    documento.save(adulterado)
    documento.close()

    relatorio = verificar_redacao(adulterado, DETECTORES, entidades)

    assert relatorio.aprovado is False
    (vazamento,) = relatorio.vazamentos
    assert vazamento.origem == "texto"
    assert vazamento.pagina == 1
    assert vazamento.entity is not None
    assert vazamento.entity.type is EntityType.CPF
    assert vazamento.entity.text == "111.444.777-35"


def test_dado_tarjado_encontrado_em_outra_pagina_tambem_e_vazamento(
    gerador: ModuleType, tmp_path: Path
) -> None:
    """A correspondência é pelo dado, não pela posição: reportado onde achado."""
    entrada = gerador.gerar_pdf_paginas(
        tmp_path / "duas.pdf", [["CPF nº 529.982.247-25"], ["Sem dado pessoal."]]
    )
    entidades = _entidades_por_pagina(entrada)
    saida = tmp_path / "redigido.pdf"
    redigir_pdf(entrada, saida, entidades)

    adulterado = tmp_path / "adulterado.pdf"
    documento = pymupdf.open(saida)
    documento[1].insert_text(
        (72, 300), "CPF nº 529.982.247-25", fontname="helv", fontsize=11
    )
    documento.save(adulterado)
    documento.close()

    (vazamento,) = verificar_redacao(adulterado, DETECTORES, entidades).vazamentos
    assert vazamento.pagina == 1


def test_publicar_reencontrado_nao_e_vazamento(pdf_documentos: Path) -> None:
    """Verifica a ENTRADA, sem redação: só as TARJAR podem ser acusadas.

    O documento tem CPF e telefone (TARJAR) e CNPJ (PUBLICAR). Rodar a
    verificação sobre o arquivo intacto acusa os dois primeiros e nunca o
    terceiro — que é re-encontrado pelo pipeline do mesmo jeito.
    """
    entidades = _entidades_por_pagina(pdf_documentos)
    publicadas = [e for e in entidades[0] if e.acao is AcaoRedacao.PUBLICAR]
    assert [e.entity.type for e in publicadas] == [EntityType.CNPJ]

    relatorio = verificar_redacao(pdf_documentos, DETECTORES, entidades)

    tipos = {v.entity.type for v in relatorio.vazamentos if v.entity}
    assert EntityType.CNPJ not in tipos
    assert {EntityType.CPF, EntityType.TELEFONE} <= tipos


def test_publicar_reencontrado_na_saida_redigida_nao_reprova(
    pdf_documentos: Path, tmp_path: Path
) -> None:
    entidades = _entidades_por_pagina(pdf_documentos)
    saida = tmp_path / "redigido.pdf"
    redigir_pdf(pdf_documentos, saida, entidades)

    reencontradas = {e.type for e in process_pdf(saida, DETECTORES)[0]}
    assert EntityType.CNPJ in reencontradas, "o teste precisa do CNPJ ainda la"
    assert verificar_redacao(saida, DETECTORES, entidades).aprovado is True


# --------------------------------------------------------------------------- #
# metadados (/Info do trailer, /Info do catalogo, XMP)
# --------------------------------------------------------------------------- #


def test_metadado_sobrevivente_e_pego_mesmo_com_a_redacao_afirmando_o_contrario(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limpeza de metadados desligada: a redação diz que limpou, a verificação não."""
    entrada = tmp_path / "metadados.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.set_metadata({"author": "Fulano de Tal"})
    documento.set_xml_metadata("<x:xmpmeta xmlns:x='adobe:ns:meta/'>Fulano</x:xmpmeta>")
    documento.save(entrada)
    documento.close()

    monkeypatch.setattr(redator.redacao, "_limpar_metadados", lambda _documento: None)
    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", {0: []})

    assert relatorio.metadados_removidos is True  # o que a redacao AFIRMA
    assert relatorio.verificacao.aprovado is False  # o que foi CONFERIDO
    detalhes = [v.detalhe for v in relatorio.verificacao.vazamentos]
    assert _origens(relatorio.verificacao) == ["metadados", "metadados"]
    assert any("author" in d for d in detalhes)
    assert any("XMP" in d for d in detalhes)


def test_xmp_solto_fora_do_catalogo_e_pego(tmp_path: Path) -> None:
    """Stream /Type /Metadata pendurado na página: get_xml_metadata() não o vê."""
    caminho = _pdf_simples(tmp_path / "xmp_pagina.pdf")
    documento = pymupdf.open(caminho)
    xmp = documento.get_new_xref()
    documento.update_object(xmp, "<</Type/Metadata/Subtype/XML>>")
    documento.update_stream(xmp, b"<xmp>Fulano 529.982.247-25</xmp>", new=True)
    documento.xref_set_key(documento[0].xref, "Metadata", f"{xmp} 0 R")
    documento.saveIncr()
    documento.close()

    documento = pymupdf.open(caminho)
    assert documento.get_xml_metadata() == "", "premissa: o catalogo nao o referencia"
    documento.close()

    (vazamento,) = verificar_redacao(caminho, DETECTORES, {0: []}).vazamentos
    assert vazamento.origem == "metadados"
    assert "/Type /Metadata" in vazamento.detalhe


def test_info_dentro_do_catalogo_com_campo_alem_de_producer_e_vazamento(
    tmp_path: Path,
) -> None:
    """Lugar fora do padrão que doc.metadata não lê — e que a redação não limpa."""
    caminho = _pdf_simples(tmp_path / "catalogo.pdf")
    documento = pymupdf.open(caminho)
    documento.xref_set_key(
        documento.pdf_catalog(), "Info", "<</Producer(MuPDF)/Author(Fulano)>>"
    )
    documento.saveIncr()
    documento.close()

    relatorio = verificar_redacao(caminho, DETECTORES, {0: []})

    (vazamento,) = relatorio.vazamentos
    assert vazamento.origem == "metadados"
    assert "Author" in vazamento.detalhe
    assert "Producer" not in vazamento.detalhe


def test_producer_do_mupdf_no_catalogo_e_tolerado(tmp_path: Path) -> None:
    """Todo PDF criado pelo PyMuPDF tem isso; acusar seria só ruído."""
    caminho = _pdf_simples(tmp_path / "limpo.pdf")
    documento = pymupdf.open(caminho)
    tipo, valor = documento.xref_get_key(documento.pdf_catalog(), "Info")
    documento.close()
    assert tipo == "dict" and "Producer" in valor, "premissa do teste mudou"

    assert verificar_redacao(caminho, DETECTORES, {0: []}).aprovado is True


# --------------------------------------------------------------------------- #
# AcroForm
# --------------------------------------------------------------------------- #


def test_acroform_sobrevivente_e_pego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrada = tmp_path / "form.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    widget = pymupdf.Widget()
    widget.field_name = "assinatura"
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT  # type: ignore[attr-defined]
    widget.field_value = "Fulano"
    widget.rect = pymupdf.Rect(50, 50, 200, 70)
    pagina.add_widget(widget)
    documento.save(entrada)
    documento.close()

    monkeypatch.setattr(redator.redacao, "_remover_acroform", lambda _documento: None)
    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", {0: []})

    assert relatorio.verificacao.aprovado is False
    assert set(_origens(relatorio.verificacao)) == {"acroform"}


# --------------------------------------------------------------------------- #
# anexos
# --------------------------------------------------------------------------- #


def test_anexo_embutido_sobrevivente_e_pego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrada = tmp_path / "anexo.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.embfile_add("certidao.txt", b"529.982.247-25")
    documento.save(entrada)
    documento.close()

    monkeypatch.setattr(redator.redacao, "_remover_anexos", lambda _documento: 0)
    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", {0: []})

    assert _origens(relatorio.verificacao) == ["anexo"]


def test_anotacao_file_attachment_e_pega_mesmo_com_embfile_count_zero(
    tmp_path: Path,
) -> None:
    """Outro mecanismo de anexo, que embfile_count() nem conta."""
    caminho = _pdf_simples(tmp_path / "anotacao.pdf")
    documento = pymupdf.open(caminho)
    documento[0].add_file_annot(pymupdf.Point(300, 300), b"529.982.247-25", "a.txt")
    documento.saveIncr()
    documento.close()

    documento = pymupdf.open(caminho)
    assert documento.embfile_count() == 0, "premissa: o contador nao ve este anexo"
    documento.close()

    relatorio = verificar_redacao(caminho, DETECTORES, {0: []})
    assert _origens(relatorio) == ["anexo"]
    assert "FileAttachment" in relatorio.vazamentos[0].detalhe


# --------------------------------------------------------------------------- #
# JavaScript
# --------------------------------------------------------------------------- #


def _pdf_com_js_nomeado(caminho: Path) -> Path:
    documento = pymupdf.open()
    documento.new_page()
    js = documento.get_new_xref()
    documento.update_object(js, '<</S/JavaScript/JS(app.alert("oi"))>>')
    nomes = documento.get_new_xref()
    documento.update_object(nomes, f"<</Names[(Acao) {js} 0 R]>>")
    documento.xref_set_key(
        documento.pdf_catalog(), "Names", f"<</JavaScript {nomes} 0 R>>"
    )
    documento.save(caminho)
    documento.close()
    return caminho


def test_javascript_sobrevivente_e_pego(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entrada = _pdf_com_js_nomeado(tmp_path / "js.pdf")
    monkeypatch.setattr(redator.redacao, "_remover_javascript", lambda _documento: False)

    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", {0: []})

    assert _origens(relatorio.verificacao) == ["javascript"]


def test_javascript_neutralizado_pela_redacao_e_aprovado(tmp_path: Path) -> None:
    """``/JS()`` vazio — o que a redação deixa — não é JavaScript com código."""
    entrada = _pdf_com_js_nomeado(tmp_path / "js.pdf")
    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", {0: []})

    assert relatorio.javascript_removido is True
    assert relatorio.verificacao.aprovado is True


def test_javascript_inline_sem_objeto_proprio_e_pego(tmp_path: Path) -> None:
    """Ação aninhada no /AA da página: não é xref próprio, mas tem código."""
    caminho = _pdf_simples(tmp_path / "inline.pdf")
    documento = pymupdf.open(caminho)
    documento.xref_set_key(
        documento[0].xref, "AA", '<</O <</S/JavaScript/JS(app.alert("x"))>>>>'
    )
    documento.saveIncr()
    documento.close()

    assert _origens(verificar_redacao(caminho, DETECTORES, {0: []})) == ["javascript"]


# --------------------------------------------------------------------------- #
# Optional Content
# --------------------------------------------------------------------------- #


def test_camada_opcional_e_sinalizada_sem_saber_o_conteudo(tmp_path: Path) -> None:
    caminho = tmp_path / "ocg.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    camada = documento.add_ocg("Oculta", on=False)
    pagina.insert_text(
        (72, 100), "CPF nº 529.982.247-25", fontname="helv", fontsize=11, oc=camada
    )
    documento.save(caminho)
    documento.close()

    relatorio = verificar_redacao(caminho, DETECTORES, {0: []})

    assert relatorio.aprovado is False
    (vazamento,) = relatorio.vazamentos
    assert vazamento.origem == "optional_content"
    assert vazamento.pagina is None and vazamento.entity is None
    assert "revisao manual" in vazamento.detalhe


# --------------------------------------------------------------------------- #
# canais independentes
# --------------------------------------------------------------------------- #


def test_canais_sao_independentes_e_todos_reportados(
    pdf_documentos: Path, tmp_path: Path
) -> None:
    """Um vazamento num canal não esconde os dos outros."""
    entidades = _entidades_por_pagina(pdf_documentos)
    saida = tmp_path / "redigido.pdf"
    redigir_pdf(pdf_documentos, saida, entidades)

    adulterado = tmp_path / "adulterado.pdf"
    documento = pymupdf.open(saida)
    documento[0].insert_text(
        (72, 600), "CPF nº 529.982.247-25", fontname="helv", fontsize=11
    )
    documento.set_metadata({"author": "Fulano"})
    documento.embfile_add("a.txt", b"x")
    documento.add_ocg("Camada", on=True)
    documento.save(adulterado)
    documento.close()

    origens = set(_origens(verificar_redacao(adulterado, DETECTORES, entidades)))

    assert origens == {"texto", "metadados", "anexo", "optional_content"}


# --------------------------------------------------------------------------- #
# integracao com redigir_pdf
# --------------------------------------------------------------------------- #


def test_redigir_pdf_fluxo_normal_traz_verificacao_aprovada(
    pdf_documentos: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.CRITICAL, logger="redator.redacao"):
        relatorio = redigir_pdf(
            pdf_documentos, tmp_path / "redigido.pdf", _entidades_por_pagina(pdf_documentos)
        )

    assert relatorio.verificacao.aprovado is True
    assert relatorio.verificacao.paginas_verificadas == 1
    assert not [r for r in caplog.records if r.levelno == logging.CRITICAL]


def test_redigir_pdf_reprovado_loga_critico_e_mantem_o_arquivo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entrada = tmp_path / "metadados.pdf"
    documento = pymupdf.open()
    documento.new_page()
    documento.set_metadata({"author": "Fulano de Tal"})
    documento.save(entrada)
    documento.close()
    monkeypatch.setattr(redator.redacao, "_limpar_metadados", lambda _documento: None)

    saida = tmp_path / "redigido.pdf"
    with caplog.at_level(logging.CRITICAL, logger="redator.redacao"):
        relatorio = redigir_pdf(entrada, saida, {0: []})

    assert relatorio.verificacao.aprovado is False
    assert saida.is_file(), "descartar e decisao de quem chama, nao do modulo"
    criticos = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert criticos and "origem=metadados" in criticos[0].getMessage()


def test_camada_opcional_na_entrada_reprova_a_redacao_integrada(
    tmp_path: Path,
) -> None:
    """A redação não trata OCG; a verificação integrada não deixa isso passar."""
    entrada = tmp_path / "ocg.pdf"
    documento = pymupdf.open()
    documento.new_page().insert_text((72, 100), "x", fontname="helv", fontsize=11)
    documento.add_ocg("Camada", on=False)
    documento.save(entrada)
    documento.close()

    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", {0: []})

    assert _origens(relatorio.verificacao) == ["optional_content"]


# --------------------------------------------------------------------------- #
# independencia do modulo de redacao, fixada no codigo
# --------------------------------------------------------------------------- #


def test_verificacao_nao_importa_nada_de_redacao() -> None:
    """A regra de desenho vira teste: nenhum import de redator.redacao.

    Se a verificação reaproveitasse uma função da redação, um bug nela
    esconderia o próprio bug que a verificação existe para pegar.
    """
    fonte = Path(redator.verificacao.__file__).read_text(encoding="utf-8")
    importados: list[str] = []
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.ImportFrom):
            importados.append("." * no.level + (no.module or ""))
        elif isinstance(no, ast.Import):
            importados.extend(alias.name for alias in no.names)
    assert not [m for m in importados if "redacao" in m], importados


def test_vazamento_de_documento_nao_inventa_entidade() -> None:
    vazamento = VazamentoDetectado(
        pagina=None, entity=None, origem="anexo", detalhe="1 anexo"
    )
    assert vazamento.entity is None and vazamento.pagina is None


# --------------------------------------------------------------------------- #
# PDFs manuais: documentos que sabemos estarem corretos
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "nome",
    [
        "FUNSERV_Ata_Conselho_Fiscal_DADOS_FICTICIOS_TESTE.pdf",
        "FUNSERV_Ata_Conselho_Fiscal_DEBUG.pdf",
    ],
)
def test_pdf_manual_redigido_e_aprovado(nome: str, tmp_path: Path) -> None:
    entrada = PDF_MANUAL / nome
    if not entrada.is_file():
        pytest.skip(f"{nome} nao esta no ambiente")
    entidades = _entidades_por_pagina(entrada)

    relatorio = redigir_pdf(entrada, tmp_path / "redigido.pdf", entidades)

    assert relatorio.total_entidades_tarjadas > 0, "sem entidade o teste nao prova nada"
    assert relatorio.verificacao.aprovado is True, relatorio.verificacao.vazamentos
    assert relatorio.verificacao.paginas_verificadas == 4
