"""Testes do pipeline de deteccao.

Os detectores aqui sao falsos, definidos neste arquivo: a infraestrutura tem de
ser testavel antes de existir qualquer detector real.
"""

from __future__ import annotations

import pytest

from redator.detectors import Detector
from redator.entities import Entity, EntityType
from redator.normalize import normalize
from redator.pipeline import detect_all

NBSP = " "
EN_DASH = "–"


# --------------------------------------------------------------------------- #
# Detectores falsos
# --------------------------------------------------------------------------- #


class DetectorLiteral:
    """Acha todas as ocorrencias de um literal no texto normalizado."""

    def __init__(
        self,
        literal: str,
        entity_type: EntityType = EntityType.CPF,
        *,
        name: str = "literal",
        confidence: float = 0.9,
        validated: bool = False,
    ) -> None:
        self.literal = literal
        self.entity_type = entity_type
        self.name = name
        self.confidence = confidence
        self.validated = validated

    def detect(self, texto: str) -> list[Entity]:
        achadas: list[Entity] = []
        inicio = texto.find(self.literal)
        while inicio != -1:
            fim = inicio + len(self.literal)
            achadas.append(
                Entity(
                    type=self.entity_type,
                    start=inicio,
                    end=fim,
                    text=texto[inicio:fim],
                    confidence=self.confidence,
                    detector=self.name,
                    validated=self.validated,
                )
            )
            inicio = texto.find(self.literal, inicio + 1)
        return achadas


class DetectorVazio:
    """Nunca acha nada."""

    name = "vazio"
    entity_type = EntityType.NOME

    def detect(self, texto: str) -> list[Entity]:
        return []


class DetectorFixo:
    """Devolve exatamente os spans pedidos, sem olhar o texto."""

    def __init__(
        self,
        spans: list[tuple[int, int]],
        entity_type: EntityType = EntityType.TELEFONE,
        *,
        name: str = "fixo",
        confidence: float = 0.9,
        validated: bool = False,
    ) -> None:
        self.spans = spans
        self.entity_type = entity_type
        self.name = name
        self.confidence = confidence
        self.validated = validated

    def detect(self, texto: str) -> list[Entity]:
        return [
            Entity(
                type=self.entity_type,
                start=inicio,
                end=fim,
                text=texto[inicio:fim],
                confidence=self.confidence,
                detector=self.name,
                validated=self.validated,
            )
            for inicio, fim in self.spans
        ]


def test_os_falsos_satisfazem_o_protocolo() -> None:
    assert isinstance(DetectorLiteral("x"), Detector)
    assert isinstance(DetectorVazio(), Detector)
    assert isinstance(DetectorFixo([]), Detector)


# --------------------------------------------------------------------------- #
# Casos degenerados
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("texto", ["", "sem nada relevante", "CPF 529.982.247-25"])
def test_sem_detectores_nao_acha_nada(texto: str) -> None:
    assert detect_all(texto, []) == []


def test_detector_que_nao_acha_nada() -> None:
    assert detect_all("CPF 529.982.247-25", [DetectorVazio()]) == []


def test_varios_detectores_todos_vazios() -> None:
    detectores: list[Detector] = [
        DetectorVazio(),
        DetectorVazio(),
        DetectorLiteral("inexistente"),
    ]
    assert detect_all("texto qualquer", detectores) == []


def test_texto_vazio_com_detectores() -> None:
    assert detect_all("", [DetectorLiteral("x"), DetectorVazio()]) == []


# --------------------------------------------------------------------------- #
# Deteccao simples
# --------------------------------------------------------------------------- #


def test_acha_e_ancora_no_texto_original() -> None:
    texto = "Servidor com CPF 529.982.247-25 cadastrado."
    resultado = detect_all(texto, [DetectorLiteral("529.982.247-25")])
    assert len(resultado) == 1
    entidade = resultado[0]
    assert entidade.span == (17, 31)
    assert texto[17:31] == "529.982.247-25"
    assert entidade.text == "529.982.247-25"


