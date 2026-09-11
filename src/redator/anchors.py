"""Âncoras de contexto: o rótulo que vem antes do candidato.

Dígito verificador diz que o número é bem-formado, não que ele é dado pessoal.
``52998224725`` fecha o DV de CPF tanto sob ``CPF nº`` quanto sob ``Número de
série``. Quem separa os dois é o rótulo imediatamente anterior.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from .entities import EntityType

__all__ = [
    "ANCORAS_NEGATIVAS",
    "ANCORAS_POSITIVAS",
    "JANELA_ENDERECO",
    "JANELA_PADRAO",
    "buscar_ancora",
    "contexto_de_endereco",
    "tem_ancora_negativa",
    "tipo_ancorado",
]

# Rotulo de tipo e pontual: vem colado no candidato, so separado por ruido
# de pontuacao. Quarenta caracteres bastam e evitam alcance indevido.
JANELA_PADRAO = 40
# Contexto de endereco e difuso: logradouro, numero, complemento e bairro se
# espalham pela frase inteira antes do CEP. Em "Avenida Empresarial, nº 1250,
# sala 84, Parque Tecnológico, Sorocaba/SP, 18087-150" o complemento mais
# proximo ja esta a 42 caracteres do CEP.
JANELA_ENDERECO = 120

ANCORAS_POSITIVAS: dict[EntityType, list[str]] = {
    EntityType.CPF: [
        "CPF",
        "C.P.F.",
        "CPF nº",
        "inscrito no CPF",
        "inscrita no CPF",
        "portador do CPF",
        "portadora do CPF",
        "CPF do titular",
    ],
    EntityType.CPF_MASCARADO: ["CPF", "C.P.F.", "CPF mascarado"],
    EntityType.CNPJ: [
        "CNPJ",
        "C.N.P.J.",
        "CNPJ nº",
        "inscrito no CNPJ",
        "inscrita no CNPJ",
        "CNPJ da contratada",
    ],
    EntityType.RG: [
        "RG",
        "R.G.",
        "RG nº",
        "Cédula de Identidade",
        "Identidade nº",
        "documento de identidade",
        "carteira de identidade",
        "registro geral",
    ],
    EntityType.PIS: ["PIS", "PASEP", "PIS/PASEP", "NIT", "PIS/PASEP/NIT"],
    EntityType.CNH: [
        "CNH",
        "Registro CNH",
        "carteira de habilitação",
        "carteira nacional de habilitação",
        "habilitação",
    ],
    EntityType.TITULO_ELEITOR: [
        "Título de Eleitor",
        "título eleitoral",
        "título eleitor",
        "inscrição eleitoral",
    ],
    EntityType.CNS: [
        "CNS",
        "Cartão Nacional de Saúde",
        "cartão SUS",
        "cartão do SUS",
    ],
    EntityType.PROCESSO_CNJ: [
        "processo",
        "processo judicial",
        "autos",
        "autos nº",
        "número único",
    ],
    # "cartão" sozinho fica de fora de proposito: ele casaria "Cartão Nacional
    # de Saúde" e daria ancora de cartao de credito a um CNS.
    EntityType.CARTAO_CREDITO: [
        "cartão de crédito",
        "cartão de débito",
        "nº do cartão",
        "número do cartão",
    ],
    EntityType.EMAIL: [
        "e-mail",
        "email",
        "endereço eletrônico",
        "correio eletrônico",
    ],
    EntityType.TELEFONE: [
        "telefone",
        "tel.",
        "tel",
        "fone",
        "celular",
        "whatsapp",
        "contato",
    ],
    # "código postal" fica de fora: "código" e ancora negativa, e a sobreposicao
    # so geraria disputa entre as duas listas.
    EntityType.CEP: ["CEP"],
    EntityType.DATA_NASCIMENTO: [
        "data de nascimento",
        "nascido em",
        "nascida em",
        "nasc.",
        "nascimento",
    ],
    EntityType.AGENCIA_CONTA: [
        "agência",
        "ag.",
        "conta",
        "conta corrente",
        "conta poupança",
        "c/c",
    ],
    EntityType.CHAVE_PIX: ["chave PIX", "PIX"],
    EntityType.CID: ["CID", "CID-10", "CID 10", "diagnóstico"],
    EntityType.NOME: ["nome", "razão social", "favorecido", "favorecida"],
    EntityType.ENDERECO: [
        "endereço",
        "residente",
        "domiciliado",
        "domiciliada",
        "estabelecido",
        "estabelecida",
        "sede",
    ],
}

# Rotulos administrativos: o que vem depois deles nao e dado pessoal.
ANCORAS_NEGATIVAS: list[str] = [
    "código",
    "código interno",
    "código patrimonial",
    "código de rastreamento",
    "código de verificação",
    "código verificador",
    "número de série",
    "total de registros",
    "identificador",
    "identificador do lote",
    "chave de integração",
    "protocolo",
    "nota de empenho",
    "empenho",
    "processo",
    "lote",
    "item",
    "ficha",
    "ficha orçamentária",
    "dotação",
    "dotação orçamentária",
    "versão",
    "build",
]

# Palavras que indicam que estamos no meio de um endereco. Servem ao CEP, que
# sem ancora nem vizinhanca de endereco e um palpite fraco.
_CONTEXTO_ENDERECO: list[str] = [
    # logradouro
    "rua",
    "avenida",
    "av.",
    "alameda",
    "travessa",
    "praça",
    "rodovia",
    "estrada",
    "largo",
    # complemento
    "sala",
    "bloco",
    "apartamento",
    "apto",
    "andar",
    "conjunto",
    "casa",
    "lote",
    "quadra",
    # area
    "bairro",
    "jardim",
    "parque",
    "vila",
    "distrito",
    "centro",
    "residencial",
    # verbos e rotulos que introduzem endereco
    "endereço",
    "residente",
    "domiciliado",
    "domiciliada",
    "estabelecido",
    "estabelecida",
    "sede",
    "com sede",
]

# Sinal estrutural, nao lexical: "Sorocaba/SP," logo antes do candidato. Uma
# sigla de duas letras colada a barra, depois de um nome proprio, e evidencia
# de endereco sem depender de vocabulario — pega cidade que nao esta em lista
# nenhuma. So conta se nada alem de pontuacao a separar do candidato.
_CIDADE_UF = re.compile(r"[A-ZÁ-Ú][a-zá-ú]+/[A-Z]{2}[\s,.;:-]*$")

_LETRA_OU_DIGITO = r"[^\W_]"


def _compilar(rotulos: Iterable[str]) -> re.Pattern[str]:
    """Uma alternativa por rótulo, do mais longo para o mais curto.

    As guardas nas pontas impedem casar pedaço de palavra — ``item`` não pode
    sair de dentro de ``itemizado``.
    """
    alternativas = "|".join(
        re.escape(rotulo) for rotulo in sorted(set(rotulos), key=len, reverse=True)
    )
    return re.compile(
        rf"(?<!{_LETRA_OU_DIGITO})(?:{alternativas})(?!{_LETRA_OU_DIGITO})",
        re.IGNORECASE,
    )


_PADRAO_POSITIVO: dict[EntityType, re.Pattern[str]] = {
    tipo: _compilar(rotulos) for tipo, rotulos in ANCORAS_POSITIVAS.items()
}
_PADRAO_NEGATIVO = _compilar(ANCORAS_NEGATIVAS)
_PADRAO_ENDERECO = _compilar(_CONTEXTO_ENDERECO)


def _janela_de_busca(texto: str, start: int, janela: int) -> str:
    """O trecho onde faz sentido procurar o rótulo do candidato.

    É a linha do candidato até ele. Se o candidato abre a linha — caso de
    ``RG:\\n42.815.739-6`` —, usa a linha anterior, desde que ela não esteja em
    branco: linha em branco é quebra de parágrafo e a janela não a atravessa.

    Prender a busca à linha é o que impede um rótulo distante de contaminar o
    candidato. Numa tabela ``NOME;CPF;LOTE;VALOR`` seguida das linhas de dados,
    uma janela puramente por caracteres alcançaria o ``LOTE`` do cabeçalho e
    mataria todos os CPFs da tabela como se fossem número de lote.
    """
    inicio_linha = texto.rfind("\n", 0, start) + 1
    prefixo = texto[inicio_linha:start]
    if prefixo.strip():
        return prefixo[-janela:]

    fim_anterior = inicio_linha - 1
    if fim_anterior <= 0:
        return prefixo[-janela:]
    inicio_anterior = texto.rfind("\n", 0, fim_anterior) + 1
    anterior = texto[inicio_anterior:fim_anterior].rstrip("\r")
    if not anterior.strip():
        return prefixo[-janela:]
    return f"{anterior}{prefixo}"[-janela:]


def _ultima(padrao: re.Pattern[str], trecho: str) -> re.Match[str] | None:
    """O match mais à direita — o rótulo mais próximo do candidato."""
    ultima = None
    for match in padrao.finditer(trecho):
        ultima = match
    return ultima


def buscar_ancora(
    texto: str,
    start: int,
    janela: int = JANELA_PADRAO,
    *,
    tipo: EntityType | None = None,
) -> str | None:
    """Rótulo âncora imediatamente antes do candidato em ``start``.

    Com ``tipo``, procura só os rótulos daquele tipo. Sem ``tipo``, procura os
    de todos e devolve o mais próximo do candidato. Devolve o rótulo como está
    escrito no texto, ou ``None``.
    """
    trecho = _janela_de_busca(texto, start, janela)
    if not trecho:
        return None
    if tipo is not None:
        match = _ultima(_PADRAO_POSITIVO[tipo], trecho)
        return match.group() if match else None
    encontrado = tipo_ancorado(texto, start, janela)
    return None if encontrado is None else encontrado[1]


def tipo_ancorado(
    texto: str,
    start: int,
    janela: int = JANELA_PADRAO,
    tipos: Iterable[EntityType] | None = None,
) -> tuple[EntityType, str] | None:
    """Qual tipo o rótulo mais próximo indica, e qual rótulo é esse.

    ``tipos`` restringe a disputa — é assim que a colisão CNH×PIS se resolve:
    passando os dois tipos que o DV aceitou e deixando a âncora escolher. Em
    empate de posição vence o rótulo mais longo, que é o mais específico.
    """
    trecho = _janela_de_busca(texto, start, janela)
    if not trecho:
        return None
    candidatos = list(_PADRAO_POSITIVO) if tipos is None else list(tipos)

    melhor: tuple[EntityType, str] | None = None
    melhor_chave = (-1, -1)
    for tipo in candidatos:
        padrao = _PADRAO_POSITIVO.get(tipo)
        if padrao is None:
            continue
        match = _ultima(padrao, trecho)
        if match is None:
            continue
        chave = (match.start(), len(match.group()))
        if chave > melhor_chave:
            melhor_chave = chave
            melhor = (tipo, match.group())
    return melhor


def tem_ancora_negativa(texto: str, start: int, janela: int = JANELA_PADRAO) -> bool:
    """Se o rótulo mais próximo é administrativo, e não de dado pessoal.

    Um rótulo positivo que venha DEPOIS do negativo cancela a supressão. É o
    que mantém ``Processo nº`` funcionando como âncora de PROCESSO_CNJ, mesmo
    ``processo`` estando na lista negativa por causa de ``Processo nº
    2026/004587-3``.
    """
    trecho = _janela_de_busca(texto, start, janela)
    if not trecho:
        return False
    negativa = _ultima(_PADRAO_NEGATIVO, trecho)
    if negativa is None:
        return False
    positiva = tipo_ancorado(texto, start, janela)
    if positiva is None:
        return True
    match_positiva = _ultima(_PADRAO_POSITIVO[positiva[0]], trecho)
    assert match_positiva is not None
    # Empate de posicao (mesmo texto servindo as duas listas, como
    # "Processo") fica com a positiva: ela e especifica de um tipo.
    return match_positiva.start() < negativa.start()


def contexto_de_endereco(texto: str, start: int, janela: int = JANELA_ENDERECO) -> bool:
    """Se o trecho anterior parece endereço.

    Duas evidências, qualquer uma basta: vocabulário de endereço (logradouro,
    complemento, bairro, ou o verbo que o introduz) em qualquer ponto da
    janela, ou o padrão ``Cidade/UF`` imediatamente antes do candidato.

    A janela aqui é bem maior que a de rótulo (:data:`JANELA_ENDERECO` contra
    :data:`JANELA_PADRAO`) porque os dois sinais têm natureza diferente: o
    rótulo é pontual e encostado no valor, o endereço é difuso e se espalha
    pela frase. A regra de não atravessar quebra de parágrafo vale para as
    duas.
    """
    trecho = _janela_de_busca(texto, start, janela)
    if not trecho:
        return False
    if _CIDADE_UF.search(trecho):
        return True
    return _PADRAO_ENDERECO.search(trecho) is not None
