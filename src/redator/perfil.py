"""Perfil de redação: o que fazer com cada entidade detectada.

A detecção responde "o que é isto e onde está". O perfil responde a outra
pergunta — "isto sai tarjado ou publicado?" — e as duas ficam separadas de
propósito: um CNPJ é detectado com a mesma certeza de um CPF, mas não é dado
pessoal, e tarjá-lo esconderia informação que a transparência exige.

**Hoje a decisão é só por tipo.** Não existe distinção entre dado
institucional e pessoal: o telefone da própria fundação no cabeçalho de um
ofício sai tarjado exatamente como o celular de um cidadão. Não é descuido — é
que a ``Entity`` não carrega nenhum sinal que sustente essa distinção. O
motivo, e o caminho para resolvê-lo, estão em ``DECISOES.md`` (Fase 3b).

**Onde a sobreposição futura entra.** Toda decisão passa por
:func:`decidir_acao`, que recebe só a ``Entity``. Quando houver um sinal real
de contexto institucional, ele será um campo da própria ``Entity`` — como
``origem_ocr`` é campo da página, e não parâmetro do chamador, para não haver
como esquecer de passá-lo —, e a regra que o consulta entra dentro desta
função, antes da consulta ao perfil. A assinatura não muda, e nenhum chamador
precisa saber que a regra existe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .entities import Entity, EntityType

__all__ = [
    "PERFIL_PADRAO",
    "AcaoRedacao",
    "EntidadeComAcao",
    "aplicar_perfil",
    "decidir_acao",
]


class AcaoRedacao(Enum):
    """O destino de uma entidade no documento publicado."""

    TARJAR = "tarjar"
    PUBLICAR = "publicar"


#: A ação por tipo. Todo ``EntityType`` precisa estar aqui — ``tests/
#: test_perfil.py`` falha se o enum crescer e este dict não acompanhar.
#:
#: As três exceções ao TARJAR, e por quê:
#:
#: - ``CNPJ``: identifica pessoa jurídica, não pessoa natural. Fora da LGPD.
#: - ``PROCESSO_CNJ``: o número de processo é público por natureza, e é o que
#:   permite a quem lê o documento localizar o processo.
#: - ``NOME``: em ato administrativo, o nome de quem assina ou é parte é
#:   publicidade obrigatória. (Ainda não há detector de NOME; a entrada existe
#:   para o perfil já estar certo quando houver.)
PERFIL_PADRAO: dict[EntityType, AcaoRedacao] = {
    EntityType.CPF: AcaoRedacao.TARJAR,
    EntityType.CPF_MASCARADO: AcaoRedacao.TARJAR,
    EntityType.CNPJ: AcaoRedacao.PUBLICAR,
    EntityType.RG: AcaoRedacao.TARJAR,
    EntityType.PIS: AcaoRedacao.TARJAR,
    EntityType.CNH: AcaoRedacao.TARJAR,
    EntityType.TITULO_ELEITOR: AcaoRedacao.TARJAR,
    EntityType.CNS: AcaoRedacao.TARJAR,
    EntityType.PROCESSO_CNJ: AcaoRedacao.PUBLICAR,
    EntityType.CARTAO_CREDITO: AcaoRedacao.TARJAR,
    EntityType.EMAIL: AcaoRedacao.TARJAR,
    EntityType.TELEFONE: AcaoRedacao.TARJAR,
    EntityType.CEP: AcaoRedacao.TARJAR,
    EntityType.DATA_NASCIMENTO: AcaoRedacao.TARJAR,
    EntityType.AGENCIA_CONTA: AcaoRedacao.TARJAR,
    EntityType.CHAVE_PIX: AcaoRedacao.TARJAR,
    EntityType.CID: AcaoRedacao.TARJAR,
    EntityType.NOME: AcaoRedacao.PUBLICAR,
    EntityType.ENDERECO: AcaoRedacao.TARJAR,
}


@dataclass(frozen=True, slots=True)
class EntidadeComAcao:
    """Uma entidade e o que o perfil decidiu fazer com ela.

    A ``Entity`` vai inteira e intocada — ``requires_review``, ``context``,
    confiança. A ação é uma decisão SOBRE a entidade, não uma reescrita dela:
    quem revisa ainda precisa saber que um RG de OCR é frágil, mesmo que ele
    vá ser tarjado de qualquer jeito.
    """

    entity: Entity
    acao: AcaoRedacao


def decidir_acao(entity: Entity) -> AcaoRedacao:
    """A ação para esta entidade. Hoje, só pelo tipo.

    Um tipo sem entrada no perfil é erro, não default. Cair em PUBLICAR
    vazaria dado; cair em TARJAR em silêncio esconderia que alguém criou um
    tipo sem decidir a política dele — e essa decisão é jurídica, não de
    código.
    """
    try:
        return PERFIL_PADRAO[entity.type]
    except KeyError:
        raise KeyError(
            f"{entity.type.name} nao tem acao em PERFIL_PADRAO — "
            f"todo EntityType precisa de uma decisao explicita"
        ) from None


def aplicar_perfil(entidades: list[Entity]) -> list[EntidadeComAcao]:
    """Decide a ação de cada entidade, preservando a ordem de entrada."""
    return [EntidadeComAcao(entity=e, acao=decidir_acao(e)) for e in entidades]
