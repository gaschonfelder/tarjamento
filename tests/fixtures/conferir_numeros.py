#!/usr/bin/env python
"""Confere o DV dos números usados nos fixtures de texto.

Uso:
    uv run python tests/fixtures/conferir_numeros.py

Varre os ``.txt`` de ``tests/fixtures/textos/``, extrai sequências numéricas com
os comprimentos dos documentos que sabemos validar e roda os validadores de
``redator.validators`` sobre cada uma. Serve para descobrir se algum número
inventado à mão tem dígito verificador inválido — o que faria um fixture medir
outra coisa que não o que ele diz medir.

Andaime de teste: não altera arquivo nenhum, não entra na suíte do pytest e sai
sempre com código 0. Vários fixtures contêm números inválidos de propósito
(``negativo_*``, ``cpf_irregular``, ``cpf_quebrado``), então "não passou" aqui é
informação para leitura humana, não reprovação.

Limitação conhecida da extração: o padrão é deliberadamente simples e casa a
maior corrida de dígitos possível. Uma corrida de comprimento inesperado é
descartada inteira, mesmo que contenha um documento válido dentro dela.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path

from redator.validators import (
    is_valid_cnh,
    is_valid_cnpj,
    is_valid_cns,
    is_valid_cpf,
    is_valid_pis,
    is_valid_processo_cnj,
    is_valid_titulo_eleitor,
)

TEXTOS = Path(__file__).resolve().parent / "textos"

# Dígitos separados por no máximo um sinal de pontuação — cobre 52998224725,
# 529.982.247-25, 46.634.044/0001-74 e 123 4567 8901 2345.
CANDIDATO = re.compile(r"\d(?:[.\-/ ]?\d)+")

Validador = Callable[[str], bool]

VALIDADORES_POR_TAMANHO: dict[int, tuple[tuple[str, Validador], ...]] = {
    11: (("CPF", is_valid_cpf), ("PIS", is_valid_pis), ("CNH", is_valid_cnh)),
    12: (("TITULO_ELEITOR", is_valid_titulo_eleitor),),
    14: (("CNPJ", is_valid_cnpj),),
    15: (("CNS", is_valid_cns),),
    20: (("PROCESSO_CNJ", is_valid_processo_cnj),),
}


class Ocorrencia:
    """Um candidato encontrado num arquivo, com onde e quantas vezes apareceu."""

    def __init__(self, bruto: str, digitos: str, linha: int) -> None:
        self.bruto = bruto
        self.digitos = digitos
        self.primeira_linha = linha
        self.vezes = 1

    @property
    def resultados(self) -> list[tuple[str, bool]]:
        validadores = VALIDADORES_POR_TAMANHO[len(self.digitos)]
        return [(nome, validador(self.digitos)) for nome, validador in validadores]

    @property
    def passou_em_algum(self) -> bool:
        return any(passou for _, passou in self.resultados)

    @property
    def tipos_testados(self) -> str:
        return ", ".join(nome for nome, _ in self.resultados)

    @property
    def marcador(self) -> str:
        return f"L{self.primeira_linha:03d}" + (
            f" x{self.vezes}" if self.vezes > 1 else ""
        )


def extrair(texto: str) -> list[Ocorrencia]:
    """Colhe os candidatos de um arquivo, agrupando repetições do mesmo número."""
    encontrados: dict[str, Ocorrencia] = {}
    for numero_linha, linha in enumerate(texto.splitlines(), start=1):
        for match in CANDIDATO.finditer(linha):
            bruto = match.group()
            digitos = re.sub(r"\D", "", bruto)
            if len(digitos) not in VALIDADORES_POR_TAMANHO:
                continue
            existente = encontrados.get(bruto)
            if existente is None:
                encontrados[bruto] = Ocorrencia(bruto, digitos, numero_linha)
            else:
                existente.vezes += 1
    return list(encontrados.values())


def relatar_arquivo(caminho: Path, ocorrencias: list[Ocorrencia]) -> None:
    print(f"\n{caminho.name}")
    if not ocorrencias:
        print("  (nenhum candidato de comprimento conhecido)")
        return
    for ocorrencia in ocorrencias:
        for nome, passou in ocorrencia.resultados:
            print(
                f"  {ocorrencia.marcador:<10} {ocorrencia.bruto:<24}"
                f" {nome:<15} {'PASSOU' if passou else 'falhou'}"
            )


def relatar_resumo(reprovados: dict[Path, list[Ocorrencia]], total: int) -> None:
    print(f"\n{'=' * 72}")
    print("RESUMO - candidatos que nao passaram em NENHUM validador")
    print("=" * 72)
    if not reprovados:
        print("\n  Nenhum. Todos os candidatos fecham o DV de pelo menos um tipo.")
    for caminho, ocorrencias in sorted(reprovados.items()):
        print(f"\n  {caminho.name}")
        for ocorrencia in ocorrencias:
            print(
                f"    {ocorrencia.marcador:<10} {ocorrencia.bruto:<24}"
                f" {len(ocorrencia.digitos):>2} digitos"
                f"  testado contra: {ocorrencia.tipos_testados}"
            )
    reprovados_total = sum(len(o) for o in reprovados.values())
    print(
        f"\n{total} candidatos distintos examinados, "
        f"{reprovados_total} sem validador que os aceite."
    )
    print("Lembrete: fixtures negativos contem numeros invalidos de proposito.")


def main() -> int:
    if not TEXTOS.is_dir():
        print(f"Diretorio de fixtures nao encontrado: {TEXTOS}", file=sys.stderr)
        return 1

    arquivos = sorted(TEXTOS.glob("*.txt"))
    if not arquivos:
        print(f"Nenhum .txt em {TEXTOS}", file=sys.stderr)
        return 1

    reprovados: dict[Path, list[Ocorrencia]] = defaultdict(list)
    total = 0

    for caminho in arquivos:
        ocorrencias = extrair(caminho.read_text(encoding="utf-8"))
        total += len(ocorrencias)
        relatar_arquivo(caminho, ocorrencias)
        for ocorrencia in ocorrencias:
            if not ocorrencia.passou_em_algum:
                reprovados[caminho].append(ocorrencia)

    relatar_resumo(dict(reprovados), total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
