"""Pipeline completo contra o golden set dos fixtures.

Roda TODOS os detectores sobre cada fixture e compara com o ``.json`` ao lado.

Regras da comparação:

- ``esperado_fase: 2`` fica de fora — depende de layout, que é a fase seguinte.
- ``allowlist: true`` CONTA como esperada: o detector tem de achar o dado
  institucional; quem decide não tarjar é a política, depois.
- Nos ``negativo_*.txt`` qualquer detecção, de qualquer tipo, é falha.
- Nos fixtures positivos a comparação se restringe aos tipos que o golden set
  anota. AGENCIA_CONTA, CID e DATA_NASCIMENTO não têm anotação nenhuma, então
  não há gabarito contra o que medi-los; ficam cobertos pelo teste de
  visibilidade no fim do arquivo, que fixa o que eles detectam hoje.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from redator.detectors import TODOS_DETECTORES
from redator.pipeline import detect_all

TEXTOS = Path(__file__).parent / "fixtures" / "textos"
POSITIVOS = sorted(
    p for p in TEXTOS.glob("*.txt") if not p.name.startswith("negativo_")
)
NEGATIVOS = sorted(TEXTOS.glob("negativo_*.txt"))


def _tipos_anotados() -> frozenset[str]:
    tipos: set[str] = set()
    for caminho in TEXTOS.glob("*.json"):
        tipos |= {a["type"] for a in json.loads(caminho.read_text(encoding="utf-8"))}
    return frozenset(tipos)


TIPOS_ANOTADOS = _tipos_anotados()


@dataclass(frozen=True)
class Achado:
    tipo: str
    start: int
    end: int
    texto: str


# Falsos positivos conhecidos e aceitos nesta fase. Nao entram no golden set
# como anotacao — o gabarito descreve o que o documento CONTEM, nao o que o
# detector erra. Ficam aqui, nomeados, para que o teste nao os leia como
# regressao e para que sumirem tambem apareca (test_falso_positivo_aceito_*).
#
# 18035000 em "Quantidade em estoque:" e oito digitos sob rotulo que nao esta
# na lista administrativa. Sai com 0.5 e requires_review=True, e CEP isolado
# nunca e tarjado sozinho — refinar esse caminho nao e objetivo desta fase.
FALSOS_POSITIVOS_ACEITOS: dict[str, set[tuple[str, int, int]]] = {
    "dificil_cep_sem_rotulo.txt": {("CEP", 433, 441)},
}


def aceitos(txt: Path) -> set[tuple[str, int, int]]:
    return FALSOS_POSITIVOS_ACEITOS.get(txt.name, set())


def sem_aceitos(txt: Path, achados: set[Achado]) -> set[Achado]:
    """Tira do conjunto os falsos positivos ja documentados para o fixture."""
    conhecidos = aceitos(txt)
    return {a for a in achados if (a.tipo, a.start, a.end) not in conhecidos}


def ler(txt: Path) -> str:
    """Sem traduzir quebra de linha: os offsets do golden set são do arquivo."""
    with txt.open(encoding="utf-8", newline="") as arquivo:
        return arquivo.read()


def detectadas(texto: str, *, so_anotados: bool = True) -> set[Achado]:
    return {
        Achado(e.type.name, e.start, e.end, e.text)
        for e in detect_all(texto, list(TODOS_DETECTORES))
        if not so_anotados or e.type.name in TIPOS_ANOTADOS
    }


def esperadas(txt: Path, texto: str) -> set[Achado]:
    caminho = txt.with_suffix(".json")
    if not caminho.exists():
        return set()
    return {
        Achado(a["type"], a["start"], a["end"], texto[a["start"] : a["end"]])
        for a in json.loads(caminho.read_text(encoding="utf-8"))
        if a.get("esperado_fase") != 2
    }


def relatorio(nome: str, vp: set[Achado], fn: set[Achado], fp: set[Achado]) -> str:
    contagem = {
        "VP": Counter(a.tipo for a in vp),
        "FN": Counter(a.tipo for a in fn),
        "FP": Counter(a.tipo for a in fp),
    }
    linhas = [f"{nome}: VP={len(vp)} FN={len(fn)} FP={len(fp)}", "", "por tipo:"]
    linhas += [
        f"  {tipo:<16} VP={contagem['VP'][tipo]:<3}"
        f" FN={contagem['FN'][tipo]:<3} FP={contagem['FP'][tipo]}"
        for tipo in sorted({a.tipo for a in vp | fn | fp})
    ]
    for rotulo, conjunto in (("FALSOS NEGATIVOS", fn), ("FALSOS POSITIVOS", fp)):
        if conjunto:
            linhas += ["", f"{rotulo}:"]
            linhas += [
                f"  {a.tipo:<16} {nome} offset {a.start}-{a.end}  {a.texto!r}"
                for a in sorted(conjunto, key=lambda a: a.start)
            ]
    return "\n".join(linhas)


# --------------------------------------------------------------------------- #
# Fixtures positivos
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("txt", POSITIVOS, ids=lambda p: p.stem)
def test_fixture_bate_com_o_golden_set(txt: Path) -> None:
    texto = ler(txt)
    achadas, esperado = detectadas(texto), esperadas(txt, texto)
    fp = sem_aceitos(txt, achadas - esperado)
    assert not (esperado - achadas) and not fp, relatorio(
        txt.name, achadas & esperado, esperado - achadas, fp
    )


def test_cobertura_agregada() -> None:
    """Resumo por tipo sobre todos os fixtures positivos."""
    vp: set[Achado] = set()
    fn: set[Achado] = set()
    fp: set[Achado] = set()
    for txt in POSITIVOS:
        texto = ler(txt)
        achadas, esperado = detectadas(texto), esperadas(txt, texto)
        vp |= achadas & esperado
        fn |= esperado - achadas
        fp |= sem_aceitos(txt, achadas - esperado)
    assert not fn and not fp, relatorio("todos os positivos", vp, fn, fp)
    assert {a.tipo for a in vp} == TIPOS_ANOTADOS
    assert len(vp) >= 100


@pytest.mark.parametrize("tipo", sorted(TIPOS_ANOTADOS))
def test_todo_tipo_anotado_e_detectado_em_algum_fixture(tipo: str) -> None:
    achados = {
        a.texto for txt in POSITIVOS for a in detectadas(ler(txt)) if a.tipo == tipo
    }
    assert achados, f"nenhuma deteccao de {tipo} em fixture nenhum"


def test_allowlist_conta_como_esperada() -> None:
    """Os dados institucionais do órgão têm de ser achados, não ignorados."""
    institucionais = 0
    for txt in POSITIVOS:
        texto = ler(txt)
        achadas = detectadas(texto)
        caminho = txt.with_suffix(".json")
        if not caminho.exists():
            continue
        for a in json.loads(caminho.read_text(encoding="utf-8")):
            if not a.get("allowlist"):
                continue
            institucionais += 1
            alvo = Achado(a["type"], a["start"], a["end"], texto[a["start"] : a["end"]])
            assert alvo in achadas, f"{txt.name} offset {a['start']}: {alvo.texto!r}"
    assert institucionais == 9


def test_anotacoes_de_fase_2_ficam_de_fora() -> None:
    """O fixture de quebra de linha não é cobrado nesta fase."""
    txt = TEXTOS / "doc_teste_1_cpf_quebrado.txt"
    anotacoes = json.loads(txt.with_suffix(".json").read_text(encoding="utf-8"))
    assert anotacoes and all(a.get("esperado_fase") == 2 for a in anotacoes)
    assert esperadas(txt, ler(txt)) == set()


# --------------------------------------------------------------------------- #
# Fixtures negativos: qualquer detecção é falha
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("txt", NEGATIVOS, ids=lambda p: p.stem)
def test_fixture_negativo_fica_limpo(txt: Path) -> None:
    achadas = detectadas(ler(txt), so_anotados=False)
    assert not achadas, relatorio(txt.name, set(), set(), achadas)


def test_armadilhas_caem_por_ancora_negativa() -> None:
    """As cinco sequencias que fecham o DV de CPF mas nao sao dado pessoal.

    A regra de fronteira derruba as duas com letra colada; as outras cinco so
    caem pelo rotulo administrativo que vem antes delas.
    """
    from redator.detectors.documentos import detector_cpf

    texto = ler(TEXTOS / "negativo_armadilhas.txt")
    assert detector_cpf.detect(texto) == []
    # Sem o rotulo, o mesmo numero seria detectado — a supressao vem do contexto.
    assert len(detector_cpf.detect("11144477735")) == 1


# --------------------------------------------------------------------------- #
# Tipos sem anotação no golden set
# --------------------------------------------------------------------------- #


def test_agencia_conta_detectada_apesar_de_nao_estar_no_golden() -> None:
    """Fixa o que AGENCIA_CONTA acha hoje, ja que nao ha gabarito para ela."""
    texto = ler(TEXTOS / "doc_teste_1_dados_bancarios.txt")
    achadas = sorted(
        (
            e
            for e in detect_all(texto, list(TODOS_DETECTORES))
            if e.type.name == "AGENCIA_CONTA"
        ),
        key=lambda e: e.start,
    )
    assert [e.text for e in achadas] == [
        "1847-3",
        "00284715-9",
        "0001",
        "847291-5",
        "0001",
        "9182746-2",
        "2845-7",
        "00018472-3",
    ]
    assert all(e.context is not None for e in achadas)


@pytest.mark.parametrize("tipo", ["CID", "DATA_NASCIMENTO"])
def test_tipos_sem_ocorrencia_nos_fixtures_nao_inventam(tipo: str) -> None:
    for txt in sorted(TEXTOS.glob("*.txt")):
        achadas = {
            e.text
            for e in detect_all(ler(txt), list(TODOS_DETECTORES))
            if e.type.name == tipo
        }
        assert not achadas, f"{tipo} inventado em {txt.name}: {achadas}"


def test_falso_positivo_aceito_continua_sendo_produzido() -> None:
    """A tolerancia acima nao pode virar letra morta.

    Se o detector parar de emitir este falso positivo, e porque o caminho do
    CEP sem ancora mudou — e a entrada em FALSOS_POSITIVOS_ACEITOS precisa
    sair junto, em vez de ficar escondendo outra coisa.
    """
    txt = TEXTOS / "dificil_cep_sem_rotulo.txt"
    texto = ler(txt)
    achadas = detectadas(texto)
    for tipo, inicio, fim in aceitos(txt):
        alvo = Achado(tipo, inicio, fim, texto[inicio:fim])
        assert alvo in achadas, f"{alvo} nao e mais produzido: limpe a tolerancia"


def test_cep_em_endereco_sai_consistente() -> None:
    """Os tres CEPs em contexto de endereco valem o mesmo, nao dois valores."""
    from redator.entities import EntityType

    txt = TEXTOS / "dificil_cep_sem_rotulo.txt"
    texto = ler(txt)
    ceps = sorted(
        (
            e
            for e in detect_all(texto, list(TODOS_DETECTORES))
            if e.type is EntityType.CEP
        ),
        key=lambda e: e.start,
    )
    em_endereco = [e for e in ceps if e.start < 340]
    assert [e.text for e in em_endereco] == ["18045-310", "18087-150", "18040220"]
    assert {e.confidence for e in em_endereco} == {0.9}
    assert not any(e.requires_review for e in em_endereco)

    soltos = [e for e in ceps if e.start >= 340]
    assert {e.confidence for e in soltos} == {0.5}
    assert all(e.requires_review for e in soltos)
