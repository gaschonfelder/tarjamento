"""Testes de ``POST /documentos/{job_id}/exportar``: o ciclo completo.

Detecção → revisão humana → redação real (Fase 4) → download. A prova de que
uma entidade TARJAR de fato saiu do documento é sempre o TEXTO do PDF
BAIXADO — relido do zero a partir do ``content`` da resposta, nunca do
status code sozinho, seguindo o mesmo princípio de ``test_redacao.py``.

Fixtures duplicadas de ``test_api.py`` (``config``, ``armazenamento``,
``cliente``) de propósito: este arquivo fica autossuficiente, sem importar de
outro módulo de teste — mesma escolha de ``test_verificacao.py`` em relação a
``test_redacao.py``.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fakeredis
import pymupdf
import pytest
from fastapi.testclient import TestClient
from rq import Queue

from redator.api.app import criar_app
from redator.api.config import Config
from redator.api.storage import Armazenamento, novo_job_id
from redator.entities import EntityType
from redator.pdf import extract_pdf
from redator.perfil import PERFIL_PADRAO, AcaoRedacao

# --------------------------------------------------------------------------- #
# fixtures — mesmo desenho de test_api.py
# --------------------------------------------------------------------------- #


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        diretorio_base=tmp_path / "jobs",
        tamanho_maximo_bytes=1024 * 1024,
        ttl_segundos=1800,
        fila="teste",
    )


@pytest.fixture
def armazenamento(config: Config) -> Armazenamento:
    return Armazenamento(config.diretorio_base)


@pytest.fixture
def cliente(config: Config) -> Iterator[TestClient]:
    """POST /documentos processa o documento antes de responder (fila síncrona)."""
    fila = Queue(config.fila, connection=fakeredis.FakeStrictRedis(), is_async=False)
    with TestClient(criar_app(config, fila)) as cliente:
        yield cliente


def enviar(cliente: TestClient, caminho: Path) -> dict[str, Any]:
    resposta = cliente.post(
        "/documentos",
        files={"arquivo": (caminho.name, caminho.read_bytes(), "application/pdf")},
    )
    assert resposta.status_code == 202
    return dict(resposta.json())


def _decisoes_padrao(paginas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A decisão que o PERFIL_PADRAO tomaria — sem overrides do revisor."""
    decisoes = []
    for pagina in paginas:
        for entidade in pagina["entidades"]:
            acao = PERFIL_PADRAO[EntityType[entidade["type"]]]
            decisoes.append(
                {
                    "entidade_id": entidade["id"],
                    "pagina": pagina["numero"],
                    "acao": "TARJAR" if acao is AcaoRedacao.TARJAR else "PUBLICAR",
                }
            )
    return decisoes


def _texto_do_pdf(conteudo: bytes, tmp_path: Path, nome: str = "baixado.pdf") -> str:
    """Relê o texto do PDF a partir dos BYTES da resposta — nunca do status."""
    caminho = tmp_path / nome
    caminho.write_bytes(conteudo)
    return "\n".join(p.text for p in extract_pdf(caminho).pages)


# --------------------------------------------------------------------------- #
# exportacao completa
# --------------------------------------------------------------------------- #


