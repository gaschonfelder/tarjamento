"""Testes do perfil de redação.

Onde dá, as entidades vêm de detecção real (``detect_all``/``process_pdf``) e
não de ``Entity`` montada à mão: um teste de "CPF sem âncora" só prova alguma
coisa se a entidade de fato saiu sem âncora do detector.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from redator.detectors import TODOS_DETECTORES
from redator.entities import Entity, EntityType
from redator.pdf import process_pdf
from redator.perfil import (
    PERFIL_PADRAO,
    AcaoRedacao,
    EntidadeComAcao,
    aplicar_perfil,
    decidir_acao,
)
from redator.pipeline import detect_all

DETECTORES = list(TODOS_DETECTORES)
TEXTOS = Path(__file__).parent / "fixtures" / "textos"
ATA = (
    Path(__file__).parent
    / "fixtures"
    / "pdf_manual"
    / "FUNSERV_Ata_Conselho_Fiscal_DADOS_FICTICIOS_TESTE.pdf"
)


def unica(texto: str, tipo: EntityType) -> Entity:
    """A única entidade do tipo no texto — e falha se não for única."""
    achadas = [e for e in detect_all(texto, DETECTORES) if e.type is tipo]
    assert len(achadas) == 1, f"esperava 1 {tipo.name} em {texto!r}, achei {achadas}"
    return achadas[0]


def entidade(tipo: EntityType, **campos: object) -> Entity:
    base: dict[str, object] = {
        "type": tipo,
        "start": 0,
        "end": 5,
        "text": "xxxxx",
        "confidence": 0.99,
        "detector": "teste",
    }
    base.update(campos)
    return Entity(**base)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# cobertura do perfil
# --------------------------------------------------------------------------- #


def test_todo_entity_type_tem_acao_definida() -> None:
    """Falha quando o enum cresce e o perfil não acompanha."""
    faltando = set(EntityType) - set(PERFIL_PADRAO)
    assert not faltando, (
        f"sem acao em PERFIL_PADRAO: {sorted(t.name for t in faltando)}"
    )


def test_perfil_nao_tem_chave_fora_do_enum() -> None:
    assert set(PERFIL_PADRAO) == set(EntityType)


@pytest.mark.parametrize("tipo", list(EntityType), ids=lambda t: t.name)
def test_decidir_acao_responde_para_todo_tipo(tipo: EntityType) -> None:
    assert decidir_acao(entidade(tipo)) is PERFIL_PADRAO[tipo]


def test_so_tres_tipos_sao_publicados() -> None:
    """Uma exceção a mais ao TARJAR é decisão jurídica: tem de aparecer aqui."""
    publicados = {t for t, a in PERFIL_PADRAO.items() if a is AcaoRedacao.PUBLICAR}
    assert publicados == {EntityType.CNPJ, EntityType.PROCESSO_CNJ, EntityType.NOME}


def test_tipo_sem_acao_e_erro_e_nao_default(monkeypatch: pytest.MonkeyPatch) -> None:
    incompleto = {t: a for t, a in PERFIL_PADRAO.items() if t is not EntityType.RG}
    monkeypatch.setattr("redator.perfil.PERFIL_PADRAO", incompleto)
    with pytest.raises(KeyError, match="RG"):
        decidir_acao(entidade(EntityType.RG))


# --------------------------------------------------------------------------- #
# CPF: a ação não depende de como ele foi achado
# --------------------------------------------------------------------------- #


def test_cpf_com_ancora_e_tarjado() -> None:
    cpf = unica("CPF nº 529.982.247-25", EntityType.CPF)
    assert cpf.context is not None
    assert decidir_acao(cpf) is AcaoRedacao.TARJAR


def test_cpf_em_bloco_de_assinatura_sem_ancora_e_tarjado() -> None:
    cpf = unica("Assinatura\nMariana Alves Ribeiro\n529.982.247-25", EntityType.CPF)
    assert cpf.context is None, "o cenario so vale se o CPF saiu sem ancora"
    assert decidir_acao(cpf) is AcaoRedacao.TARJAR


def test_cpf_mascarado_e_tarjado() -> None:
    """O que sobra de um CPF mascarado ainda identifica, junto com o nome."""
    mascarado = unica("CPF ***.982.247-**", EntityType.CPF_MASCARADO)
    assert decidir_acao(mascarado) is AcaoRedacao.TARJAR


# --------------------------------------------------------------------------- #
# CNPJ
# --------------------------------------------------------------------------- #


def test_cnpj_e_publicado_mesmo_validado_e_com_confianca_maxima() -> None:
    """Certeza de detecção não é argumento para tarjar: CNPJ não é dado pessoal."""
    cnpj = unica("CNPJ: 46.634.044/0001-74", EntityType.CNPJ)
    assert cnpj.validated is True
    assert cnpj.confidence >= 0.99
    assert decidir_acao(cnpj) is AcaoRedacao.PUBLICAR


# --------------------------------------------------------------------------- #
# telefone: a distinção institucional/pessoal NÃO existe ainda
# --------------------------------------------------------------------------- #


def test_telefone_institucional_e_pessoal_sao_ambos_tarjados() -> None:
    """Documenta uma AUSÊNCIA, de propósito.

    O telefone da fundação no ofício deveria, em tese, ser publicado. Ele sai
    TARJAR porque a ``Entity`` não tem sinal nenhum que diga que ele é
    institucional — o ``allowlist: true`` do golden set é anotação de teste, e
    ``context`` é só o rótulo da âncora ("Telefone"), não uma classificação.

    Se este teste quebrar porque o institucional passou a sair PUBLICAR, a
    pergunta é: de onde veio o sinal? Se veio de ``context``, de ``text`` ou de
    heurística sobre o número, é regressão — é exatamente o atalho que a Fase
    3b registra como errado. Ver DECISOES.md.
    """
    oficio = (TEXTOS / "doc_teste_1_oficio.txt").read_text(encoding="utf-8")
    contrato = (TEXTOS / "doc_teste_1_contrato.txt").read_text(encoding="utf-8")

    institucionais = [
        e for e in detect_all(oficio, DETECTORES) if e.type is EntityType.TELEFONE
    ]
    pessoais = [
        e for e in detect_all(contrato, DETECTORES) if e.type is EntityType.TELEFONE
    ]
    assert institucionais and pessoais

    # A prova da ausência de sinal: o rótulo "Telefone institucional:" está no
    # texto, mas o que chega na Entity é só a âncora, sem a palavra decisiva.
    rotulado = next(
        e
        for e in institucionais
        if "Telefone institucional:" in oficio[max(0, e.start - 30) : e.start]
    )
    assert rotulado.context is not None, "a ancora foi achada..."
    assert "institucional" not in rotulado.context.lower(), "...mas sem a palavra"

    for telefone in [*institucionais, *pessoais]:
        assert decidir_acao(telefone) is AcaoRedacao.TARJAR


# --------------------------------------------------------------------------- #
# CID e a preservação da Entity
# --------------------------------------------------------------------------- #


def test_cid_e_sempre_tarjado() -> None:
    cid = unica("Afastamento por CID F32.1 conforme laudo", EntityType.CID)
    assert decidir_acao(cid) is AcaoRedacao.TARJAR


@pytest.mark.parametrize("requires_review", [True, False])
def test_requires_review_sobrevive_inalterado(requires_review: bool) -> None:
    """A ação não apaga o aviso de fragilidade: quem revisa ainda precisa dele."""
    detectado = unica("Afastamento por CID F32.1 conforme laudo", EntityType.CID)
    cid = replace(detectado, requires_review=requires_review)

    (resultado,) = aplicar_perfil([cid])

    assert resultado.acao is AcaoRedacao.TARJAR
    assert resultado.entity.requires_review is requires_review
    assert resultado.entity is cid  # a mesma entidade, não uma cópia reescrita


# --------------------------------------------------------------------------- #
# aplicar_perfil
# --------------------------------------------------------------------------- #


def test_aplicar_perfil_preserva_ordem_e_tamanho() -> None:
    entidades = detect_all(
        "CNPJ: 46.634.044/0001-74 — CPF nº 529.982.247-25 — telefone (15) 99842-7316",
        DETECTORES,
    )
    resultado = aplicar_perfil(entidades)

    assert [r.entity for r in resultado] == entidades
    assert all(isinstance(r, EntidadeComAcao) for r in resultado)


def test_aplicar_perfil_em_lista_vazia() -> None:
    assert aplicar_perfil([]) == []


def test_entidade_com_acao_e_imutavel() -> None:
    (r,) = aplicar_perfil([entidade(EntityType.CPF)])
    with pytest.raises(AttributeError):
        r.acao = AcaoRedacao.PUBLICAR  # type: ignore[misc]


def contar(entidades_por_pagina: dict[int, list[Entity]]) -> Counter[tuple[str, str]]:
    todas = [e for pagina in entidades_por_pagina.values() for e in pagina]
    return Counter((r.entity.type.name, r.acao.name) for r in aplicar_perfil(todas))


def test_pdf_sintetico_tem_publicado_e_tarjado(pdf_documentos: Path) -> None:
    """O caminho PDF de ponta a ponta, num fixture que sempre existe."""
    contagem = contar(process_pdf(pdf_documentos, DETECTORES))
    assert contagem == Counter(
        {("CPF", "TARJAR"): 1, ("CNPJ", "PUBLICAR"): 1, ("TELEFONE", "TARJAR"): 1}
    )


@pytest.mark.skipif(not ATA.is_file(), reason="PDF real nao esta nesta maquina")
def test_ata_do_funserv_tudo_tarjado() -> None:
    """Os 10 CPF e 7 EMAIL da Fase 2: nenhum dos dois tipos é publicável."""
    contagem = contar(process_pdf(ATA, DETECTORES))
    assert contagem == Counter({("CPF", "TARJAR"): 10, ("EMAIL", "TARJAR"): 7})
