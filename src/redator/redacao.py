"""Redação real de PDF: remoção de conteúdo, não desenho por cima.

Este módulo é o que substitui, para produção, o que ``gerar_pdf_debug``
(``redator.pdf.pipeline``) fazia: aquele marca a área de uma entidade com um
retângulo translúcido, para inspeção — o conteúdo original continua ali,
só coberto. Serve para revisão, mas seria inaceitável para publicação: quem
recebesse o PDF final ainda teria o dado pessoal em mãos, bastando copiar o
texto ou remover a marca no visualizador. ``gerar_pdf_debug`` continua
existindo, para depuração; este módulo é o caminho de verdade.

Aqui, cada entidade a tarjar é marcada com ``page.add_redact_annot`` e a
página passa por ``page.apply_redactions()``: o texto e os desenhos sob a
caixa são de fato removidos do PDF, não apenas cobertos. Entidades a
publicar não são tocadas — a decisão já foi tomada em ``redator.perfil``, e
este módulo só a executa.

**Os três parâmetros de ``apply_redactions``, e por que não são o default.**

- ``images=PDF_REDACT_IMAGE_PIXELS`` (é o default do PyMuPDF, mas fica
  explícito de propósito): apaga só os PIXELS da imagem sob a área marcada,
  não a imagem inteira. Importa para o caso comum de um bloco de texto
  pequeno — um carimbo, um campo preenchido — sobre uma imagem de fundo
  grande, como uma página inteira digitalizada: com
  ``PDF_REDACT_IMAGE_REMOVE`` a página inteira sumiria porque uma entidade
  colidiu com ela. Verificado empiricamente: uma imagem de 400×400 com
  redação de 50×20 num canto sai com o resto dos pixels intactos.
- ``graphics=PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED``, e **não** o default
  (``REMOVE_IF_COVERED``): o default só remove uma forma vetorial (retângulo,
  linha) se ela estiver inteiramente contida na área de redação, e — achado
  ao investigar este ponto — um retângulo cujas bordas coincidem exatamente
  com as da área marcada não conta como "coberto" o suficiente e sobrevive
  intocado. É exatamente o caso de uma tarja gráfica pré-existente ou um
  elemento decorativo desenhado nas mesmas coordenadas do texto detectado —
  cenário plausível, não hipotético. ``REMOVE_IF_TOUCHED`` remove qualquer
  forma que toque a área, o que é mais agressivo, mas para uma ferramenta cuja
  função é garantir que nada de dado pessoal sobreviva, o erro seguro é
  remover um elemento gráfico de mais, não deixar um de menos.
- ``text=PDF_REDACT_TEXT_REMOVE`` — é o comportamento central: sem ele não
  haveria redação nenhuma. Fica explícito só para os três parâmetros
  aparecerem juntos, como uma decisão só.

**O que também é removido, sem parâmetro nenhum.** Anotações que colidem com
a área marcada — inclusive um link (``/Annots`` tipo ``Link``) — somem junto,
por um mecanismo do PyMuPDF independente do ``graphics``: não são "line art"
do conteúdo da página, e ``apply_redactions`` as descarta sempre que a área
delas intersecta uma redação. Relevante para o caso de um link de verificação
(ex.: QR code) cuja área caia sob uma entidade tarjada — o link para de
existir, ainda que o tratamento completo de QR (ler o conteúdo da imagem,
decidir se o próprio código precisa ser coberto) seja tarefa futura.

**Limpeza de metadados — incondicional, não uma opção.** Depois das
redações de conteúdo e antes de salvar, todo documento passa por:

- ``/Info`` (autor, criador, produtor, datas, título — inclusive campos
  CUSTOMIZADOS fora do conjunto padrão): ``set_metadata({})`` não edita
  campo por campo, ele zera a referência ``/Info`` inteira no trailer
  (vira ``null``). Verificado empiricamente: um campo customizado gravado à
  mão no dicionário ``/Info`` (fora dos campos que ``set_metadata`` sequer
  sabe nomear) desaparece do arquivo bruto depois do save com
  ``garbage=4`` — é o garbage collector do PyMuPDF que descarta o objeto
  órfão, não uma edição seletiva. Por isso é suficiente sozinho, sem
  varredura adicional de xref.
- XMP (``/Root/Metadata``, que pode duplicar ou divergir do ``/Info``):
  ``del_xml_metadata()`` remove a referência no catálogo, e uma varredura
  de todos os xrefs zera qualquer objeto ``/Type /Metadata`` encontrado
  solto (não só o referenciado pelo catálogo) — mesma técnica que
  ``Document.scrub()`` usa internamente, adaptada aqui porque ``scrub()``
  faz outras coisas fora de escopo (mexe em link, thumbnail, texto oculto).
- ``AcroForm`` e todo widget (inclusive um de assinatura): removidos por
  completo, não redigidos. Um certificado de assinatura carrega nome e CPF
  do signatário em DER binário dentro do widget — invisível a qualquer
  extração de texto, e ``apply_redactions`` não o atinge porque não é
  conteúdo de página. Cada widget é apagado de cada página
  (``page.delete_widget``) e a chave ``/AcroForm`` do catálogo é anulada;
  o objeto inteiro (campos, valores, assinatura) vira lixo coletável no
  save seguinte.
- Anexos embutidos (``embfile_names``/``embfile_del``): todos, sem exceção.
- JavaScript: qualquer objeto ``/S /JavaScript`` em qualquer xref do
  documento (ação de abertura, campo de nome, ação de widget) tem seu
  ``/JS`` esvaziado — mesma técnica de ``scrub()``.

Nenhum desses seis passos é opcional nem parametrizado: não há cenário,
neste projeto, em que manter metadado original é aceitável num documento
que passou por redação para publicação.

**Optional Content (OCG/camadas) — investigado, não tratado.** Uma camada
desligada por padrão (``add_ocg(..., on=False)``) faz ``page.get_text()`` —
e portanto ``extract_pdf``, e portanto todo detector — devolver `''` para o
texto daquela camada: verificado empiricamente, o texto simplesmente não é
visto. Isso significa que uma entidade escondida numa camada assim **nunca
chega a ser detectada**, e portanto nunca é marcada para redação — o dado
permanece no arquivo, alcançável por qualquer leitor que ligue a camada ou
por um extrator de texto que ignore o estado padrão de OCG (muitos ignoram).
Não é tratado aqui porque nenhum PDF deste projeto (gerados pelo gerador de
teste, ou os PDFs reais de ata/ofício usados nos testes) usa OCG — não há
caso de uso real que o justifique agora. Fica como risco documentado, não
como lacuna silenciosa: se um documento com camadas aparecer em produção,
este módulo não é a defesa contra dado escondido nelas.

**O que este módulo ainda NÃO faz.** Não faz verificação pós-redação
(reabrir o resultado e confirmar que nada sobrou) — fica para a próxima
tarefa. Também não decide política: recebe a decisão já pronta, em
``EntidadeComAcao``.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .pdf import bboxes_for_span, extract_pdf
from .perfil import AcaoRedacao, EntidadeComAcao

__all__ = ["RelatorioRedacao", "redigir_pdf"]

_log = logging.getLogger(__name__)

#: Chaves de ``Document.metadata`` que não são campos reais do dicionário
#: ``/Info`` — ``format`` é derivado da versão do PDF, ``encryption`` do
#: estado de criptografia. Contá-las como "metadado presente" inflaria o
#: relatório sem nenhum dado pessoal por trás.
_CHAVES_METADATA_NAO_REMOVIVEIS = frozenset({"format", "encryption"})


@dataclass(frozen=True, slots=True)
class RelatorioRedacao:
    """O resultado de uma redação: quanto foi tocado, e os hashes de antes/depois.

    Os hashes vêm de ler os dois arquivos do disco depois de tudo pronto —
    não do que ficou em memória durante o processamento —, porque o que
    importa é o que está gravado, e só lendo de novo isso é garantido.

    Os quatro campos de limpeza de documento registram o que *havia* e foi
    removido — não se o passo rodou (ele sempre roda, incondicionalmente):
    ``anexos_removidos == 0`` diz "não havia anexo", não "a limpeza falhou".
    """

    total_entidades_tarjadas: int
    total_entidades_publicadas: int
    paginas_processadas: int
    hash_original: str
    hash_resultado: str
    metadados_removidos: bool
    acroform_removido: bool
    anexos_removidos: int
    javascript_removido: bool


def _sha256_arquivo(caminho: Path) -> str:
    """O sha256 do conteúdo do arquivo, lido do disco agora."""
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def _tinha_metadados(documento: pymupdf.Document) -> bool:
    """``True`` se ``/Info`` (campo real, não ``format``/``encryption``) ou XMP existem."""
    info_preenchido = any(
        valor
        for chave, valor in documento.metadata.items()
        if chave not in _CHAVES_METADATA_NAO_REMOVIVEIS
    )
    return bool(info_preenchido) or bool(documento.get_xml_metadata())


def _limpar_metadados(documento: pymupdf.Document) -> None:
    """Zera ``/Info`` por completo e remove todo XMP, inclusive solto no xref.

    ``set_metadata({})`` não edita campo por campo: com ``/Info`` já
    existente, ele substitui a referência inteira no trailer por ``null`` —
    é por isso que também some campo customizado, fora do conjunto que a
    própria função sabe nomear (ver docstring do módulo, com a verificação).

    Para XMP, ``del_xml_metadata()`` cobre o caso comum (referenciado pelo
    catálogo), e a varredura de xref cobre o objeto ``/Type /Metadata``
    solto que ``del_xml_metadata`` sozinho não alcançaria — mesma técnica
    que ``Document.scrub()`` usa.
    """
    documento.set_metadata({})
    documento.del_xml_metadata()
    for xref in range(1, documento.xref_length()):
        if not documento.xref_object(xref):
            continue
        if documento.xref_get_key(xref, "Type")[1] == "/Metadata":
            documento.update_object(xref, "<<>>")
            documento.update_stream(xref, b"", new=True)


def _tinha_acroform(documento: pymupdf.Document) -> bool:
    if documento.is_form_pdf:
        return True
    return any(
        True
        for numero in range(documento.page_count)
        for _ in documento[numero].widgets()
    )


def _remover_acroform(documento: pymupdf.Document) -> None:
    """Apaga todo widget de toda página e anula ``/AcroForm`` no catálogo.

    Não tenta redigir o conteúdo de um campo de formulário ou de uma
    assinatura — remove o widget inteiro. Um certificado de assinatura
    carrega nome e CPF do signatário em DER binário, invisível a qualquer
    extração de texto; a única garantia é não deixar o objeto no arquivo.
    """
    for numero in range(documento.page_count):
        pagina = documento[numero]
        for widget in list(pagina.widgets()):
            pagina.delete_widget(widget)
    documento.xref_set_key(documento.pdf_catalog(), "AcroForm", "null")


def _remover_anexos(documento: pymupdf.Document) -> int:
    nomes = documento.embfile_names()
    for nome in nomes:
        documento.embfile_del(nome)
    return len(nomes)


def _remover_javascript(documento: pymupdf.Document) -> bool:
    """Esvazia todo objeto ``/S /JavaScript`` — ação de abertura, de campo, etc.

    Varre o xref inteiro em vez de seguir só ``/Root/Names/JavaScript``
    porque uma ação de JavaScript pode estar pendurada em outro lugar (ex.:
    ``/OpenAction``, ou a ``/AA`` de um widget já removido, mas cujo objeto
    de ação pode ter sido criado à parte). Mesma técnica de
    ``Document.scrub()``.
    """
    achou = False
    for xref in range(1, documento.xref_length()):
        if not documento.xref_object(xref):
            continue
        if documento.xref_get_key(xref, "S")[1] == "/JavaScript":
            documento.update_object(xref, "<</S/JavaScript/JS()>>")
            achou = True
    return achou


def _verificar_optional_content(documento: pymupdf.Document, caminho: Path) -> None:
    """Log de alerta, não tratamento: ver o docstring do módulo.

    Uma camada (OCG) desligada por padrão faz o texto dela ficar invisível
    a ``get_text``/``extract_pdf`` — logo, invisível a todo detector. Este
    módulo não sabe redigir o que nunca detectou, então a existência de
    QUALQUER camada é motivo para alguém olhar o documento à mão.
    """
    if documento.get_ocgs():
        _log.warning(
            "%s tem Optional Content (OCG); conteudo em camada desligada por"
            " padrao nao e visto por extract_pdf e pode conter dado pessoal"
            " nao detectado — revisar manualmente",
            caminho,
        )


def redigir_pdf(
    caminho_entrada: str | Path,
    caminho_saida: str | Path,
    entidades_por_pagina: dict[int, list[EntidadeComAcao]],
) -> RelatorioRedacao:
    """Grava em ``caminho_saida`` uma cópia com toda entidade TARJAR removida.

    Para cada página com entidades: cada uma com ``acao == TARJAR`` tem seus
    ``bboxes_for_span`` marcados com ``add_redact_annot(fill=(0, 0, 0))``, e
    ao final da página ``apply_redactions()`` aplica tudo de uma vez — é
    isso que efetivamente apaga o texto e os desenhos sob a área, e não só
    desenha por cima. Os parâmetros de ``apply_redactions`` não são o
    default do PyMuPDF; o porquê de cada um está no docstring do módulo.
    Entidades com ``acao == PUBLICAR`` são ignoradas: nem marcadas, nem
    contadas como tarjadas.

    O documento é salvo com reescrita completa (``garbage=4, deflate=True,
    clean=True``), não incremental — um save incremental manteria a versão
    anterior, não redigida, dentro do próprio arquivo, o que anularia a
    redação.

    ``caminho_saida`` tem de ser um arquivo novo: entrada e saída resolvendo
    para o mesmo caminho é erro, e nada é tocado antes dessa checagem — nunca
    se processa in-place.
    """
    entrada = Path(caminho_entrada)
    saida = Path(caminho_saida)
    if entrada.resolve() == saida.resolve():
        raise ValueError(
            f"saida igual a entrada: {entrada} — nunca processa in-place"
        )

    extraido = {pagina.page: pagina for pagina in extract_pdf(entrada).pages}

    total_tarjadas = 0
    total_publicadas = 0

    documento = pymupdf.open(str(entrada))
    try:
        for numero, entidades in entidades_por_pagina.items():
            if numero not in extraido:
                raise IndexError(f"pagina {numero} nao existe em {entrada}")
            pagina_extraida = extraido[numero]
            pagina_pdf = documento[numero]
            for entidade_com_acao in entidades:
                if entidade_com_acao.acao is AcaoRedacao.PUBLICAR:
                    total_publicadas += 1
                    continue
                entidade = entidade_com_acao.entity
                caixas = bboxes_for_span(pagina_extraida, entidade.start, entidade.end)
                for bbox in caixas:
                    pagina_pdf.add_redact_annot(pymupdf.Rect(*bbox), fill=(0, 0, 0))
                total_tarjadas += 1
            pagina_pdf.apply_redactions(
                images=pymupdf.PDF_REDACT_IMAGE_PIXELS,  # type: ignore[attr-defined]
                graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED,  # type: ignore[attr-defined]
                text=pymupdf.PDF_REDACT_TEXT_REMOVE,  # type: ignore[attr-defined]
            )

        # Limpeza de documento inteiro: incondicional, roda sempre, depois
        # de toda redação de conteúdo e antes do save. Ver docstring do
        # módulo para o porquê de cada passo não ser opcional.
        _verificar_optional_content(documento, entrada)
        metadados_removidos = _tinha_metadados(documento)
        _limpar_metadados(documento)
        acroform_removido = _tinha_acroform(documento)
        _remover_acroform(documento)
        anexos_removidos = _remover_anexos(documento)
        javascript_removido = _remover_javascript(documento)

        documento.save(str(saida), garbage=4, deflate=True, clean=True)
    finally:
        documento.close()

    return RelatorioRedacao(
        total_entidades_tarjadas=total_tarjadas,
        total_entidades_publicadas=total_publicadas,
        paginas_processadas=len(entidades_por_pagina),
        hash_original=_sha256_arquivo(entrada),
        hash_resultado=_sha256_arquivo(saida),
        metadados_removidos=metadados_removidos,
        acroform_removido=acroform_removido,
        anexos_removidos=anexos_removidos,
        javascript_removido=javascript_removido,
    )
