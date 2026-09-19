"""Detectores de dados de contato: e-mail, telefone, CEP e CPF mascarado.

Aqui não há dígito verificador para confirmar nada. O que sustenta a detecção é
a forma do valor, e a âncora, quando existe, eleva a confiança.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ..anchors import buscar_ancora, contexto_de_endereco, tem_ancora_negativa
from ..entities import Entity, EntityType
from ._fronteiras import ANTES, DEPOIS

__all__ = [
    "CONFIANCA_ANCORADA",
    "CONFIANCA_FRACA",
    "CONFIANCA_OCR_AMBIGUA",
    "CONFIANCA_PADRAO",
    "DDDS_VALIDOS",
    "DETECTORES_CONTATO",
    "detector_cep",
    "detector_cpf_mascarado",
    "detector_email",
    "detector_email_ocr_ambiguo",
    "detector_telefone",
]

CONFIANCA_ANCORADA = 0.99
CONFIANCA_PADRAO = 0.9
# Leitura resgatada de texto corrompido por OCR: nunca vale mais que isto.
CONFIANCA_OCR_AMBIGUA = 0.5
# Padrao generico demais para sustentar sozinho: so com rotulo ou vizinhanca.
CONFIANCA_FRACA = 0.5

# DDDs em uso no Brasil. Os buracos (20, 23, 25, 26, 29, 30, 36, 39, 40, 50,
# 52, 56-60, 70, 72, 76, 78, 80, 90) nunca foram atribuidos, e e justamente
# isso que derruba um CPF lido como telefone: 52998224725 comecaria em DDD 52.
DDDS_VALIDOS = frozenset(
    [11, 12, 13, 14, 15, 16, 17, 18, 19]
    + [21, 22, 24, 27, 28]
    + [31, 32, 33, 34, 35, 37, 38]
    + [41, 42, 43, 44, 45, 46, 47, 48, 49]
    + [51, 53, 54, 55]
    + [61, 62, 63, 64, 65, 66, 67, 68, 69]
    + [71, 73, 74, 75, 77, 79]
    + [81, 82, 83, 84, 85, 86, 87, 88, 89]
    + [91, 92, 93, 94, 95, 96, 97, 98, 99]
)

_PADRAO_EMAIL = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?![\w-])"
)

# As cinco variantes de doc_teste_1_cpf_irregular.txt, mais o fixo do oficio:
#   (15) 99842-7316 / 15 99842 7316 / 15998427316
#   +55 15 99842-7316 / +55 (15) 99842 7316 / (15) 3238-0000
_PADRAO_TELEFONE = re.compile(
    r"(?<![^\W_])"
    r"(?:\+\s?55[\s.-]?)?"
    r"(?:\((\d{2})\)|(\d{2}))"
    r"[\s.-]?(\d{4,5})[\s.-]?(\d{4})"
    rf"{DEPOIS}"
)

_PADRAO_CEP = re.compile(rf"{ANTES}\d{{5}}-?\d{{3}}{DEPOIS}")

# O mesmo padrao de e-mail, mas exigindo "&" onde deveria haver "@". O
# Tesseract le o arroba como "&" (as vezes engolindo um caractere antes,
# "G&"), e a confianca do OCR nao protege disso: numa das variantes medidas a
# palavra corrompida saiu com 61, ACIMA do limiar de 60, entao nem entrou em
# low_confidence_words. Sem esta passagem o e-mail some por inteiro — nem
# detectado, nem sinalizado —, que e a pior falha possivel para uma
# ferramenta que prioriza recall.
_PADRAO_EMAIL_OCR = re.compile(
    r"(?<![\w.+-])[A-Za-z0-9._%+-]+&[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+(?![\w-])"
)
#: Vai no ``context`` da entidade, para quem revisa entender por que a
#: confianca e baixa: nao foi o rotulo que faltou, foi o caractere que o OCR
#: trocou.
CONTEXTO_EMAIL_OCR = "email_ocr_ambiguo"

# Grupo de CPF escrito por extenso, mascarado ou nao.
_GRUPO3 = r"(?:\d{3}|\*{3}|[Xx]{3})"
_GRUPO2 = r"(?:\d{2}|\*{2}|[Xx]{2})"
_PADRAO_CPF_MASCARADO = re.compile(
    rf"{ANTES}{_GRUPO3}\.{_GRUPO3}\.{_GRUPO3}-{_GRUPO2}{DEPOIS}"
)
_TEM_MASCARA = re.compile(r"[*Xx]")


def _telefone_plausivel(match: re.Match[str]) -> bool:
    """DDD atribuído, e o assinante com a forma certa para o comprimento.

    Celular tem nove dígitos e começa em 9; fixo tem oito e começa entre 2 e 5.
    Sem essas duas regras, um CPF de DDD válido passaria: 11144477735 daria
    DDD 11 e assinante 144477735, que não é telefone de ninguém.
    """
    ddd = match.group(1) or match.group(2)
    if int(ddd) not in DDDS_VALIDOS:
        return False
    assinante = f"{match.group(3)}{match.group(4)}"
    if len(assinante) == 9:
        return assinante[0] == "9"
    return assinante[0] in "2345"


class _DetectorPadrao:
    """Detector de padrão sem DV, com a âncora apenas elevando a confiança."""

    def __init__(
        self,
        entity_type: EntityType,
        name: str,
        padrao: re.Pattern[str],
    ) -> None:
        self.entity_type = entity_type
        self.name = name
        self._padrao = padrao

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.entity_type.name})"

    def _aceita(self, match: re.Match[str]) -> bool:
        return True

    def _confianca(self, texto: str, match: re.Match[str], ancora: str | None) -> float:
        return CONFIANCA_ANCORADA if ancora else CONFIANCA_PADRAO

    def detect(self, texto: str) -> list[Entity]:
        achadas: list[Entity] = []
        for match in self._padrao.finditer(texto):
            if not self._aceita(match):
                continue
            ancora = buscar_ancora(texto, match.start(), tipo=self.entity_type)
            if ancora is None and tem_ancora_negativa(texto, match.start()):
                continue
            achadas.append(
                Entity(
                    type=self.entity_type,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(),
                    confidence=self._confianca(texto, match, ancora),
                    detector=self.name,
                    context=ancora,
                )
            )
        return achadas


class _DetectorTelefone(_DetectorPadrao):
    def _aceita(self, match: re.Match[str]) -> bool:
        return _telefone_plausivel(match)


class _DetectorCep(_DetectorPadrao):
    """CEP é o padrão mais frágil: oito dígitos quaisquer têm essa cara.

    Com rótulo ``CEP`` vale o máximo; cercado de logradouro, bairro ou sede
    vale o normal; sozinho no meio do texto sai com confiança fraca e marcado
    para revisão.
    """

    def _confianca(self, texto: str, match: re.Match[str], ancora: str | None) -> float:
        if ancora:
            return CONFIANCA_ANCORADA
        if contexto_de_endereco(texto, match.start()):
            return CONFIANCA_PADRAO
        return CONFIANCA_FRACA

    def detect(self, texto: str) -> list[Entity]:
        return [
            entidade
            if entidade.confidence > CONFIANCA_FRACA
            else Entity(
                type=entidade.type,
                start=entidade.start,
                end=entidade.end,
                text=entidade.text,
                confidence=entidade.confidence,
                detector=entidade.detector,
                context=entidade.context,
                requires_review=True,
            )
            for entidade in super().detect(texto)
        ]


class _DetectorCpfMascarado(_DetectorPadrao):
    """CPF que já chegou mascarado no documento original.

    Toda ocorrência sai com ``requires_review=True``, sem exceção: a redação
    (``redator.redacao``) não aplica tarja automática sobre um valor já
    parcialmente oculto — o padrão DOU não tem como ser reforçado de forma
    consistente sobre um texto que já veio com pontas ou meio faltando. Quem
    revisa decide se aceita como está ou marca uma tarja manual por cima.
    """

    def _aceita(self, match: re.Match[str]) -> bool:
        # Sem nenhum grupo oculto e um CPF comum, que tem detector proprio.
        return bool(_TEM_MASCARA.search(match.group()))

    def detect(self, texto: str) -> list[Entity]:
        return [replace(entidade, requires_review=True) for entidade in super().detect(texto)]


class _DetectorEmailOcrAmbiguo:
    """E-mail cujo ``@`` o OCR trocou por ``&``. So roda sobre texto de OCR.

    Nunca disputa com o detector estrito: um exige ``&`` onde o outro exige
    ``@``, entao os dois jamais casam o mesmo trecho. E resgate, nao
    alternativa — por isso e aditivo e nao altera nada do caminho nativo.

    Toda entidade daqui sai com ``CONFIANCA_OCR_AMBIGUA`` e
    ``requires_review=True``, sem excecao e independentemente da confianca
    que o OCR deu a palavra: se um caractere ja veio trocado, os outros
    podem ter vindo tambem, e isso o padrao nao tem como ver.
    """

    entity_type = EntityType.EMAIL
    name = CONTEXTO_EMAIL_OCR

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.entity_type.name})"

    def detect(self, texto: str) -> list[Entity]:
        achadas: list[Entity] = []
        for match in _PADRAO_EMAIL_OCR.finditer(texto):
            if tem_ancora_negativa(texto, match.start()):
                continue
            achadas.append(
                Entity(
                    type=self.entity_type,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(),
                    confidence=CONFIANCA_OCR_AMBIGUA,
                    detector=self.name,
                    context=CONTEXTO_EMAIL_OCR,
                    requires_review=True,
                )
            )
        return achadas


detector_email = _DetectorPadrao(EntityType.EMAIL, "email_padrao", _PADRAO_EMAIL)
detector_email_ocr_ambiguo = _DetectorEmailOcrAmbiguo()
detector_telefone = _DetectorTelefone(
    EntityType.TELEFONE, "telefone_padrao", _PADRAO_TELEFONE
)
detector_cep = _DetectorCep(EntityType.CEP, "cep_padrao", _PADRAO_CEP)
detector_cpf_mascarado = _DetectorCpfMascarado(
    EntityType.CPF_MASCARADO, "cpf_mascarado_padrao", _PADRAO_CPF_MASCARADO
)

DETECTORES_CONTATO: list[_DetectorPadrao] = [
    detector_email,
    detector_telefone,
    detector_cep,
    detector_cpf_mascarado,
]
