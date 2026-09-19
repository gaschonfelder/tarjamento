"""Verificação pós-redação: reabre o resultado do zero e procura o que sobrou.

É o teste de regressão permanente da Fase 4. ``redigir_pdf`` afirma o que
fez (``RelatorioRedacao``); este módulo não acredita. Ele abre o arquivo de
saída como qualquer leitor abriria, reconstrói a verdade por conta própria e
compara com o que DEVERIA ter sumido.

**Independência do módulo de redação é o ponto, não um detalhe.** Nada aqui
importa de ``redator.redacao`` — só os tipos compartilhados (``Entity``,
``EntidadeComAcao``, ``AcaoRedacao``). Se a verificação reaproveitasse uma
função interna da redação, um bug nessa função mascararia exatamente o bug
que a verificação existe para pegar. Por isso também as técnicas de detecção
aqui são deliberadamente DIFERENTES das de remoção lá, e mais amplas:

- **JavaScript.** ``redacao`` procura objetos cujo ``/S`` é ``/JavaScript``
  no nível do xref. Uma ação inline — aninhada dentro de outro dicionário,
  como o ``/AA`` de uma página — não é xref próprio e escapa dessa varredura
  (verificado: sobrevive a ``redigir_pdf`` com o conteúdo intacto). Aqui se
  lê o fonte de todo objeto e procura ``/JS`` com conteúdo não vazio, onde
  quer que esteja.
- **Anexos.** ``redacao`` remove os anexos do name tree
  (``embfile_names``). Uma anotação ``FileAttachment`` na página é outro
  mecanismo, que ``embfile_count()`` nem conta (verificado: sobrevive, e o
  contador dá zero). Aqui se checam os dois.
- **Metadados.** Além do ``/Info`` do trailer (o que ``doc.metadata`` lê),
  confere-se um ``/Info`` dentro do CATÁLOGO — lugar fora do padrão, mas em
  que o próprio MuPDF grava ``/Producer`` em todo documento que cria, e que
  ``doc.metadata`` não enxerga. ``/Producer`` sozinho ali é tolerado: é a
  assinatura da biblioteca, presente em toda fixture gerada pelo PyMuPDF, não
  dado do documento de entrada. Qualquer outra chave ali é vazamento.

**Os sete canais são independentes.** Um vazamento num canal não interrompe
os outros: o relatório lista tudo que sobrou, para quem investiga ver o
quadro inteiro de uma vez.

**Limites conhecidos do canal de texto.** Só se detecta o que um detector
reconhece. Uma redação que cortasse METADE de um CPF deixaria um fragmento
("247-25") que nenhum detector casa — não seria acusado. E só contam como
vazamento as entidades que correspondem a uma esperada TARJAR (mesmo tipo,
mesmo texto normalizado): uma entidade de tipo tarjável que aparecesse na
saída sem ter existido na entrada não é acusada aqui.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .detectors import Detector
from .entities import Entity, EntityType
from .pdf import process_pdf
from .perfil import AcaoRedacao, EntidadeComAcao

__all__ = ["RelatorioVerificacao", "VazamentoDetectado", "verificar_redacao"]

ORIGEM_TEXTO = "texto"
ORIGEM_METADADOS = "metadados"
ORIGEM_ACROFORM = "acroform"
ORIGEM_ANEXO = "anexo"
ORIGEM_JAVASCRIPT = "javascript"
ORIGEM_OPTIONAL_CONTENT = "optional_content"

#: Chaves de ``Document.metadata`` que não são campos do ``/Info``: derivadas
#: da versão e da criptografia do arquivo, sempre preenchidas. Mantida aqui
#: por conta própria, sem importar a constante equivalente de ``redacao``.
_CHAVES_DERIVADAS = frozenset({"format", "encryption"})

#: ``/JS`` seguido de string literal não vazia, string hex não vazia, ou
#: referência a objeto (stream com o código). ``/JS()`` e ``/JS<>`` — o que a
#: redação deixa ao neutralizar — não casam.
_JS_LITERAL = re.compile(r"/JS\s*\((?!\))")
_JS_HEX = re.compile(r"/JS\s*<(?!>)")
_JS_REFERENCIA = re.compile(r"/JS\s+(\d+)\s+\d+\s+R")

#: O que o MuPDF grava sozinho no ``/Info`` do catálogo de todo PDF que cria.
_CHAVE_TOLERADA_INFO_CATALOGO = "Producer"


@dataclass(frozen=True, slots=True)
class VazamentoDetectado:
    """Uma coisa que sobreviveu à redação e não deveria.

    ``pagina`` e ``entity`` só existem para ``origem == "texto"``: metadado,
    AcroForm, anexo, JavaScript e camada são do documento, não de uma página
    nem de uma entidade detectada — ``None`` nesses casos, em vez de uma
    ``Entity`` inventada que fingiria uma detecção que não houve. ``detalhe``
    diz, em texto, o que foi achado e onde.
    """

    pagina: int | None
    entity: Entity | None
    origem: str
    detalhe: str


@dataclass(frozen=True, slots=True)
class RelatorioVerificacao:
    aprovado: bool
    vazamentos: list[VazamentoDetectado]
    paginas_verificadas: int


def _chave_texto(tipo: EntityType, texto: str) -> tuple[EntityType, str]:
    """Tipo + texto sem separador nem caixa.

    "Igual ou muito próximo": a redação pode deslocar posição e o extrator
    pode reagrupar espaço e pontuação, mas o dado em si — os dígitos de um
    CPF, as letras de um e-mail — é o mesmo. A posição não entra na chave.
    """
    return tipo, re.sub(r"\W", "", texto).casefold()


def _verificar_texto(
    caminho: Path,
    detectores: list[Detector],
    esperadas: dict[int, list[EntidadeComAcao]],
) -> list[VazamentoDetectado]:
    """Re-detecta do zero e acusa o que casar com uma entidade esperada TARJAR.

    A correspondência não exige a mesma página: o mesmo dado pessoal que
    devia ter saído, encontrado em qualquer página do resultado, é vazamento
    — e é reportado na página em que foi ENCONTRADO. PUBLICAR nunca entra no
    conjunto de busca, então re-encontrar um CNPJ publicado não acusa nada.
    """
    proibidas = {
        _chave_texto(item.entity.type, item.entity.text)
        for itens in esperadas.values()
        for item in itens
        if item.acao is AcaoRedacao.TARJAR
    }
    if not proibidas:
        return []
    vazamentos: list[VazamentoDetectado] = []
    for numero, entidades in sorted(process_pdf(caminho, detectores).items()):
        for entidade in entidades:
            if _chave_texto(entidade.type, entidade.text) in proibidas:
                vazamentos.append(
                    VazamentoDetectado(
                        pagina=numero,
                        entity=entidade,
                        origem=ORIGEM_TEXTO,
                        detalhe=(
                            f"{entidade.type.name} marcado TARJAR ainda legivel"
                            f" na pagina {numero}"
                        ),
                    )
                )
    return vazamentos


def _vazamento_documento(origem: str, detalhe: str) -> VazamentoDetectado:
    return VazamentoDetectado(pagina=None, entity=None, origem=origem, detalhe=detalhe)


def _verificar_metadados(documento: pymupdf.Document) -> list[VazamentoDetectado]:
    vazamentos: list[VazamentoDetectado] = []
    preenchidos = sorted(
        chave
        for chave, valor in documento.metadata.items()
        if chave not in _CHAVES_DERIVADAS and valor
    )
    if preenchidos:
        vazamentos.append(
            _vazamento_documento(
                ORIGEM_METADADOS, f"/Info do trailer com campos preenchidos: {preenchidos}"
            )
        )

    extras = [
        chave
        for chave in _chaves_do_dicionario(documento, documento.pdf_catalog(), "Info")
        if chave != _CHAVE_TOLERADA_INFO_CATALOGO
    ]
    if extras:
        vazamentos.append(
            _vazamento_documento(
                ORIGEM_METADADOS, f"/Info dentro do catalogo com campos: {extras}"
            )
        )

    xmp_do_catalogo = documento.xref_xml_metadata()
    if documento.get_xml_metadata():
        vazamentos.append(
            _vazamento_documento(ORIGEM_METADADOS, "XMP referenciado pelo catalogo")
        )
    # A varredura procura XMP SOLTO: o stream que o catálogo referencia já foi
    # acusado acima, e contá-lo de novo duplicaria o mesmo vazamento.
    for xref in range(1, documento.xref_length()):
        if xref == xmp_do_catalogo:
            continue
        if documento.xref_get_key(xref, "Type")[1] != "/Metadata":
            continue
        if documento.xref_is_stream(xref) and documento.xref_stream(xref).strip():
            vazamentos.append(
                _vazamento_documento(
                    ORIGEM_METADADOS, f"stream /Type /Metadata nao vazio no xref {xref}"
                )
            )
    return vazamentos


def _chaves_do_dicionario(
    documento: pymupdf.Document, xref: int, chave: str
) -> list[str]:
    """As chaves de primeiro nível de ``xref[chave]``, inline ou referência.

    Para dicionário inline, o PyMuPDF devolve só o fonte em texto, e tirar
    chaves dali por regex erraria com ``/`` dentro de string ou dicionário
    aninhado. Em vez disso o fonte vira um objeto temporário, de onde
    ``xref_get_keys`` lê as chaves exatas. O documento nunca é salvo por esta
    verificação, então o objeto temporário não chega a disco nenhum.
    """
    tipo, valor = documento.xref_get_key(xref, chave)
    if tipo == "xref":
        return list(documento.xref_get_keys(int(valor.split()[0])))
    if tipo == "dict":
        temporario = documento.get_new_xref()
        documento.update_object(temporario, valor)
        return list(documento.xref_get_keys(temporario))
    return []


def _verificar_acroform(documento: pymupdf.Document) -> list[VazamentoDetectado]:
    vazamentos: list[VazamentoDetectado] = []
    if documento.is_form_pdf:
        vazamentos.append(
            _vazamento_documento(
                ORIGEM_ACROFORM, f"AcroForm com {documento.is_form_pdf} campo(s)"
            )
        )
    for numero in range(documento.page_count):
        widgets = list(documento[numero].widgets())
        if widgets:
            vazamentos.append(
                _vazamento_documento(
                    ORIGEM_ACROFORM, f"{len(widgets)} widget(s) na pagina {numero}"
                )
            )
    return vazamentos


def _verificar_anexos(documento: pymupdf.Document) -> list[VazamentoDetectado]:
    vazamentos: list[VazamentoDetectado] = []
    if documento.embfile_count():
        vazamentos.append(
            _vazamento_documento(
                ORIGEM_ANEXO,
                f"{documento.embfile_count()} anexo(s) embutido(s): "
                f"{documento.embfile_names()}",
            )
        )
    for numero in range(documento.page_count):
        for anotacao in documento[numero].annots():
            if anotacao.type[0] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT:  # type: ignore[attr-defined]
                vazamentos.append(
                    _vazamento_documento(
                        ORIGEM_ANEXO,
                        f"anotacao FileAttachment na pagina {numero}",
                    )
                )
    return vazamentos


def _verificar_javascript(documento: pymupdf.Document) -> list[VazamentoDetectado]:
    """Procura ``/JS`` não vazio no fonte de TODO objeto, inline incluso."""
    vazamentos: list[VazamentoDetectado] = []
    for xref in range(1, documento.xref_length()):
        fonte = documento.xref_object(xref)
        if not fonte or "/JS" not in fonte:
            continue
        com_codigo = bool(_JS_LITERAL.search(fonte) or _JS_HEX.search(fonte))
        for referencia in _JS_REFERENCIA.findall(fonte):
            alvo = int(referencia)
            if documento.xref_is_stream(alvo) and documento.xref_stream(alvo).strip():
                com_codigo = True
        if com_codigo:
            vazamentos.append(
                _vazamento_documento(
                    ORIGEM_JAVASCRIPT, f"JavaScript com codigo no xref {xref}"
                )
            )
    return vazamentos


def _verificar_optional_content(
    documento: pymupdf.Document,
) -> list[VazamentoDetectado]:
    """Qualquer camada é vazamento EM POTENCIAL — não há como ver dentro dela.

    Conteúdo numa camada desligada por padrão é invisível a ``extract_pdf``,
    logo invisível a esta mesma verificação de texto. Não dá para afirmar que
    há dado pessoal ali; dá para afirmar que ninguém conferiu. Exige revisão
    manual — é o risco já documentado no DECISOES.md (Fase 4, item 3).
    """
    camadas = documento.get_ocgs()
    if not camadas:
        return []
    nomes = sorted(str(info.get("name")) for info in camadas.values())
    return [
        _vazamento_documento(
            ORIGEM_OPTIONAL_CONTENT,
            f"{len(camadas)} camada(s) opcional(is) {nomes}: conteudo em camada"
            " desligada nao e visto pela extracao de texto — revisao manual"
            " obrigatoria",
        )
    ]


def verificar_redacao(
    caminho_resultado: str | Path,
    detectores: list[Detector],
    entidades_esperadas_tarjadas: dict[int, list[EntidadeComAcao]],
) -> RelatorioVerificacao:
    """Reabre ``caminho_resultado`` e procura, em sete canais, o que sobrou.

    ``entidades_esperadas_tarjadas`` é o mesmo dicionário dado a
    ``redigir_pdf`` — com TARJAR e PUBLICAR misturados; só as TARJAR são
    procuradas. ``aprovado`` é ``True`` só se nenhum canal achar nada.
    """
    caminho = Path(caminho_resultado)
    vazamentos = _verificar_texto(caminho, detectores, entidades_esperadas_tarjadas)

    documento = pymupdf.open(str(caminho))
    try:
        paginas = documento.page_count
        vazamentos += _verificar_metadados(documento)
        vazamentos += _verificar_acroform(documento)
        vazamentos += _verificar_anexos(documento)
        vazamentos += _verificar_javascript(documento)
        vazamentos += _verificar_optional_content(documento)
    finally:
        documento.close()

    return RelatorioVerificacao(
        aprovado=not vazamentos,
        vazamentos=vazamentos,
        paginas_verificadas=paginas,
    )