def test_varias_ocorrencias_saem_ordenadas_por_start() -> None:
    texto = "A 111.444.777-35 e B 111.444.777-35 e C 111.444.777-35"
    resultado = detect_all(texto, [DetectorLiteral("111.444.777-35")])
    assert len(resultado) == 3
    assert [e.start for e in resultado] == sorted(e.start for e in resultado)
    for entidade in resultado:
        assert texto[entidade.start : entidade.end] == entidade.text


def test_detectores_de_tipos_diferentes_convivem() -> None:
    texto = "CPF 529.982.247-25, CEP 18045-310."
    detectores: list[Detector] = [
        DetectorLiteral("529.982.247-25", EntityType.CPF, name="cpf"),
        DetectorLiteral("18045-310", EntityType.CEP, name="cep"),
    ]
    resultado = detect_all(texto, detectores)
    assert [e.type for e in resultado] == [EntityType.CPF, EntityType.CEP]


# --------------------------------------------------------------------------- #
# O campo text vem do ORIGINAL, nao do normalizado
# --------------------------------------------------------------------------- #


def test_text_preserva_o_hifen_tipografico_do_original() -> None:
    """O detector casa o hifen ASCII; o resultado devolve o traco original."""
    texto = f"CPF 529.982.247{EN_DASH}25 fim"
    normalizado, _ = normalize(texto)
    assert normalizado == "CPF 529.982.247-25 fim"

    resultado = detect_all(texto, [DetectorLiteral("529.982.247-25")])
    assert len(resultado) == 1
    entidade = resultado[0]
    assert entidade.text == f"529.982.247{EN_DASH}25"
    assert entidade.text != "529.982.247-25"
    assert texto[entidade.start : entidade.end] == entidade.text


def test_text_preserva_o_espaco_nao_quebravel_do_original() -> None:
    texto = f"CPF{NBSP}529.982.247-25"
    resultado = detect_all(texto, [DetectorLiteral("CPF 529.982.247-25")])
    assert len(resultado) == 1
    assert resultado[0].text == texto
    assert NBSP in resultado[0].text


def test_text_atravessa_expansao_do_nfkc() -> None:
    """A ligadura vira dois caracteres no normalizado e um so no original."""
    texto = "conﬁrmado 111.444.777-35"
    normalizado, _ = normalize(texto)
    assert normalizado == "confirmado 111.444.777-35"

    resultado = detect_all(texto, [DetectorLiteral("111.444.777-35")])
    assert len(resultado) == 1
    entidade = resultado[0]
    assert entidade.text == "111.444.777-35"
    assert texto[entidade.start : entidade.end] == entidade.text
    # O offset no original fica uma posicao atras do normalizado.
    assert entidade.start == normalizado.index("111") - 1


def test_text_atravessa_fusao_do_nfkc() -> None:
    """Acento combinante: dois caracteres originais viram um normalizado."""
    texto = "café CPF 987.654.321-00"
    normalizado, _ = normalize(texto)
    assert normalizado == "café CPF 987.654.321-00"

    resultado = detect_all(texto, [DetectorLiteral("987.654.321-00")])
    entidade = resultado[0]
    assert entidade.text == "987.654.321-00"
    assert texto[entidade.start : entidade.end] == entidade.text
    assert entidade.start == normalizado.index("987") + 1


@pytest.mark.parametrize(
    "texto",
    [
        "CPF 529.982.247-25",
        f"CPF{NBSP}529.982.247{EN_DASH}25",
        "conﬁrmado: 529.982.247-25",
        "café 529.982.247-25",
        "linha 1\n529.982.247-25\nlinha 3",
        "  529.982.247-25  ",
    ],
)
def test_text_sempre_bate_com_o_original_nos_offsets(texto: str) -> None:
    resultado = detect_all(texto, [DetectorLiteral("529.982.247-25")])
    assert resultado
    for entidade in resultado:
        assert texto[entidade.start : entidade.end] == entidade.text


# --------------------------------------------------------------------------- #
# resolve_entities foi aplicado
# --------------------------------------------------------------------------- #


