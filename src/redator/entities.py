"""Modelo de entidades detectáveis e seus metadados legais."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "ENTITY_METADATA",
    "DetectionMethod",
    "Entity",
    "EntityMetadata",
    "EntityType",
    "LegalCategory",
]


class LegalCategory(Enum):
    """Enquadramento legal do dado, que rege a política de tarja."""

    PESSOAL = "pessoal"
    SENSIVEL = "sensivel"
    PESSOA_JURIDICA = "pessoa_juridica"
    PUBLICO_OBRIGATORIO = "publico_obrigatorio"


class DetectionMethod(Enum):
    """Técnica esperada para localizar o dado no texto."""

    VALIDADO_DV = "validado_dv"
    PADRAO = "padrao"
    CONTEXTUAL = "contextual"
    NER = "ner"
    SEMANTICO = "semantico"
    VISUAL = "visual"


class EntityType(Enum):
    """Tipos de dado que a ferramenta reconhece."""

    CPF = "cpf"
    CPF_MASCARADO = "cpf_mascarado"
    CNPJ = "cnpj"
    RG = "rg"
    PIS = "pis"
    CNH = "cnh"
    TITULO_ELEITOR = "titulo_eleitor"
    CNS = "cns"
    PROCESSO_CNJ = "processo_cnj"
    CARTAO_CREDITO = "cartao_credito"
    EMAIL = "email"
    TELEFONE = "telefone"
    CEP = "cep"
    DATA_NASCIMENTO = "data_nascimento"
    AGENCIA_CONTA = "agencia_conta"
    CHAVE_PIX = "chave_pix"
    CID = "cid"
    NOME = "nome"
    ENDERECO = "endereco"

    @property
    def metadata(self) -> EntityMetadata:
        return ENTITY_METADATA[self]

    @property
    def categoria(self) -> LegalCategory:
        return ENTITY_METADATA[self].categoria

    @property
    def metodo(self) -> DetectionMethod:
        return ENTITY_METADATA[self].metodo


@dataclass(frozen=True, slots=True)
class EntityMetadata:
    """Os dois eixos que classificam um :class:`EntityType`."""

    categoria: LegalCategory
    metodo: DetectionMethod


ENTITY_METADATA: dict[EntityType, EntityMetadata] = {
    EntityType.CPF: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV),
    EntityType.CPF_MASCARADO: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.PADRAO
    ),
    EntityType.CNPJ: EntityMetadata(
        LegalCategory.PESSOA_JURIDICA, DetectionMethod.VALIDADO_DV
    ),
    EntityType.RG: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.CONTEXTUAL),
    EntityType.PIS: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV),
    EntityType.CNH: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV),
    EntityType.TITULO_ELEITOR: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV
    ),
    EntityType.CNS: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV),
    EntityType.PROCESSO_CNJ: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV
    ),
    EntityType.CARTAO_CREDITO: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.VALIDADO_DV
    ),
    EntityType.EMAIL: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.PADRAO),
    EntityType.TELEFONE: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.PADRAO),
    EntityType.CEP: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.PADRAO),
    EntityType.DATA_NASCIMENTO: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.CONTEXTUAL
    ),
    EntityType.AGENCIA_CONTA: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.CONTEXTUAL
    ),
    EntityType.CHAVE_PIX: EntityMetadata(
        LegalCategory.PESSOAL, DetectionMethod.CONTEXTUAL
    ),
    EntityType.CID: EntityMetadata(LegalCategory.SENSIVEL, DetectionMethod.CONTEXTUAL),
    EntityType.NOME: EntityMetadata(
        LegalCategory.PUBLICO_OBRIGATORIO, DetectionMethod.NER
    ),
    EntityType.ENDERECO: EntityMetadata(LegalCategory.PESSOAL, DetectionMethod.NER),
}


@dataclass(frozen=True, slots=True)
class Entity:
    """Uma ocorrência localizada no texto normalizado."""

    type: EntityType
    start: int
    end: int
    text: str
    confidence: float
    detector: str
    validated: bool = False
    context: str | None = None
    requires_review: bool = False

    def __post_init__(self) -> None:
        if self.start < 0:
            raise ValueError(f"start deve ser >= 0, recebido {self.start}")
        if self.end <= self.start:
            raise ValueError(
                f"end ({self.end}) deve ser maior que start ({self.start})"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence deve estar entre 0.0 e 1.0, recebido {self.confidence}"
            )

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def span(self) -> tuple[int, int]:
        return (self.start, self.end)

    def overlaps(self, other: Entity) -> bool:
        """Interseção de intervalos; adjacência (end == start) não conta."""
        return self.start < other.end and other.start < self.end

    def contains(self, other: Entity) -> bool:
        """``other`` cabe inteiro dentro de ``self``.

        Contenção é estrita: spans idênticos não contam, porque entidades sobre
        exatamente o mesmo trecho disputam a precedência em vez de aninhar.
        """
        return (
            self.start <= other.start
            and other.end <= self.end
            and self.span != other.span
        )

    def partially_overlaps(self, other: Entity) -> bool:
        """Interseção verdadeira que não é contenção nem span idêntico.

        Só este caso — dois trechos que se cruzam sem que um caiba no outro —
        dispara a regra de precedência em :func:`redator.overlap.resolve_overlaps`.
        """
        return (
            self.overlaps(other)
            and not self.contains(other)
            and not other.contains(self)
            and self.span != other.span
        )
