"""Motor de OCR sobre Tesseract, via pytesseract.

Garantia de posição — a diferença que importa em relação ao PDF nativo:

- ``extract_pdf`` (camada de texto) dá uma caixa POR CARACTERE. Um span pode
  recortar meio CPF, e a tarja cai exatamente nos glifos recortados.
- ``TesseractEngine`` dá uma caixa POR PALAVRA. O Tesseract não devolve caixa
  por caractere de forma confiável, então cada caractere de uma palavra
  recebe a caixa da palavra inteira. Se um span cai PARCIALMENTE dentro de
  uma palavra — o detector achou só metade de um CPF por erro de OCR —,
  ``bboxes_for_span`` devolve a caixa da palavra inteira. Não há como ser
  mais preciso que isso: a tarja cobre a palavra.

Essa diferença é invisível para o restante do pipeline, que recebe a mesma
``PageExtraction`` nos dois casos — e é deliberado que seja: quem precisa
saber é quem vai olhar a tarja, não quem detecta.

Confiança: o Tesseract atribui 0–100 a cada palavra. Toda palavra entra no
texto — omitir texto é pior que marcar dúvida —, mas as abaixo do limiar
ficam registradas em ``PageExtraction.low_confidence_words``, com o
intervalo que ocupam no texto, e cada ``CharBox`` carrega a confiança da sua
palavra.

Requisito de sistema: o binário ``tesseract`` e o pacote de idioma português
(``por.traineddata``) NÃO são dependências Python. Veja o README.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytesseract
from PIL import Image
from pytesseract import Output

from ..pdf.extract import (
    BBox,
    CharBox,
    LowConfidenceWord,
    PageExtraction,
    _espaco_sintetico,
    _quebra_de_linha,
    _uniao,
)

__all__ = [
    "IDIOMA_PADRAO",
    "LIMIAR_CONFIANCA_PADRAO",
    "PSM_PADRAO",
    "TesseractEngine",
    "localizar_tessdata",
    "localizar_tesseract",
    "montar_pagina_de_dados",
    "tesseract_disponivel",
]

IDIOMA_PADRAO = "por"

# PSM 3 = segmentação automática de página: serve para texto corrido —
# parágrafos, blocos, colunas simples. Tabela pede outro modo, e isso fica
# para quando houver tabela real digitalizada para medir.
PSM_PADRAO = 3

# Abaixo disto a palavra continua no texto, mas vai para a lista de revisão.
LIMIAR_CONFIANCA_PADRAO = 60.0

# Onde o instalador da UB-Mannheim costuma deixar o binário no Windows. O
# instalador nem sempre atualiza o PATH da sessão corrente.
_CAMINHOS_WINDOWS = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    Path(os.environ.get("LOCALAPPDATA", ""))
    / "Programs"
    / "Tesseract-OCR"
    / "tesseract.exe",
)


def localizar_tesseract() -> str | None:
    """Caminho do binário: ``TESSERACT_CMD``, depois o PATH, depois o Windows."""
    do_ambiente = os.environ.get("TESSERACT_CMD")
    if do_ambiente and Path(do_ambiente).is_file():
        return do_ambiente
    no_path = shutil.which("tesseract")
    if no_path:
        return no_path
    for candidato in _CAMINHOS_WINDOWS:
        if candidato.is_file():
            return str(candidato)
    return None


def tesseract_disponivel() -> bool:
    return localizar_tesseract() is not None


def localizar_tessdata() -> Path | None:
    """Pasta de idiomas em espaço de usuário, quando o Tesseract não a acharia.

    Se ``TESSDATA_PREFIX`` está definida, o próprio Tesseract a usa e aqui não
    há o que fazer. Senão, ``%LOCALAPPDATA%\\tessdata`` — o lugar que o README
    indica para o ``por.traineddata`` quando não se pode escrever na pasta
    do instalador, que fica em ``Program Files`` e exige elevação.
    """
    if os.environ.get("TESSDATA_PREFIX"):
        return None
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "tessdata"
    if local.is_dir() and any(local.glob("*.traineddata")):
        return local
    return None


def _em_branco(imagem: Image.Image) -> bool:
    """Imagem de uma cor só não tem o que reconhecer — nem vale chamar o OCR."""
    minimo, maximo = imagem.convert("L").getextrema()
    return minimo == maximo


def montar_pagina_de_dados(
    dados: Mapping[str, Sequence[Any]],
    limiar_confianca: float = LIMIAR_CONFIANCA_PADRAO,
    page: int = 0,
) -> PageExtraction:
    """Converte a saída de ``image_to_data(output_type=DICT)`` numa página.

    Público para ser testável sem o binário: o formato do dicionário é
    estável e dá para montar um à mão.

    Só entram as linhas que são palavra (texto não vazio e ``conf >= 0``; os
    níveis de bloco, parágrafo e linha vêm com ``conf == -1``). As palavras
    são agrupadas pela tripla ``(block, par, line)`` do Tesseract, na ordem
    em que aparecem, e ordenadas por ``word_num`` dentro da linha.

    Montagem do texto — os mesmos separadores sintéticos do PDF nativo:
    entre palavras da mesma linha, um espaço cuja caixa é o vão entre elas;
    entre linhas, um ``\\n`` de largura zero. Cada caractere de uma palavra
    recebe a caixa inteira da palavra e a confiança dela.
    """
    palavras_por_linha: dict[
        tuple[int, int, int], list[tuple[int, str, BBox, float]]
    ] = {}
    ordem: list[tuple[int, int, int]] = []

    for indice in range(len(dados["text"])):
        texto = str(dados["text"][indice]).strip()
        if not texto:
            continue
        confianca = float(dados["conf"][indice])
        if confianca < 0:
            continue
        chave = (
            int(dados["block_num"][indice]),
            int(dados["par_num"][indice]),
            int(dados["line_num"][indice]),
        )
        x0 = float(dados["left"][indice])
        y0 = float(dados["top"][indice])
        bbox: BBox = (
            x0,
            y0,
            x0 + float(dados["width"][indice]),
            y0 + float(dados["height"][indice]),
        )
        if chave not in palavras_por_linha:
            palavras_por_linha[chave] = []
            ordem.append(chave)
        palavras_por_linha[chave].append(
            (int(dados["word_num"][indice]), texto, bbox, confianca)
        )

    caixas: list[CharBox] = []
    baixa_confianca: list[LowConfidenceWord] = []
    fim_da_linha_anterior: BBox | None = None

    for chave in ordem:
        palavras = sorted(palavras_por_linha[chave])
        if fim_da_linha_anterior is not None:
            caixas.append(_quebra_de_linha(fim_da_linha_anterior, page))
        for posicao, (_, texto, bbox, confianca) in enumerate(palavras):
            if posicao > 0 and caixas and not caixas[-1].char.isspace():
                caixas.append(_espaco_sintetico(caixas[-1], bbox, page))
            inicio = len(caixas)
            caixas.extend(
                CharBox(char=c, bbox=bbox, page=page, confidence=confianca)
                for c in texto
            )
            if confianca < limiar_confianca:
                baixa_confianca.append(
                    LowConfidenceWord(
                        text=texto,
                        bbox=bbox,
                        confidence=confianca,
                        start=inicio,
                        end=len(caixas),
                        page=page,
                    )
                )
        fim_da_linha_anterior = _uniao([bbox for _, _, bbox, _ in palavras])

    return PageExtraction(
        page=page,
        text="".join(caixa.char for caixa in caixas),
        char_boxes=caixas,
        low_confidence_words=baixa_confianca,
    )


class TesseractEngine:
    """``OcrEngine`` sobre o Tesseract.

    Construir o motor não exige o binário: ele só é procurado para configurar
    o ``pytesseract`` e só é chamado em ``extract_text``. Assim o motor pode
    existir — e ser o padrão de ``extract_pdf_scanned`` — numa máquina sem
    Tesseract, e falhar de forma clara só quando houver o que reconhecer.
    """

    def __init__(
        self,
        idioma: str = IDIOMA_PADRAO,
        psm: int = PSM_PADRAO,
        limiar_confianca: float = LIMIAR_CONFIANCA_PADRAO,
        tesseract_cmd: str | Path | None = None,
        tessdata_dir: str | Path | None = None,
    ) -> None:
        self.idioma = idioma
        self.psm = psm
        self.limiar_confianca = limiar_confianca
        comando = str(tesseract_cmd) if tesseract_cmd else localizar_tesseract()
        if comando:
            # pytesseract guarda o caminho num global de modulo; e assim que
            # a biblioteca funciona, entao e aqui que ele tem de ser posto.
            pytesseract.pytesseract.tesseract_cmd = comando
        self.tessdata_dir = Path(tessdata_dir) if tessdata_dir else localizar_tessdata()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(idioma={self.idioma!r}, psm={self.psm}, "
            f"limiar_confianca={self.limiar_confianca})"
        )

    @property
    def config(self) -> str:
        """A linha de opções passada ao binário."""
        partes = [f"--psm {self.psm}"]
        if self.tessdata_dir is not None:
            partes.append(f'--tessdata-dir "{self.tessdata_dir}"')
        return " ".join(partes)

    def extract_text(self, imagem: Image.Image) -> PageExtraction:
        if _em_branco(imagem):
            return PageExtraction(page=0, text="", char_boxes=[])
        dados = pytesseract.image_to_data(
            imagem,
            lang=self.idioma,
            config=self.config,
            output_type=Output.DICT,
        )
        return montar_pagina_de_dados(dados, self.limiar_confianca)