def test_exportacao_completa_serve_pdf_aprovado_e_destroi_o_job(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    resposta = cliente.post(
        f"/documentos/{job_id}/exportar",
        json={"decisoes": _decisoes_padrao(corpo["paginas"])},
    )

    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/pdf"
    assert resposta.content.startswith(b"%PDF-")
    assert resposta.headers["cache-control"] == "no-store"

    # O job (original, resultado, estado, redigido) nao sobrevive ao download.
    assert cliente.get(f"/documentos/{job_id}").status_code == 404
    assert not (armazenamento.base / job_id).exists()


def test_cpf_tarjado_nao_aparece_no_pdf_baixado(
    cliente: TestClient, pdf_documentos: Path, tmp_path: Path
) -> None:
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    resposta = cliente.post(
        f"/documentos/{job_id}/exportar",
        json={"decisoes": _decisoes_padrao(corpo["paginas"])},
    )

    texto = _texto_do_pdf(resposta.content, tmp_path)
    assert "529.982.247-25" not in texto


def test_cnpj_publicado_continua_no_pdf_baixado(
    cliente: TestClient, pdf_documentos: Path, tmp_path: Path
) -> None:
    """CNPJ e PUBLICAR no PERFIL_PADRAO — nao pode sumir do documento."""
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    resposta = cliente.post(
        f"/documentos/{job_id}/exportar",
        json={"decisoes": _decisoes_padrao(corpo["paginas"])},
    )

    texto = _texto_do_pdf(resposta.content, tmp_path)
    assert "46.634.044/0001-74" in texto


# --------------------------------------------------------------------------- #
# decisao faltando
# --------------------------------------------------------------------------- #


def test_decisao_faltando_devolve_400_com_a_lista(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()
    decisoes = _decisoes_padrao(corpo["paginas"])
    omitida = decisoes.pop()  # uma entidade fica sem decisao

    resposta = cliente.post(
        f"/documentos/{job_id}/exportar", json={"decisoes": decisoes}
    )

    assert resposta.status_code == 400
    faltando = resposta.json()["detail"]["faltando"]
    assert [f["entidade_id"] for f in faltando] == [omitida["entidade_id"]]

    # Reprovacao nao consome o job: ainda da para tentar de novo, completo.
    assert cliente.get(f"/documentos/{job_id}").status_code == 200


# --------------------------------------------------------------------------- #
# job inexistente ou expirado
# --------------------------------------------------------------------------- #


def test_job_inexistente_devolve_404(cliente: TestClient) -> None:
    resposta = cliente.post(
        f"/documentos/{novo_job_id()}/exportar", json={"decisoes": []}
    )
    assert resposta.status_code == 404


def test_job_expirado_devolve_404(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()
    decisoes = _decisoes_padrao(corpo["paginas"])

    estado = armazenamento.ler_estado(job_id)
    assert estado is not None
    armazenamento.escrever_estado(
        estado.model_copy(update={"expira_em": datetime.now(UTC) - timedelta(seconds=1)})
    )

    resposta = cliente.post(
        f"/documentos/{job_id}/exportar", json={"decisoes": decisoes}
    )
    assert resposta.status_code == 404


# --------------------------------------------------------------------------- #
# chamar duas vezes
# --------------------------------------------------------------------------- #


def test_exportar_duas_vezes_a_segunda_da_404(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()
    decisoes = _decisoes_padrao(corpo["paginas"])

    primeira = cliente.post(
        f"/documentos/{job_id}/exportar", json={"decisoes": decisoes}
    )
    assert primeira.status_code == 200

    segunda = cliente.post(
        f"/documentos/{job_id}/exportar", json={"decisoes": decisoes}
    )
    assert segunda.status_code == 404


# --------------------------------------------------------------------------- #
# entidade manual — sem Entity real, so bbox
# --------------------------------------------------------------------------- #


def test_entidade_manual_tarjada_e_redigida_de_verdade(
    cliente: TestClient, tmp_path: Path
) -> None:
    """Uma area marcada a mao na interface, sem detector nenhum por tras."""
    segredo = "AREA-MARCADA-A-MAO-SEGREDO"
    entrada = tmp_path / "manual.pdf"
    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((72, 300), segredo, fontname="helv", fontsize=11)
    documento.save(entrada)
    documento.close()

    # A bbox exata da propria palavra, medida no arquivo que sera enviado —
    # e exatamente o que a interface faz ao desenhar um retangulo na tela.
    documento = pymupdf.open(entrada)
    (retangulo,) = documento[0].search_for(segredo)
    bbox = [retangulo.x0, retangulo.y0, retangulo.x1, retangulo.y1]
    documento.close()

    job_id = enviar(cliente, entrada)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()
    assert not [e for p in corpo["paginas"] for e in p["entidades"]], (
        "premissa: nenhum detector acha dado pessoal nesta palavra"
    )

    decisoes = [
        {
            "entidade_id": "manual-1-teste",
            "pagina": 0,
            "acao": "TARJAR",
            "bboxes": [bbox],
        }
    ]
    resposta = cliente.post(
        f"/documentos/{job_id}/exportar", json={"decisoes": decisoes}
    )

    assert resposta.status_code == 200
    texto = _texto_do_pdf(resposta.content, tmp_path)
    assert segredo not in texto


def test_entidade_manual_sem_bbox_devolve_400(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    job_id = enviar(cliente, pdf_documentos)["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()
    decisoes = _decisoes_padrao(corpo["paginas"])
    decisoes.append({"entidade_id": "manual-sem-bbox", "pagina": 0, "acao": "TARJAR"})

    resposta = cliente.post(
        f"/documentos/{job_id}/exportar", json={"decisoes": decisoes}
    )

    assert resposta.status_code == 400