def test_sobreposicao_parcial_e_resolvida() -> None:
    """Dois detectores cruzando o mesmo trecho: so o mais forte sobrevive."""
    texto = "0123456789012345678901234567890123456789"
    detectores: list[Detector] = [
        DetectorFixo([(0, 10)], EntityType.CPF, name="a", validated=True),
        DetectorFixo([(5, 20)], EntityType.TELEFONE, name="b", confidence=1.0),
    ]
    resultado = detect_all(texto, detectores)
    assert len(resultado) == 1
    assert resultado[0].span == (0, 10)
    assert resultado[0].detector == "a"


def test_span_identico_de_dois_detectores_vira_um_so() -> None:
    texto = "CPF 529.982.247-25"
    detectores: list[Detector] = [
        DetectorLiteral("529.982.247-25", EntityType.CPF, name="a", validated=True),
        DetectorLiteral("529.982.247-25", EntityType.TELEFONE, name="b"),
    ]
    resultado = detect_all(texto, detectores)
    assert len(resultado) == 1
    assert resultado[0].type is EntityType.CPF


def test_fragmento_espurio_dentro_de_validado_e_descartado() -> None:
    """discard_spurious_fragments roda no fim do pipeline."""
    texto = "documento 529.982.247-25 encerrado"
    detectores: list[Detector] = [
        DetectorLiteral("529.982.247-25", EntityType.CPF, name="cpf", validated=True),
        DetectorLiteral("982.247-25", EntityType.TELEFONE, name="tel"),
    ]
    resultado = detect_all(texto, detectores)
    assert len(resultado) == 1
    assert resultado[0].type is EntityType.CPF


def test_aninhamento_estrutural_sobrevive() -> None:
    """CEP dentro de ENDERECO de NER: os dois ficam."""
    texto = "Rua das Acacias, 184, Sorocaba/SP, CEP 18045-310, Brasil"
    detectores: list[Detector] = [
        DetectorFixo([(0, 48)], EntityType.ENDERECO, name="ner"),
        DetectorLiteral("18045-310", EntityType.CEP, name="cep", validated=True),
    ]
    resultado = detect_all(texto, detectores)
    assert [e.type for e in resultado] == [EntityType.ENDERECO, EntityType.CEP]
    for entidade in resultado:
        assert texto[entidade.start : entidade.end] == entidade.text


def test_resultado_nunca_tem_sobreposicao_parcial() -> None:
    texto = "x" * 60
    detectores: list[Detector] = [
        DetectorFixo([(0, 20), (30, 50)], EntityType.CPF, name="a"),
        DetectorFixo([(15, 35)], EntityType.TELEFONE, name="b"),
        DetectorFixo([(45, 60)], EntityType.CEP, name="c"),
    ]
    resultado = detect_all(texto, detectores)
    for primeira in resultado:
        for segunda in resultado:
            if primeira is not segunda:
                assert not primeira.partially_overlaps(segunda)


# --------------------------------------------------------------------------- #
# Contrato com o detector
# --------------------------------------------------------------------------- #


def test_offset_alem_do_texto_normalizado_e_erro() -> None:
    texto = "curto"
    with pytest.raises(ValueError, match="alem do texto normalizado"):
        detect_all(texto, [DetectorFixo([(0, 99)], name="estourado")])


def test_detector_recebe_o_texto_normalizado() -> None:
    """Prova de que o detector nunca ve o hifen tipografico nem o NBSP."""
    vistos: list[str] = []

    class Espiao:
        name = "espiao"
        entity_type = EntityType.NOME

        def detect(self, texto: str) -> list[Entity]:
            vistos.append(texto)
            return []

    detect_all(f"CPF{NBSP}529.982.247{EN_DASH}25", [Espiao()])
    assert vistos == ["CPF 529.982.247-25"]


def test_ordem_dos_detectores_nao_muda_o_resultado() -> None:
    texto = "A 529.982.247-25 B 18045-310 C"
    cpf = DetectorLiteral("529.982.247-25", EntityType.CPF, name="cpf")
    cep = DetectorLiteral("18045-310", EntityType.CEP, name="cep")
    assert detect_all(texto, [cpf, cep]) == detect_all(texto, [cep, cpf])
