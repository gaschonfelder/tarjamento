"""Extração de PDF para texto com posição por caractere.

A tarja precisa cair num retângulo da página, não num offset de string. Por
isso a extração não devolve só texto: devolve, para cada caractere do texto,
a caixa que ele ocupa na página.

A invariante que sustenta tudo é ``len(text) == len(char_boxes)``, com
correspondência posição a posição. Ela vale por construção: o texto não é
pedido ao PyMuPDF pronto — é montado a partir dos caracteres, e todo separador
inserido pelo caminho ganha a sua própria caixa.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymupdf

__all__ = [
    "CharBox",
    "DocumentExtraction",
    "PageExtraction",
    "bboxes_for_span",
    "extract_pdf",
]

BBox = tuple[float, float, float, float]

# Duas caixas estao na mesma linha visual se as bordas verticais coincidem
# dentro desta fracao da altura do caractere. Serve para agrupar o span numa
# caixa por linha, em vez de uma por caractere.
_TOLERANCIA_LINHA = 0.5

# Lacuna horizontal entre spans que vira espaco sintetico, como fracao da
# altura da linha. Abaixo disso e so o kerning entre glifos.
_LACUNA_MINIMA = 0.25

# Duas ``lines`` do rawdict so sao celulas da mesma fileira se a sobreposicao
# vertical real cobre pelo menos esta fracao da altura da menor delas.
_SOBREPOSICAO_MINIMA = 0.5


@dataclass(frozen=True)
class CharBox:
    """Onde um caractere do texto extraído está na página."""

    char: str
    bbox: BBox  # x0, y0, x1, y1
    page: int


@dataclass(frozen=True)
class PageExtraction:
    """O texto de uma página e a posição de cada um de seus caracteres."""

    page: int
    text: str
    char_boxes: list[CharBox]

    def __post_init__(self) -> None:
        if len(self.text) != len(self.char_boxes):
            raise ValueError(
                f"pagina {self.page}: {len(self.text)} caracteres de texto "
                f"para {len(self.char_boxes)} caixas — a correspondencia "
                f"posicao a posicao esta quebrada"
            )


@dataclass(frozen=True)
class DocumentExtraction:
    """Todas as páginas de um documento."""

    pages: list[PageExtraction]

    @property
    def text(self) -> str:
        """Conveniência: as páginas concatenadas, uma por linha de quebra.

        Cuidado: os offsets deste texto NÃO servem para ``bboxes_for_span``,
        que trabalha sempre dentro de uma página.
        """
        return "\n".join(pagina.text for pagina in self.pages)


def _altura(bbox: BBox) -> float:
    return bbox[3] - bbox[1]


def _uniao(boxes: list[BBox]) -> BBox:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _bordas_coincidem(a: BBox, b: BBox) -> bool:
    """Se duas caixas têm as mesmas bordas verticais, dentro da tolerância.

    A folga é proporcional à altura maior. Dois textos na mesma linha-base
    dividem o ``y1``, mas o topo ``y0`` do glifo maior sobe com o tamanho da
    fonte. Medido: 11pt convive com até ~30pt (razão ~2,7×); a partir de 32pt
    as bordas se afastam mais que a folga e as caixas deixam de contar como a
    mesma linha. É deliberado — título grande ao lado de corpo pequeno não é
    uma linha só, e a tarja não deve tratá-los como tal.
    """
    altura = max(_altura(a), _altura(b), 1.0)
    folga = altura * _TOLERANCIA_LINHA
    return abs(a[1] - b[1]) <= folga and abs(a[3] - b[3]) <= folga


def _mesma_linha(anterior: CharBox, proximo: CharBox) -> bool:
    return anterior.page == proximo.page and _bordas_coincidem(
        anterior.bbox, proximo.bbox
    )


def _bbox_da_linha(linha: dict[str, Any]) -> BBox:
    return tuple(float(v) for v in linha["bbox"])  # type: ignore[return-value]


def _mesma_fileira(a: BBox, b: BBox) -> bool:
    """Se duas ``lines`` do ``rawdict`` são células da mesma fileira visual.

    O PyMuPDF segmenta uma fileira de tabela posicionada por coordenada em uma
    ``line`` por célula, sem nenhum separador entre elas. Este critério é o
    que permite juntá-las de volta — e precisa distinguir dois casos que se
    parecem em ``y``:

    1. Células de uma fileira: "Nome" e "CPF" na mesma altura, ou um rótulo e
       o seu valor em colunas. Sobrepõem-se verticalmente E têm fonte parecida.
       Devem virar uma linha de texto só, unidas por espaço — senão a âncora
       de contexto nunca vê o rótulo.

    2. Título grande com corpo pequeno na mesma banda de ``y``: um cabeçalho
       em 32pt ao lado de uma nota em 11pt. Também se sobrepõem, mas a fonte
       é muito diferente. Devem continuar linhas separadas.

    Por isso exige as duas coisas. Sobreposição REAL de ``[y0, y1]``, não só
    ``y0`` parecido — isso pegaria linhas empilhadas com entrelinha apertada.
    E a mesma tolerância de bordas de ``_mesma_linha``, que é o que carrega a
    razão de fonte de ~2,7× e mantém o caso 2 partido.
    """
    sobreposicao = min(a[3], b[3]) - max(a[1], b[1])
    if sobreposicao <= 0:
        return False
    menor = max(min(_altura(a), _altura(b)), 1.0)
    if sobreposicao < menor * _SOBREPOSICAO_MINIMA:
        return False
    return _bordas_coincidem(a, b)


def _fileiras(linhas: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Agrupa ``lines`` consecutivas que formam a mesma fileira visual.

    Só compara vizinhas na ordem de extração. É de propósito: um layout em
    duas colunas de texto corrido tem linhas na mesma altura que NÃO são
    fileira — e o PyMuPDF emite cada coluna como bloco inteiro, então elas
    nunca ficam adjacentes aqui.
    """
    fileiras: list[list[dict[str, Any]]] = []
    atual: list[dict[str, Any]] = []
    for linha in linhas:
        if atual and _mesma_fileira(_bbox_da_linha(atual[-1]), _bbox_da_linha(linha)):
            atual.append(linha)
            continue
        if atual:
            fileiras.append(atual)
        atual = [linha]
    if atual:
        fileiras.append(atual)
    return fileiras


