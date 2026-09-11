#!/usr/bin/env python
"""Gera o golden set dos fixtures de texto.

Uso:
    uv run python tests/fixtures/anotar.py tests/fixtures/textos/arquivo.txt
    uv run python tests/fixtures/anotar.py --todos

Para cada valor de ``VALORES_CONHECIDOS`` procura todas as ocorrências no texto
e emite ``{"type", "start", "end", "text"}`` num ``.json`` ao lado do ``.txt``.

O arquivo é lido com ``encoding="utf-8"`` e ``newline=""``: nada de tradução de
quebra de linha, porque os offsets precisam bater com o arquivo como está em
disco. Um ``\\r\\n`` conta dois caracteres, e é assim que o detector vai ver.

Andaime de teste: não entra na suíte do pytest e não depende de nada além da
biblioteca padrão e do enum de ``redator.entities``.

Três decisões que valem leitura antes de confiar na saída:

1. Casamento é por literal, mais longo primeiro, e cada trecho só é reivindicado
   uma vez. É o que faz ``+55 (15) 99842-7316`` vencer o ``(15) 99842-7316``
   que mora dentro dele, em vez de gerar duas anotações sobrepostas.

2. Os ``negativo_*.txt`` ficam de fora do ``--todos``. Eles contêm sequências
   que passam no DV de propósito (``52998224725`` como número de série, por
   exemplo) e anotá-las como CPF transformaria o registro de uma limitação em
   um gabarito errado. Use ``--incluir-negativos`` para forçar.

3. Só cobre o que dá para casar por literal: documentos, contatos e a chave PIX.
   NOME, ENDERECO e AGENCIA_CONTA ficam de fora — dependem de NER ou de âncora
   de contexto, e um gabarito feito à mão para eles é trabalho de revisão
   humana, não deste andaime.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from redator.entities import EntityType

TEXTOS = Path(__file__).resolve().parent / "textos"

# Literal exatamente como aparece no fixture -> nome do EntityType.
# Valores já corrigidos: os DVs conferem (ver conferir_numeros.py).
VALORES_CONHECIDOS: dict[str, str] = {
    # ----------------------------------------------------------------- CPF --
    "529.982.247-25": "CPF",
    "111.444.777-35": "CPF",
    "123.456.789-09": "CPF",
    "987.654.321-00": "CPF",
    "52998224725": "CPF",
    "529 982 247 25": "CPF",
    "529-982-247.25": "CPF",
    # CPFs partidos por quebra de linha (doc_teste_1_cpf_quebrado.txt).
    "529.982.\n247-25": "CPF",
    "111.\n444.777-35": "CPF",
    "123.456.789-\n09": "CPF",
    "987654\n32100": "CPF",
    "529 982\n247 25": "CPF",
    # ------------------------------------------------------- CPF_MASCARADO --
    "529.XXX.XXX-25": "CPF_MASCARADO",
    "111.XXX.XXX-35": "CPF_MASCARADO",
    "123.XXX.XXX-09": "CPF_MASCARADO",
    "***.982.247-**": "CPF_MASCARADO",
    "***.***.***-**": "CPF_MASCARADO",
    # ---------------------------------------------------------------- CNPJ --
    "46.634.044/0001-74": "CNPJ",
    "12.345.678/0001-95": "CNPJ",
    "27.865.432/0001-11": "CNPJ",
    "41.258.963/0001-77": "CNPJ",
    "45.678.901/0001-75": "CNPJ",
    "38.456.789/0001-62": "CNPJ",
    # ------------------------------------------------------------------ RG --
    "42.815.739-6": "RG",
    "33.742.918-2": "RG",
    "428157396": "RG",
    # ------------------------------------------------------------ TELEFONE --
    "+55 (15) 99842-7316": "TELEFONE",
    "+55 (15) 99842 7316": "TELEFONE",
    "+55 15 99842-7316": "TELEFONE",
    "(15) 99842-7316": "TELEFONE",
    "(15) 3238-0000": "TELEFONE",
    "15 99842 7316": "TELEFONE",
    "15998427316": "TELEFONE",
    # ----------------------------------------------------------------- CEP --
    "18035-000": "CEP",
    "18035-210": "CEP",
    "18040-120": "CEP",
    "18040-220": "CEP",
    "18045-310": "CEP",
    "18087-150": "CEP",
    "18045310": "CEP",
    # --------------------------------------------------------------- EMAIL --
    "marcelo.almeida@example.com": "EMAIL",
    "MARCELO.ALMEIDA@EXAMPLE.COM": "EMAIL",
    "juliana.ferreira@example.com": "EMAIL",
    "atendimento@fundacao-exemplo.gov.br": "EMAIL",
    # ----------------------------------------------------- outros documentos --
    "02650306461": "CNH",
    "120.44567.89-1": "PIS",
    "12044567891": "PIS",
    "0425 5879 0141": "TITULO_ELEITOR",
    "042558790141": "TITULO_ELEITOR",
    "174 5987 4356 0003": "CNS",
    "174598743560003": "CNS",
    "550e8400-e29b-41d4-a716-446655440000": "CHAVE_PIX",
}


def validar_tipos() -> None:
    """Falha cedo se algum nome de EntityType estiver escrito errado."""
    validos = {membro.name for membro in EntityType}
    desconhecidos = sorted(set(VALORES_CONHECIDOS.values()) - validos)
    if desconhecidos:
        raise SystemExit(
            f"EntityType inexistente em VALORES_CONHECIDOS: {desconhecidos}"
        )


def variantes(literal: str) -> list[str]:
    """O literal e, se ele cruza linhas, a versão com CRLF.

    O arquivo é lido sem tradução de newline, então um fixture com checkout em
    CRLF traria ``\\r\\n`` onde o literal tem ``\\n``.
    """
    if "\n" not in literal:
        return [literal]
    return [literal, literal.replace("\n", "\r\n")]


def anotar(texto: str) -> list[dict[str, object]]:
    """Casa os literais conhecidos, do mais longo para o mais curto.

    Cada posição do texto pertence a no máximo uma anotação: um literal só é
    aceito se o trecho ainda estiver livre.
    """
    reivindicado = bytearray(len(texto))
    anotacoes: list[dict[str, object]] = []

    ordenados = sorted(VALORES_CONHECIDOS, key=len, reverse=True)
    for literal in ordenados:
        tipo = VALORES_CONHECIDOS[literal]
        for variante in variantes(literal):
            inicio = texto.find(variante)
            while inicio != -1:
                fim = inicio + len(variante)
                if not any(reivindicado[inicio:fim]):
                    reivindicado[inicio:fim] = b"\x01" * (fim - inicio)
                    anotacoes.append(
                        {
                            "type": tipo,
                            "start": inicio,
                            "end": fim,
                            "text": variante,
                        }
                    )
                inicio = texto.find(variante, inicio + 1)

    anotacoes.sort(key=lambda anotacao: (anotacao["start"], anotacao["end"]))
    return anotacoes


def gravar(destino: Path, anotacoes: list[dict[str, object]]) -> tuple[Path, bool]:
    """Grava o JSON. Nunca sobrescreve: devolve (caminho, era_novo)."""
    alvo = destino if not destino.exists() else destino.with_suffix(".json.novo")
    conteudo = json.dumps(anotacoes, indent=2, ensure_ascii=False)
    alvo.write_text(f"{conteudo}\n", encoding="utf-8", newline="\n")
    return alvo, alvo == destino


def processar(caminho: Path) -> tuple[Counter[str], set[str]]:
    """Anota um arquivo e devolve (contagem por tipo, literais encontrados)."""
    with caminho.open(encoding="utf-8", newline="") as arquivo:
        texto = arquivo.read()

    anotacoes = anotar(texto)
    destino, era_novo = gravar(caminho.with_suffix(".json"), anotacoes)

    contagem: Counter[str] = Counter(str(a["type"]) for a in anotacoes)
    encontrados = {str(a["text"]) for a in anotacoes}

    print(f"\n{caminho.name}  ->  {destino.name}")
    if not era_novo:
        print(
            "  AVISO: o .json ja existia e foi PRESERVADO."
            f" A saida nova foi para {destino.name}."
        )
    if not anotacoes:
        print("  (nenhum valor conhecido encontrado)")
    for tipo, quantas in sorted(contagem.items()):
        print(f"  {tipo:<16} {quantas}")
    return contagem, encontrados


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Gera o golden set dos fixtures de texto."
    )
    parser.add_argument("arquivos", nargs="*", type=Path, help="arquivos .txt")
    parser.add_argument(
        "--todos", action="store_true", help=f"processa todos os .txt de {TEXTOS}"
    )
    parser.add_argument(
        "--incluir-negativos",
        action="store_true",
        help="nao pula os negativo_*.txt em --todos (veja o docstring)",
    )
    args = parser.parse_args(argv)

    validar_tipos()

    if args.todos:
        alvos = sorted(TEXTOS.glob("*.txt"))
        if not args.incluir_negativos:
            pulados = [c for c in alvos if c.name.startswith("negativo_")]
            alvos = [c for c in alvos if not c.name.startswith("negativo_")]
            if pulados:
                print(
                    f"Pulando {len(pulados)} fixture(s) negativo(s):"
                    f" {', '.join(c.name for c in pulados)}"
                )
                print("Use --incluir-negativos para anota-los mesmo assim.")
    elif args.arquivos:
        alvos = args.arquivos
    else:
        parser.error("informe ao menos um arquivo ou use --todos")

    faltando = [c for c in alvos if not c.is_file()]
    if faltando:
        for caminho in faltando:
            print(f"Arquivo nao encontrado: {caminho}", file=sys.stderr)
        return 1

    total: Counter[str] = Counter()
    vistos: set[str] = set()
    for caminho in alvos:
        contagem, encontrados = processar(caminho)
        total.update(contagem)
        vistos |= encontrados

    print(f"\n{'=' * 72}")
    print(f"TOTAL em {len(alvos)} arquivo(s)")
    print("=" * 72)
    for tipo, quantas in sorted(total.items()):
        print(f"  {tipo:<16} {quantas}")
    print(f"  {'TOTAL':<16} {sum(total.values())}")

    nunca_vistos = sorted(
        literal
        for literal in VALORES_CONHECIDOS
        if not any(variante in vistos for variante in variantes(literal))
    )
    if nunca_vistos:
        print(f"\nAVISO: {len(nunca_vistos)} valor(es) de VALORES_CONHECIDOS")
        print("nao apareceram em nenhum arquivo processado:")
        for literal in nunca_vistos:
            print(f"  {VALORES_CONHECIDOS[literal]:<16} {literal!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
