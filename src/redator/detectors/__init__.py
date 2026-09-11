"""Detectores de entidades."""

from ..entities import EntityType
from .base import Detector
from .contato import DETECTORES_CONTATO, detector_email_ocr_ambiguo
from .contextual import DETECTORES_CONTEXTUAIS
from .documentos import DETECTORES_DOCUMENTOS, DetectorDocumento

#: Todos os detectores implementados, na ordem em que foram construidos.
TODOS_DETECTORES: list[Detector] = [
    *DETECTORES_DOCUMENTOS,
    *DETECTORES_CONTATO,
    *DETECTORES_CONTEXTUAIS,
]

#: Detectores que so fazem sentido sobre texto vindo de OCR, somados aos
#: demais quando a origem e OCR. Sao aditivos: resgatam o que a degradacao de
#: leitura quebrou, sem nunca disputar trecho com os detectores normais.
DETECTORES_SO_OCR: list[Detector] = [detector_email_ocr_ambiguo]

#: Tipos sem digito verificador cuja FORMA quebra facilmente com ruido de
#: imagem — um espaco a mais, um caractere trocado, e o padrao nao casa. Em
#: texto de OCR eles saem sempre marcados para revisao, mesmo com casamento
#: limpo e ancora: a marca diz "este tipo e fragil nesta origem", nao "esta
#: deteccao e duvidosa". CPF e CNPJ ficam de fora porque o digito verificador
#: e a rede de seguranca que o RG nao tem.
TIPOS_FRAGEIS_EM_OCR: frozenset[EntityType] = frozenset({EntityType.RG})

__all__ = [
    "DETECTORES_CONTATO",
    "DETECTORES_CONTEXTUAIS",
    "DETECTORES_DOCUMENTOS",
    "DETECTORES_SO_OCR",
    "TIPOS_FRAGEIS_EM_OCR",
    "TODOS_DETECTORES",
    "Detector",
    "DetectorDocumento",
]