def _caixas_do_char(bruto: dict[str, Any], numero: int) -> list[CharBox]:
    """As caixas de um caractere do ``rawdict``.

    Quase sempre é uma só. O ``rawdict`` pode devolver mais de um caractere
    Unicode num único glifo (uma ligadura que o extrator expande); nesse caso
    cada caractere recebe uma cópia da mesma caixa, para o texto e a lista
    continuarem com o mesmo comprimento.
    """
    texto = str(bruto["c"])
    bbox: BBox = tuple(float(v) for v in bruto["bbox"])  # type: ignore[assignment]
    return [CharBox(char=c, bbox=bbox, page=numero) for c in texto]


def _quebra_de_linha(fim_da_linha: BBox, numero: int) -> CharBox:
    """A caixa do ``\\n`` que separa duas linhas.

    Largura zero, encostada na borda direita da linha que terminou. Não é
    tinta na página — é só um lugar para o separador existir sem furar a
    correspondência posição a posição.
    """
    x1, y0, y1 = fim_da_linha[2], fim_da_linha[1], fim_da_linha[3]
    return CharBox(char="\n", bbox=(x1, y0, x1, y1), page=numero)


def _espaco_sintetico(anterior: CharBox, proximo_bbox: BBox, numero: int) -> CharBox:
    """Espaço para uma lacuna que o PDF não escreveu como caractere.

    A caixa é o próprio vão horizontal: do fim do caractere anterior ao início
    do próximo, na altura do anterior. Serve tanto para dois spans afastados
    dentro de uma ``line`` quanto para duas células da mesma fileira. Se por
    acaso não houver vão (células encostadas ou fora de ordem), a caixa fica
    com largura zero em vez de negativa.
    """
    x0 = anterior.bbox[2]
    x1 = max(proximo_bbox[0], x0)
    return CharBox(
        char=" ", bbox=(x0, anterior.bbox[1], x1, anterior.bbox[3]), page=numero
    )


def _precisa_de_espaco(anterior: CharBox | None, proximo_bbox: BBox) -> bool:
    """Dentro de uma ``line``: só vira espaço se a lacuna passa do kerning."""
    if anterior is None or anterior.char.isspace():
        return False
    lacuna = proximo_bbox[0] - anterior.bbox[2]
    altura = max(_altura(anterior.bbox), 1.0)
    return lacuna > altura * _LACUNA_MINIMA


