#!/usr/bin/env python
"""Gera PDFs sintéticos para os testes de extração.

Andaime de teste, não código de produção. Os PDFs não são versionados: os
testes os geram em ``tmp_path`` a cada execução, e só este gerador vai para o
repositório. Assim não há binário no git e o conteúdo do PDF fica legível na
revisão, escrito aqui em texto.

Uso direto, para inspecionar um PDF à mão:
    uv run python tests/fixtures/pdf/gerar_pdf.py /tmp/saida.pdf
"""

from __future__ import annotations

import sys
from pathlib import Path

import pymupdf

__all__ = [
    "COLUNAS_X",
    "FORMULARIO_POSICIONADO",
    "LINHAS_CEP",
    "LINHAS_DOCUMENTOS",
    "LINHAS_QUEBRADAS",
    "TABELA_POSICIONADA",
    "gerar_pdf",
    "gerar_pdf_celulas",
    "gerar_pdf_paginas",
    "gerar_pdf_so_imagem",
    "gerar_pdf_tabela_posicionada",
    "gerar_pdf_vazio",
]

# Posicao e fonte fixas: o teste precisa ser deterministico.
_MARGEM_X = 72.0
_TOPO_Y = 100.0
_ENTRELINHA = 30.0
_FONTE = "helv"
_TAMANHO = 11.0

# Trechos curtos tirados dos fixtures de texto. Nao reproduzem os .txt
# inteiros — so o suficiente para o extrator ter o que casar.
LINHAS_DOCUMENTOS = [
    "CPF nº 529.982.247-25",
    "CNPJ: 46.634.044/0001-74",
    "Telefone: (15) 99842-7316",
]

LINHAS_CEP = [
    "Rua das Acácias, nº 184, apartamento 32,",
    "Jardim Europa, Sorocaba/SP, CEP 18045-310",
]

# "529.982.247-25" parte entre as duas linhas, como em doc_teste_1_cpf_quebrado.
LINHAS_QUEBRADAS = [
    "Inscrito no CPF sob o nº 529.982.",
    "247-25, residente em Sorocaba/SP.",
]


# Tabela por colunas posicionadas — cada celula e um insert_text proprio, em
# coordenada, sem espaco escrito entre elas. E como a maioria dos geradores de
# PDF faz tabela, e e o cenario (b) da investigacao: o rawdict devolve uma line
# por celula, e sem tratamento "Nome" e "CPF" caem em linhas de texto distintas.
TABELA_POSICIONADA: list[tuple[str, ...]] = [
    ("Nome", "CPF"),
    ("Marcelo Henrique de Almeida", "529.982.247-25"),
    ("Juliana Cristina Ferreira", "111.444.777-35"),
]
COLUNAS_X: tuple[float, ...] = (72.0, 300.0)

# Formulario rotulo | valor em colunas: o rotulo fica na MESMA fileira do valor,
# entao a ancora de contexto so o enxerga se a fileira for reconstruida.
FORMULARIO_POSICIONADO: list[tuple[str, ...]] = [
    ("CPF:", "529.982.247-25"),
    ("CEP:", "18045-310"),
]


def gerar_pdf_celulas(
    caminho: str | Path, celulas: list[tuple[float, float, str, float]]
) -> Path:
    """Uma página com texto em posições livres.

    Cada célula é ``(x, y, texto, tamanho_da_fonte)``. É o gerador mais cru:
    serve para montar fileiras de tabela, fontes mistas e células fora de
    ordem, sem nenhuma opinião sobre layout.
    """
    documento = pymupdf.open()
    pagina = documento.new_page()
    for x, y, texto, tamanho in celulas:
        pagina.insert_text((x, y), texto, fontname=_FONTE, fontsize=tamanho)
    destino = Path(caminho)
    documento.save(str(destino))
    documento.close()
    return destino


def gerar_pdf_tabela_posicionada(
    caminho: str | Path,
    fileiras: list[tuple[str, ...]] = TABELA_POSICIONADA,
    colunas_x: tuple[float, ...] = COLUNAS_X,
    tamanho: float = _TAMANHO,
) -> Path:
    """Tabela cujas colunas são posicionadas por coordenada, não por espaço."""
    celulas = [
        (colunas_x[coluna], _TOPO_Y + indice * _ENTRELINHA, texto, tamanho)
        for indice, fileira in enumerate(fileiras)
        for coluna, texto in enumerate(fileira)
    ]
    return gerar_pdf_celulas(caminho, celulas)


def gerar_pdf(caminho: str | Path, linhas: list[str]) -> Path:
    """Escreve uma página com uma linha de texto por elemento de ``linhas``."""
    documento = pymupdf.open()
    pagina = documento.new_page()
    for indice, linha in enumerate(linhas):
        pagina.insert_text(
            (_MARGEM_X, _TOPO_Y + indice * _ENTRELINHA),
            linha,
            fontname=_FONTE,
            fontsize=_TAMANHO,
        )
    destino = Path(caminho)
    documento.save(str(destino))
    documento.close()
    return destino


def gerar_pdf_paginas(caminho: str | Path, paginas: list[list[str]]) -> Path:
    """Várias páginas, cada uma com as suas linhas. Lista vazia = página em branco."""
    documento = pymupdf.open()
    for linhas in paginas:
        pagina = documento.new_page()
        for indice, linha in enumerate(linhas):
            pagina.insert_text(
                (_MARGEM_X, _TOPO_Y + indice * _ENTRELINHA),
                linha,
                fontname=_FONTE,
                fontsize=_TAMANHO,
            )
    destino = Path(caminho)
    documento.save(str(destino))
    documento.close()
    return destino


def gerar_pdf_vazio(caminho: str | Path, paginas: int = 1) -> Path:
    """Páginas em branco: nem texto, nem imagem."""
    documento = pymupdf.open()
    for _ in range(paginas):
        documento.new_page()
    destino = Path(caminho)
    documento.save(str(destino))
    documento.close()
    return destino


def gerar_pdf_so_imagem(caminho: str | Path) -> Path:
    """Uma página com um retângulo colorido e nenhum caractere.

    É o PDF digitalizado do pobre: o extrator tem de devolver texto vazio em
    vez de estourar.
    """
    documento = pymupdf.open()
    pagina = documento.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 64, 64))
    pixmap.set_rect(pixmap.irect, (200, 30, 30))
    pagina.insert_image(pymupdf.Rect(100, 100, 300, 300), pixmap=pixmap)
    destino = Path(caminho)
    documento.save(str(destino))
    documento.close()
    return destino


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"uso: {Path(argv[0]).name} <saida.pdf>", file=sys.stderr)
        return 1
    destino = gerar_pdf(argv[1], LINHAS_DOCUMENTOS + LINHAS_CEP)
    print(f"gerado: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
