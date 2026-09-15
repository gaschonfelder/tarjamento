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

**O que este módulo NÃO faz ainda.** Não limpa metadados (``/Info``, XMP,
anotações de assinatura, ``AcroForm``) nem faz verificação pós-redação
(reabrir o resultado e confirmar que nada sobrou) — as duas são a próxima
tarefa. Também não decide política: recebe a decisão já pronta, em
``EntidadeComAcao``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .pdf import bboxes_for_span, extract_pdf
from .perfil import AcaoRedacao, EntidadeComAcao

__all__ = ["RelatorioRedacao", "redigir_pdf"]


@dataclass(frozen=True, slots=True)
class RelatorioRedacao:
    """O resultado de uma redação: quanto foi tocado, e os hashes de antes/depois.

    Os hashes vêm de ler os dois arquivos do disco depois de tudo pronto —
    não do que ficou em memória durante o processamento —, porque o que
    importa é o que está gravado, e só lendo de novo isso é garantido.
    """

    total_entidades_tarjadas: int
    total_entidades_publicadas: int
    paginas_processadas: int
    hash_original: str
    hash_resultado: str


def _sha256_arquivo(caminho: Path) -> str:
    """O sha256 do conteúdo do arquivo, lido do disco agora."""
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


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
        documento.save(str(saida), garbage=4, deflate=True, clean=True)
    finally:
        documento.close()

    return RelatorioRedacao(
        total_entidades_tarjadas=total_tarjadas,
        total_entidades_publicadas=total_publicadas,
        paginas_processadas=len(entidades_por_pagina),
        hash_original=_sha256_arquivo(entrada),
        hash_resultado=_sha256_arquivo(saida),
    )