def _extrair_pagina(pagina: Any, numero: int) -> PageExtraction:
    bruto = pagina.get_text("rawdict")
    linhas = [
        linha
        for bloco in bruto.get("blocks", [])
        if bloco.get("type") == 0  # 0 = texto; 1 = imagem, que nao tem "lines"
        for linha in bloco.get("lines", [])
    ]

    caixas: list[CharBox] = []
    fim_da_fileira: BBox | None = None

    for fileira in _fileiras(linhas):
        if fim_da_fileira is not None:
            caixas.append(_quebra_de_linha(fim_da_fileira, numero))
        anterior: CharBox | None = None
        # Celulas na ordem horizontal, nao na ordem em que o PDF as escreveu.
        ordenadas = sorted(fileira, key=lambda linha: _bbox_da_linha(linha)[0])
        for indice, linha in enumerate(ordenadas):
            fronteira_de_celula = indice > 0
            for span in linha.get("spans", []):
                for char in span.get("chars", []):
                    novas = _caixas_do_char(char, numero)
                    if not novas:
                        continue
                    if fronteira_de_celula:
                        # Entre celulas sempre ha separacao, por menor que seja
                        # o vao: sem isso "Almeida" e "529..." grudariam.
                        if anterior is not None and not anterior.char.isspace():
                            caixas.append(
                                _espaco_sintetico(anterior, novas[0].bbox, numero)
                            )
                        fronteira_de_celula = False
                    elif _precisa_de_espaco(anterior, novas[0].bbox):
                        assert anterior is not None
                        caixas.append(
                            _espaco_sintetico(anterior, novas[0].bbox, numero)
                        )
                    caixas.extend(novas)
                    anterior = caixas[-1]
        fim_da_fileira = _uniao([_bbox_da_linha(linha) for linha in fileira])

    return PageExtraction(
        page=numero,
        text="".join(caixa.char for caixa in caixas),
        char_boxes=caixas,
    )


def extract_pdf(caminho: str | Path) -> DocumentExtraction:
    """Extrai texto e posição de cada caractere, página por página.

    As linhas de uma página são separadas por ``\\n``; não há quebra no fim da
    última linha. Células de uma mesma fileira de tabela — que o PyMuPDF
    entrega como ``lines`` separadas — são reunidas numa linha só, na ordem
    horizontal, com espaço sintético no vão entre elas. Página sem texto — vazia ou só com imagem — devolve
    ``text=""`` e ``char_boxes=[]``, sem erro: um PDF digitalizado é entrada
    legítima, e é o OCR que resolve depois.
    """
    documento = pymupdf.open(str(caminho))
    try:
        paginas = [
            _extrair_pagina(documento[numero], numero)
            for numero in range(documento.page_count)
        ]
    finally:
        documento.close()
    return DocumentExtraction(pages=paginas)


def bboxes_for_span(pagina: PageExtraction, start: int, end: int) -> list[BBox]:
    """Os retângulos que cobrem ``[start, end)`` do texto da página.

    Devolve uma caixa por linha visual, não uma por caractere: os caracteres
    consecutivos que dividem a mesma linha são reunidos na caixa envolvente. Um
    valor que atravessa quebra de linha rende, portanto, mais de um retângulo —
    que é exatamente o que a tarja precisa para não pintar o vão entre eles.

    O ``\\n`` encerra o grupo e não entra na união: ele é separador, não tinta.
    """
    if start < 0 or end > len(pagina.char_boxes):
        raise IndexError(
            f"span ({start}, {end}) fora da pagina de "
            f"{len(pagina.char_boxes)} caracteres"
        )
    if start > end:
        raise ValueError(f"start ({start}) nao pode ser maior que end ({end})")

    grupos: list[list[CharBox]] = []
    atual: list[CharBox] = []
    for caixa in pagina.char_boxes[start:end]:
        if caixa.char == "\n":
            if atual:
                grupos.append(atual)
                atual = []
            continue
        if atual and not _mesma_linha(atual[-1], caixa):
            grupos.append(atual)
            atual = []
        atual.append(caixa)
    if atual:
        grupos.append(atual)

    return [_uniao([caixa.bbox for caixa in grupo]) for grupo in grupos]
