"""Detectores que só existem com âncora.

RG não tem DV universal, agência e conta são dígitos soltos, CID é uma letra e
dois números, data de nascimento é uma data como outra qualquer. Nenhum desses
padrões se sustenta sozinho: sem o rótulo antes, o detector não devolve nada.
"""

from __future__ import annotations

import re

from ..anchors import buscar_ancora, tem_ancora_negativa
from ..entities import Entity, EntityType
from ._fronteiras import ANTES, DEPOIS

__all__ = [
    "CONFIANCA_ANCORADA",
    "CONFIANCA_ANCORADA_FRACA",
    "DETECTORES_CONTEXTUAIS",
    "DetectorContextual",
    "detector_agencia_conta",
    "detector_chave_pix",
    "detector_cid",
    "detector_data_nascimento",
    "detector_rg",
]

CONFIANCA_ANCORADA = 0.99
# Ancora presente, mas o valor tambem seria reconhecido por outro tipo.
CONFIANCA_ANCORADA_FRACA = 0.7

# 42.815.739-6 / 428157396 / 33.742.918-2. O orgao emissor (SSP/SP) pode vir
# depois, mas nao entra no span: o dado e o numero.
_PADRAO_RG = re.compile(
    rf"{ANTES}(?:\d{{1,2}}\.\d{{3}}\.\d{{3}}-?[0-9Xx]|\d{{7,9}}[Xx]?){DEPOIS}"
)

# 1847-3 / 0001 / 00284715-9 / 847291-5 / 9182746-2
_PADRAO_AGENCIA_CONTA = re.compile(rf"{ANTES}\d{{3,12}}(?:-[0-9Xx])?{DEPOIS}")

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_EMAIL = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,}"
_CPF = r"\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11}"
_TELEFONE = r"\+?\s?(?:55[\s.-]?)?(?:\(\d{2}\)|\d{2})[\s.-]?\d{4,5}[\s.-]?\d{4}"
_PADRAO_CHAVE_PIX = re.compile(rf"(?<![\w.+-])(?:{_UUID}|{_EMAIL}|{_CPF}|{_TELEFONE})")

_PADRAO_CID = re.compile(r"(?<![^\W_])[A-Z]\d{2}(?:\.\d)?(?![^\W_])")

_PADRAO_DATA = re.compile(
    rf"{ANTES}(?:\d{{2}}/\d{{2}}/\d{{4}}|\d{{2}}\.\d{{2}}\.\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}){DEPOIS}"
)

# Tipos cujo valor a chave PIX so toma emprestado. Quando a chave e um desses,
# o detector proprio (CPF com DV, EMAIL, TELEFONE) descreve melhor o dado, e o
# golden set anota assim; CHAVE_PIX sai com confianca menor de proposito, para
# perder a disputa de span e sobrar so na chave aleatoria.
_FORMATOS_EMPRESTADOS = re.compile(rf"(?:{_EMAIL}|{_CPF}|{_TELEFONE})\Z")


class DetectorContextual:
    """Detector cujo padrão só vale acompanhado do rótulo certo."""

    def __init__(
        self, entity_type: EntityType, name: str, padrao: re.Pattern[str]
    ) -> None:
        self.entity_type = entity_type
        self.name = name
        self._padrao = padrao

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.entity_type.name})"

    def _confianca(self, bruto: str) -> float:
        return CONFIANCA_ANCORADA

    def detect(self, texto: str) -> list[Entity]:
        achadas: list[Entity] = []
        for match in self._padrao.finditer(texto):
            ancora = buscar_ancora(texto, match.start(), tipo=self.entity_type)
            if ancora is None:
                continue
            if tem_ancora_negativa(texto, match.start()):
                continue
            achadas.append(
                Entity(
                    type=self.entity_type,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(),
                    confidence=self._confianca(match.group()),
                    detector=self.name,
                    context=ancora,
                )
            )
        return achadas


class _DetectorChavePix(DetectorContextual):
    def _confianca(self, bruto: str) -> float:
        if _FORMATOS_EMPRESTADOS.match(bruto):
            return CONFIANCA_ANCORADA_FRACA
        return CONFIANCA_ANCORADA


detector_rg = DetectorContextual(EntityType.RG, "rg_contextual", _PADRAO_RG)
detector_agencia_conta = DetectorContextual(
    EntityType.AGENCIA_CONTA, "agencia_conta_contextual", _PADRAO_AGENCIA_CONTA
)
detector_chave_pix = _DetectorChavePix(
    EntityType.CHAVE_PIX, "chave_pix_contextual", _PADRAO_CHAVE_PIX
)
detector_cid = DetectorContextual(EntityType.CID, "cid_contextual", _PADRAO_CID)
detector_data_nascimento = DetectorContextual(
    EntityType.DATA_NASCIMENTO, "data_nascimento_contextual", _PADRAO_DATA
)

DETECTORES_CONTEXTUAIS: list[DetectorContextual] = [
    detector_rg,
    detector_agencia_conta,
    detector_chave_pix,
    detector_cid,
    detector_data_nascimento,
]
