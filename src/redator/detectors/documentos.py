"""Detectores de documentos conferidos por dígito verificador.

Cada detector casa um candidato por regex tolerante a pontuação e só devolve a
entidade se o DV fechar. Número que não valida não é documento — não sai nada.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from ..anchors import buscar_ancora, tem_ancora_negativa, tipo_ancorado
from ..entities import Entity, EntityType
from ..validators import (
    is_valid_cnh,
    is_valid_cnpj,
    is_valid_cns,
    is_valid_cpf,
    is_valid_luhn,
    is_valid_pis,
    is_valid_processo_cnj,
    is_valid_titulo_eleitor,
)
from ._fronteiras import ANTES as _ANTES
from ._fronteiras import DEPOIS as _DEPOIS
from ._fronteiras import SO_DIGITOS as _SO_DIGITOS
from ._fronteiras import tolerante as _tolerante

__all__ = [
    "CONFIANCA_AMBIGUA",
    "CONFIANCA_ANCORADA",
    "CONFIANCA_CANONICA",
    "CONFIANCA_IRREGULAR",
    "DETECTORES_DOCUMENTOS",
    "DetectorDocumento",
    "detector_cartao_credito",
    "detector_cnh",
    "detector_cnpj",
    "detector_cns",
    "detector_cpf",
    "detector_pis",
    "detector_processo_cnj",
    "detector_titulo_eleitor",
]

# Rotulo explicito antes do numero: a evidencia mais forte que existe aqui.
CONFIANCA_ANCORADA = 0.99
CONFIANCA_CANONICA = 0.95
CONFIANCA_IRREGULAR = 0.85
# O numero fecha o DV de mais de um tipo e nao ha ancora para desempatar.
CONFIANCA_AMBIGUA = 0.6


def _mascaras(*padroes: str) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(padrao) for padrao in padroes)


# Cartao nao usa a regra tolerante dos demais. O Luhn e fraco — numero curto
# qualquer passa nele com ~10% de chance — entao a forma escrita precisa puxar
# o peso. Aceita so digitos corridos ou o agrupamento real de cartao: quatro
# grupos de quatro, ou o 4-6-5 do Amex, sempre com o MESMO separador. Isso e o
# que impede um CNPJ (46.634.044/0001-74, que por acaso fecha o Luhn) ou um
# telefone com DDI de virar cartao.
_PADRAO_CARTAO = re.compile(
    rf"{_ANTES}(?:"
    rf"\d{{13,19}}"
    rf"|\d{{4}}([ -])\d{{4}}\1\d{{4}}\1\d{{4}}"
    rf"|\d{{4}}([ -])\d{{6}}\2\d{{5}}"
    rf"){_DEPOIS}"
)


@dataclass(frozen=True)
class _Especificacao:
    """Como reconhecer e conferir um tipo de documento."""

    entity_type: EntityType
    name: str
    validador: Callable[[str], bool]
    comprimentos: frozenset[int]
    padrao: re.Pattern[str]
    canonicas: tuple[re.Pattern[str], ...]


_ESPECIFICACOES: tuple[_Especificacao, ...] = (
    _Especificacao(
        EntityType.CPF,
        "cpf_dv",
        is_valid_cpf,
        frozenset({11}),
        _tolerante(11),
        _mascaras(r"\d{3}\.\d{3}\.\d{3}-\d{2}", r"\d{11}"),
    ),
    _Especificacao(
        EntityType.CNPJ,
        "cnpj_dv",
        is_valid_cnpj,
        frozenset({14}),
        _tolerante(14),
        _mascaras(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}", r"\d{14}"),
    ),
    _Especificacao(
        EntityType.PIS,
        "pis_dv",
        is_valid_pis,
        frozenset({11}),
        _tolerante(11),
        _mascaras(r"\d{3}\.\d{5}\.\d{2}-\d", r"\d{11}"),
    ),
    _Especificacao(
        EntityType.CNH,
        "cnh_dv",
        is_valid_cnh,
        frozenset({11}),
        _tolerante(11),
        _mascaras(r"\d{11}"),
    ),
    _Especificacao(
        EntityType.TITULO_ELEITOR,
        "titulo_eleitor_dv",
        is_valid_titulo_eleitor,
        frozenset({12}),
        _tolerante(12),
        _mascaras(r"\d{4} \d{4} \d{4}", r"\d{12}"),
    ),
    _Especificacao(
        EntityType.CNS,
        "cns_dv",
        is_valid_cns,
        frozenset({15}),
        _tolerante(15),
        _mascaras(r"\d{3} \d{4} \d{4} \d{4}", r"\d{15}"),
    ),
    _Especificacao(
        EntityType.PROCESSO_CNJ,
        "processo_cnj_dv",
        is_valid_processo_cnj,
        frozenset({20}),
        _tolerante(20),
        _mascaras(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", r"\d{20}"),
    ),
    _Especificacao(
        EntityType.CARTAO_CREDITO,
        "cartao_credito_luhn",
        is_valid_luhn,
        frozenset(range(13, 20)),
        _PADRAO_CARTAO,
        _mascaras(r"\d{4} \d{4} \d{4} \d{4}", r"\d{13,19}"),
    ),
)


def _tipos_que_validam(bruto: str, digitos: str) -> set[EntityType]:
    """Tipos que reconheceriam ESTE literal e cujo DV fecha.

    Exige que o padrão do outro tipo também case o texto como escrito, não só
    que o comprimento e o DV batam. Sem isso um CNPJ seria "ambíguo" com cartão
    — 46634044000174 fecha o Luhn —, mesmo o detector de cartão jamais casando
    um literal com pontos e barra.
    """
    return {
        especificacao.entity_type
        for especificacao in _ESPECIFICACOES
        if len(digitos) in especificacao.comprimentos
        and especificacao.padrao.fullmatch(bruto)
        and especificacao.validador(digitos)
    }


class DetectorDocumento:
    """Detector de um tipo de documento conferido por DV.

    Os offsets devolvidos são do texto que o detector recebeu — o normalizado,
    quando chamado pelo pipeline.
    """

    def __init__(self, especificacao: _Especificacao) -> None:
        self._especificacao = especificacao
        self.name = especificacao.name
        self.entity_type = especificacao.entity_type

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.entity_type.name})"

    def _formato_canonico(self, bruto: str) -> bool:
        return any(m.fullmatch(bruto) for m in self._especificacao.canonicas)

    def detect(self, texto: str) -> list[Entity]:
        especificacao = self._especificacao
        meu_tipo = especificacao.entity_type
        achadas: list[Entity] = []

        for match in especificacao.padrao.finditer(texto):
            bruto = match.group()
            digitos = _SO_DIGITOS.sub("", bruto)
            if len(digitos) not in especificacao.comprimentos:
                continue
            if not especificacao.validador(digitos):
                continue

            ancora = buscar_ancora(texto, match.start(), tipo=meu_tipo)
            # Rotulo administrativo manda mais que o DV: numero de serie nao
            # vira CPF so porque o modulo 11 fecha. A ancora do proprio tipo,
            # quando existe, cancela a supressao.
            if ancora is None and tem_ancora_negativa(texto, match.start()):
                continue

            tipos = _tipos_que_validam(bruto, digitos)
            if len(tipos) > 1:
                escolhido = tipo_ancorado(texto, match.start(), tipos=tipos)
                if escolhido is not None and escolhido[0] is not meu_tipo:
                    # Outro tipo tem o rotulo: este aqui nem se candidata.
                    continue
                confianca = (
                    CONFIANCA_ANCORADA if escolhido is not None else CONFIANCA_AMBIGUA
                )
            elif ancora is not None:
                confianca = CONFIANCA_ANCORADA
            elif self._formato_canonico(bruto):
                confianca = CONFIANCA_CANONICA
            else:
                confianca = CONFIANCA_IRREGULAR

            achadas.append(
                Entity(
                    type=meu_tipo,
                    start=match.start(),
                    end=match.end(),
                    text=bruto,
                    confidence=confianca,
                    detector=especificacao.name,
                    validated=True,
                    context=ancora,
                )
            )
        return achadas


def _por_tipo(entity_type: EntityType) -> DetectorDocumento:
    for especificacao in _ESPECIFICACOES:
        if especificacao.entity_type is entity_type:
            return DetectorDocumento(especificacao)
    raise KeyError(entity_type)


detector_cpf = _por_tipo(EntityType.CPF)
detector_cnpj = _por_tipo(EntityType.CNPJ)
detector_pis = _por_tipo(EntityType.PIS)
detector_cnh = _por_tipo(EntityType.CNH)
detector_titulo_eleitor = _por_tipo(EntityType.TITULO_ELEITOR)
detector_cns = _por_tipo(EntityType.CNS)
detector_processo_cnj = _por_tipo(EntityType.PROCESSO_CNJ)
detector_cartao_credito = _por_tipo(EntityType.CARTAO_CREDITO)

DETECTORES_DOCUMENTOS: list[DetectorDocumento] = [
    detector_cpf,
    detector_cnpj,
    detector_pis,
    detector_cnh,
    detector_titulo_eleitor,
    detector_cns,
    detector_processo_cnj,
    detector_cartao_credito,
]
