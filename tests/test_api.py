"""Testes da API de revisão.

**Não é preciso Redis rodando.** A fila é um ``rq.Queue`` de verdade sobre um
``fakeredis``, então o caminho de código do RQ é o mesmo de produção — só o
servidor é falso. Duas montagens, porque os testes precisam das duas metades
do assíncrono:

- ``cliente`` usa ``is_async=False``: o ``enqueue`` roda o worker ali mesmo.
  Serve para ver o resultado sem levantar processo nenhum.
- ``cliente_enfileirado`` usa ``is_async=True`` e NENHUM worker: o job fica
  parado na fila. É a única forma de observar o estado que a interface vê
  entre o POST e o fim do processamento.

``enqueue_in`` (a expiração agendada) não executa em nenhuma das duas — o RQ
o põe no ``ScheduledJobRegistry`` e quem dispara é o scheduler. Por isso a
expiração é testada chamando ``expirar_job`` e ``purgar_expirados`` na mão,
que é o que a tarefa pede e também o que o scheduler faria.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import fakeredis
import httpx
import pytest
from fastapi.testclient import TestClient
from rq import Queue

from redator.api.app import criar_app
from redator.api.config import Config
from redator.api.jobs import expirar_job, extrair, processar_documento, purgar_expirados
from redator.api.schemas import JobStatus
from redator.api.storage import Armazenamento, ErroLimpeza, novo_job_id

PDF_REAL = (
    Path(__file__).parent
    / "fixtures"
    / "pdf_manual"
    / "FUNSERV_Ata_Conselho_Fiscal_DADOS_FICTICIOS_TESTE.pdf"
)


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def config(tmp_path: Path) -> Config:
    """Diretório descartável e TTL folgado — quem testa TTL o encurta."""
    return Config(
        diretorio_base=tmp_path / "jobs",
        tamanho_maximo_bytes=1024 * 1024,
        ttl_segundos=1800,
        fila="teste",
    )


@pytest.fixture
def armazenamento(config: Config) -> Armazenamento:
    return Armazenamento(config.diretorio_base)


def _fila(config: Config, *, sincrona: bool) -> Queue:
    return Queue(
        config.fila,
        connection=fakeredis.FakeStrictRedis(),
        is_async=not sincrona,
    )


@pytest.fixture
def cliente(config: Config) -> Iterator[TestClient]:
    """POST processa o documento antes de responder."""
    with TestClient(criar_app(config, _fila(config, sincrona=True))) as cliente:
        yield cliente


@pytest.fixture
def cliente_enfileirado(config: Config) -> Iterator[TestClient]:
    """POST só enfileira: nada processa até alguém rodar o worker."""
    with TestClient(criar_app(config, _fila(config, sincrona=False))) as cliente:
        yield cliente


def enviar(
    cliente: TestClient, caminho: Path, nome: str = "documento.pdf"
) -> httpx.Response:
    return cliente.post(
        "/documentos",
        files={"arquivo": (nome, caminho.read_bytes(), "application/pdf")},
    )


def entidades(corpo: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for pagina in corpo["paginas"] for e in pagina["entidades"]]


# --------------------------------------------------------------------------- #
# POST /documentos
# --------------------------------------------------------------------------- #


def test_post_devolve_recebido_com_id(
    cliente_enfileirado: TestClient, pdf_documentos: Path
) -> None:
    resposta = enviar(cliente_enfileirado, pdf_documentos)

    assert resposta.status_code == 202
    corpo = resposta.json()
    assert corpo["status"] == JobStatus.RECEBIDO.value
    assert len(corpo["id"]) == 32
    assert corpo["paginas"] is None
    assert corpo["erro"] is None
    assert datetime.fromisoformat(corpo["expira_em"]) > datetime.now(UTC)


def test_post_nao_espera_o_processamento(
    cliente_enfileirado: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    """Sem worker, o job fica em RECEBIDO — prova de que o POST não processou."""
    job_id = enviar(cliente_enfileirado, pdf_documentos).json()["id"]

    estado = armazenamento.ler_estado(job_id)
    assert estado is not None
    assert estado.status is JobStatus.RECEBIDO


def test_pdf_vai_para_fora_do_repositorio(
    cliente_enfileirado: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    job_id = enviar(cliente_enfileirado, pdf_documentos).json()["id"]

    destino = armazenamento.caminho_pdf(job_id)
    assert destino.is_file()
    assert destino.read_bytes() == pdf_documentos.read_bytes()
    assert Path(__file__).parents[1] not in destino.parents


def test_arquivo_que_nao_e_pdf_e_recusado(
    cliente_enfileirado: TestClient, tmp_path: Path
) -> None:
    falso = tmp_path / "documento.pdf"
    falso.write_bytes(b"PK\x03\x04 isto e um zip com nome de pdf")

    resposta = enviar(cliente_enfileirado, falso)

    assert resposta.status_code == 415


def test_extensao_e_content_type_nao_bastam(
    cliente_enfileirado: TestClient, tmp_path: Path, armazenamento: Armazenamento
) -> None:
    """A recusa é por magic bytes: nome e content-type vêm do cliente."""
    falso = tmp_path / "documento.pdf"
    falso.write_bytes(b"%PD\xc3 quase")

    assert enviar(cliente_enfileirado, falso).status_code == 415
    assert not armazenamento.base.exists() or not list(armazenamento.base.iterdir())


def test_arquivo_acima_do_maximo_e_recusado(
    tmp_path: Path, config: Config, pdf_documentos: Path
) -> None:
    apertado = Config(
        diretorio_base=config.diretorio_base, tamanho_maximo_bytes=64, fila="teste"
    )
    with TestClient(criar_app(apertado, _fila(apertado, sincrona=False))) as cliente:
        assert enviar(cliente, pdf_documentos).status_code == 413


# --------------------------------------------------------------------------- #
# GET /documentos/{job_id}
# --------------------------------------------------------------------------- #


def test_get_antes_de_processar(
    cliente_enfileirado: TestClient, pdf_documentos: Path
) -> None:
    job_id = enviar(cliente_enfileirado, pdf_documentos).json()["id"]

    corpo = cliente_enfileirado.get(f"/documentos/{job_id}").json()

    assert corpo["status"] in {
        JobStatus.RECEBIDO.value,
        JobStatus.PROCESSANDO.value,
    }
    assert corpo["paginas"] is None


def test_get_depois_de_processar(cliente: TestClient, pdf_documentos: Path) -> None:
    """O worker síncrono já rodou dentro do POST; aqui só se lê o resultado."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]

    corpo = cliente.get(f"/documentos/{job_id}").json()

    assert corpo["status"] == JobStatus.PRONTO.value
    assert corpo["progresso"] == 1.0
    assert corpo["erro"] is None
    assert len(corpo["paginas"]) == 1


def test_entidades_do_pdf_conhecido(cliente: TestClient, pdf_documentos: Path) -> None:
    """As três linhas do fixture: CPF validado, CNPJ validado e telefone."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    achadas = entidades(cliente.get(f"/documentos/{job_id}").json())

    por_tipo = {e["type"]: e for e in achadas}
    assert {"CPF", "CNPJ", "TELEFONE"} <= set(por_tipo)

    cpf = por_tipo["CPF"]
    assert cpf["texto_original"] == "529.982.247-25"
    assert cpf["validated"] is True
    assert cpf["confidence"] == 0.99
    assert cpf["context"] is not None
    assert cpf["pagina"] == 0
    assert len(cpf["id"]) == 32
    assert por_tipo["CNPJ"]["texto_original"] == "46.634.044/0001-74"


def test_cada_entidade_tem_id_proprio(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    achadas = entidades(cliente.get(f"/documentos/{job_id}").json())

    ids = [e["id"] for e in achadas]
    assert len(ids) == len(set(ids))


def test_bboxes_caem_dentro_da_pagina(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    """Sem isso a interface não teria onde desenhar a tarja."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    for pagina in corpo["paginas"]:
        assert pagina["largura"] > 0 and pagina["altura"] > 0
        for entidade in pagina["entidades"]:
            assert entidade["bboxes"], "entidade sem caixa nao e tarjavel"
            for x0, y0, x1, y1 in entidade["bboxes"]:
                assert 0 <= x0 < x1 <= pagina["largura"]
                assert 0 <= y0 < y1 <= pagina["altura"]


def test_cpf_nativo_tem_5_bboxes_no_padrao_dou(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    """A previa que a interface mostra ja e o padrao DOU: 5 caixas, nao 1 —

    o que o revisor ve e exatamente o que redigir_pdf desenha no final.
    """
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    achadas = entidades(cliente.get(f"/documentos/{job_id}").json())

    (cpf,) = [e for e in achadas if e["type"] == "CPF"]
    assert len(cpf["bboxes"]) == 5


def test_cpf_mascarado_requer_revisao_na_api(
    cliente: TestClient, gerador: ModuleType, tmp_path: Path
) -> None:
    caminho = gerador.gerar_pdf(tmp_path / "mascarado.pdf", ["CPF: ***.982.247-**"])
    job_id = enviar(cliente, caminho).json()["id"]
    achadas = entidades(cliente.get(f"/documentos/{job_id}").json())

    (mascarado,) = [e for e in achadas if e["type"] == "CPF_MASCARADO"]
    assert mascarado["requires_review"] is True


def test_pagina_sem_entidade_aparece_mesmo_assim(
    cliente: TestClient, pdf_vazio: Path
) -> None:
    job_id = enviar(cliente, pdf_vazio).json()["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    assert corpo["status"] == JobStatus.PRONTO.value
    assert len(corpo["paginas"]) == 1
    assert corpo["paginas"][0]["entidades"] == []


def test_get_de_id_inexistente_devolve_404(cliente: TestClient) -> None:
    assert cliente.get(f"/documentos/{novo_job_id()}").status_code == 404


@pytest.mark.parametrize(
    "job_id", ["..", "nao-e-um-id", "%2e%2e", "a" * 31, "A" * 32, "../../etc"]
)
def test_id_malformado_nao_vira_caminho(cliente: TestClient, job_id: str) -> None:
    """O id vira nome de diretório: aceitar ``..`` seria leitura arbitrária."""
    resposta = cliente.get(f"/documentos/{job_id}")
    assert resposta.status_code == 404


# --------------------------------------------------------------------------- #
# DELETE /documentos/{job_id}
# --------------------------------------------------------------------------- #


def test_delete_remove_job_e_get_devolve_404(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    assert cliente.get(f"/documentos/{job_id}").status_code == 200

    assert cliente.delete(f"/documentos/{job_id}").status_code == 204

    assert cliente.get(f"/documentos/{job_id}").status_code == 404
    assert not (armazenamento.base / job_id).exists()


def test_delete_apaga_pdf_e_resultado(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    diretorio = armazenamento.base / job_id
    assert list(diretorio.iterdir()), "o job deveria ter deixado arquivos"

    cliente.delete(f"/documentos/{job_id}")

    assert not diretorio.exists()


def test_delete_de_id_inexistente_devolve_404(cliente: TestClient) -> None:
    assert cliente.delete(f"/documentos/{novo_job_id()}").status_code == 404


# --------------------------------------------------------------------------- #
# TTL e expiração
# --------------------------------------------------------------------------- #


def test_expirar_job_apaga_tudo(
    cliente: TestClient,
    pdf_documentos: Path,
    config: Config,
    armazenamento: Armazenamento,
) -> None:
    """A lógica de expiração, chamada direto — sem esperar o tempo real."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    diretorio = armazenamento.base / job_id
    assert (diretorio / "original.pdf").is_file()
    assert (diretorio / "resultado.json").is_file()

    vencido = armazenamento.ler_estado(job_id)
    assert vencido is not None
    armazenamento.escrever_estado(
        vencido.model_copy(update={"expira_em": datetime.now(UTC) - timedelta(1)})
    )

    assert expirar_job(job_id, config) is True
    assert not diretorio.exists()
    assert cliente.get(f"/documentos/{job_id}").status_code == 404


def test_expirar_job_respeita_prazo_ainda_valido(
    cliente: TestClient,
    pdf_documentos: Path,
    config: Config,
    armazenamento: Armazenamento,
) -> None:
    """Agendamento atrasado não pode destruir job cujo prazo foi renovado."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]

    assert expirar_job(job_id, config) is False
    assert (armazenamento.base / job_id).is_dir()
    assert cliente.get(f"/documentos/{job_id}").status_code == 200


def test_job_vencido_nao_e_servido_mesmo_sem_scheduler(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    """A rede de segurança: o GET destrói o que venceu, ninguém precisa varrer."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    estado = armazenamento.ler_estado(job_id)
    assert estado is not None
    armazenamento.escrever_estado(
        estado.model_copy(
            update={"expira_em": datetime.now(UTC) - timedelta(seconds=1)}
        )
    )

    assert cliente.get(f"/documentos/{job_id}").status_code == 404
    assert not (armazenamento.base / job_id).exists()


def test_purgar_expirados_varre_so_o_vencido(
    cliente: TestClient,
    pdf_documentos: Path,
    config: Config,
    armazenamento: Armazenamento,
) -> None:
    vencido = enviar(cliente, pdf_documentos).json()["id"]
    vivo = enviar(cliente, pdf_documentos).json()["id"]
    estado = armazenamento.ler_estado(vencido)
    assert estado is not None
    armazenamento.escrever_estado(
        estado.model_copy(update={"expira_em": datetime.now(UTC) - timedelta(1)})
    )

    assert purgar_expirados(config) == [vencido]

    assert not (armazenamento.base / vencido).exists()
    assert (armazenamento.base / vivo).is_dir()


# --------------------------------------------------------------------------- #
# Armazenamento.remover — retentativa e falha visível (Windows)
#
# Achado intermitente: no Windows, ``shutil.rmtree`` pode falhar mesmo com
# todo arquivo do nosso próprio código fechado corretamente — o SO demora um
# instante a mais para liberar o lock depois do close(), e nesse intervalo um
# antivírus/indexador que tenha aberto o arquivo pode segurá-lo por mais um
# punhado de milissegundos. Ver DECISOES.md, Fase 3, item 11.
# --------------------------------------------------------------------------- #


def test_remocao_sobrevive_a_handle_momentaneamente_aberto(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    """Reproduz o cenário do achado: um handle aberto no instante da remoção.

    Simula o antivírus/indexador (ou o instante entre o ``close()`` do nosso
    código e o SO liberar o lock de verdade): o arquivo está aberto quando
    ``remover`` é chamado, e é fechado pouco depois, ainda dentro da janela de
    retentativa. Antes desta correção (``shutil.rmtree(..., ignore_errors=True)``
    numa tentativa só), isso apagava o diretório pela metade e devolvia
    sucesso de qualquer jeito; a asserção abaixo falha nesse regime.
    """
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    diretorio = armazenamento.base / job_id
    handle = (diretorio / "original.pdf").open("rb")
    try:
        liberador = threading.Timer(0.15, handle.close)
        liberador.start()

        assert armazenamento.remover(job_id) is True
        assert not diretorio.exists()
    finally:
        liberador.join()
        if not handle.closed:
            handle.close()


def test_remocao_levanta_erro_se_handle_nunca_libera(
    cliente: TestClient, pdf_documentos: Path, armazenamento: Armazenamento
) -> None:
    """Esgotadas as retentativas, o erro sobe — nunca mais é engolido."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    diretorio = armazenamento.base / job_id
    handle = (diretorio / "original.pdf").open("rb")
    try:
        with pytest.raises(ErroLimpeza):
            armazenamento.remover(job_id)
        # A falha foi visível, mas nao destruiu o que ainda podia ser
        # limpo depois: o diretorio continua la para a proxima tentativa.
        assert diretorio.is_dir()
    finally:
        handle.close()

    # Com o handle liberado, uma nova tentativa resolve sozinha.
    assert armazenamento.remover(job_id) is True
    assert not diretorio.exists()


def test_obter_de_job_vencido_devolve_404_mesmo_se_limpeza_falhar(
    cliente: TestClient,
    pdf_documentos: Path,
    armazenamento: Armazenamento,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET nunca serve o que venceu, nem quando a limpeza física falha.

    O job já está logicamente morto (TTL vencido); a API responde 404 de
    qualquer jeito. Mas a falha de limpeza não pode desaparecer: tem de virar
    log crítico, porque é dado pessoal potencialmente retido além do TTL
    prometido.
    """
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    estado = armazenamento.ler_estado(job_id)
    assert estado is not None
    armazenamento.escrever_estado(
        estado.model_copy(
            update={"expira_em": datetime.now(UTC) - timedelta(seconds=1)}
        )
    )

    def _sempre_falha(self: Armazenamento, job_id: str) -> bool:
        raise ErroLimpeza("simulado: handle nunca libera")

    monkeypatch.setattr(Armazenamento, "remover", _sempre_falha)

    with caplog.at_level(logging.CRITICAL, logger="redator.api.storage"):
        resposta = cliente.get(f"/documentos/{job_id}")

    assert resposta.status_code == 404
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_delete_devolve_500_se_limpeza_falhar_persistentemente(
    cliente: TestClient,
    pdf_documentos: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DELETE pediu destruição explícita: não pode fingir sucesso (204)."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]

    def _sempre_falha(self: Armazenamento, job_id: str) -> bool:
        raise ErroLimpeza("simulado: handle nunca libera")

    monkeypatch.setattr(Armazenamento, "remover", _sempre_falha)

    assert cliente.delete(f"/documentos/{job_id}").status_code == 500


def test_purgar_expirados_pula_job_cuja_limpeza_falha_e_continua(
    cliente: TestClient,
    pdf_documentos: Path,
    config: Config,
    armazenamento: Armazenamento,
) -> None:
    """Um job preso não trava a varredura dos outros, nem finge removido."""
    preso = enviar(cliente, pdf_documentos).json()["id"]
    vivo_mas_vencido = enviar(cliente, pdf_documentos).json()["id"]
    for job_id in (preso, vivo_mas_vencido):
        estado = armazenamento.ler_estado(job_id)
        assert estado is not None
        armazenamento.escrever_estado(
            estado.model_copy(update={"expira_em": datetime.now(UTC) - timedelta(1)})
        )

    diretorio_preso = armazenamento.base / preso
    handle = (diretorio_preso / "original.pdf").open("rb")
    try:
        removidos = purgar_expirados(config)
        assert removidos == [vivo_mas_vencido]
        assert diretorio_preso.is_dir()
    finally:
        handle.close()

    # liberado o handle, a proxima varredura termina o servico
    assert purgar_expirados(config) == [preso]


def test_ttl_configuravel_chega_ao_job(tmp_path: Path, pdf_documentos: Path) -> None:
    curto = Config(diretorio_base=tmp_path / "jobs", ttl_segundos=60, fila="teste")
    with TestClient(criar_app(curto, _fila(curto, sincrona=False))) as cliente:
        corpo = enviar(cliente, pdf_documentos).json()

    faltando = datetime.fromisoformat(corpo["expira_em"]) - datetime.now(UTC)
    assert timedelta(seconds=30) < faltando <= timedelta(seconds=60)


# --------------------------------------------------------------------------- #
# erro no worker
# --------------------------------------------------------------------------- #


def test_pdf_corrompido_vira_status_erro(cliente: TestClient, tmp_path: Path) -> None:
    """Passa no magic byte e quebra na extração: o job reporta, não some."""
    corrompido = tmp_path / "corrompido.pdf"
    corrompido.write_bytes(b"%PDF-1.7\nisto nao e a estrutura de um PDF\n")

    job_id = enviar(cliente, corrompido).json()["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    assert corpo["status"] == JobStatus.ERRO.value
    assert corpo["erro"]
    assert corpo["paginas"] is None


def test_erro_nao_trava_a_fila(
    cliente: TestClient, tmp_path: Path, pdf_documentos: Path
) -> None:
    corrompido = tmp_path / "corrompido.pdf"
    corrompido.write_bytes(b"%PDF-1.7\nlixo\n")
    enviar(cliente, corrompido)

    job_id = enviar(cliente, pdf_documentos).json()["id"]

    assert cliente.get(f"/documentos/{job_id}").json()["status"] == (
        JobStatus.PRONTO.value
    )


def test_job_cancelado_antes_do_worker_nao_ressuscita(
    cliente_enfileirado: TestClient,
    pdf_documentos: Path,
    config: Config,
    armazenamento: Armazenamento,
) -> None:
    job_id = enviar(cliente_enfileirado, pdf_documentos).json()["id"]
    cliente_enfileirado.delete(f"/documentos/{job_id}")

    processar_documento(job_id, config)

    assert not (armazenamento.base / job_id).exists()


# --------------------------------------------------------------------------- #
# escolha de extrator
# --------------------------------------------------------------------------- #


def test_pdf_com_texto_nativo_nao_chama_ocr(
    pdf_documentos: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def nunca(_: object) -> None:
        raise AssertionError("OCR chamado para PDF com camada de texto")

    monkeypatch.setattr("redator.api.jobs.extract_pdf_scanned", nunca)

    assert extrair(pdf_documentos).pages[0].text.strip()


def test_pdf_sem_texto_algum_cai_no_ocr(
    pdf_so_imagem: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rota testada sem Tesseract: o que importa é qual função é escolhida."""
    chamadas: list[Path] = []

    def sentinela(caminho: Path) -> str:
        chamadas.append(caminho)
        return "ocr"

    monkeypatch.setattr("redator.api.jobs.extract_pdf_scanned", sentinela)

    assert extrair(pdf_so_imagem) == "ocr"
    assert chamadas == [pdf_so_imagem]


# --------------------------------------------------------------------------- #
# segurança das respostas
# --------------------------------------------------------------------------- #


def test_nenhuma_resposta_e_cacheavel(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    """O corpo carrega CPF em texto claro: cache guardaria o dado além do TTL."""
    resposta = enviar(cliente, pdf_documentos)
    job_id = resposta.json()["id"]

    for atual in (resposta, cliente.get(f"/documentos/{job_id}")):
        assert atual.headers["cache-control"] == "no-store"


def test_api_nao_libera_origem_nenhuma(cliente: TestClient) -> None:
    """Sem CORS: uma página de terceiro não pode ler documento em revisão."""
    resposta = cliente.get(
        f"/documentos/{novo_job_id()}", headers={"Origin": "https://exemplo.invalido"}
    )
    assert "access-control-allow-origin" not in resposta.headers


def test_bind_padrao_e_loopback() -> None:
    config = Config(diretorio_base=Path("."))
    assert config.host == "127.0.0.1"
    assert config.exposto_na_rede is False
    aberto = Config(diretorio_base=Path("."), host="0.0.0.0")
    assert aberto.exposto_na_rede is True


# --------------------------------------------------------------------------- #
# PDF real (fora do controle de versão)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not PDF_REAL.is_file(), reason="PDF real nao esta nesta maquina")
def test_ata_real_de_ponta_a_ponta(cliente: TestClient) -> None:
    """Os 10 CPF e 7 EMAIL que a Fase 2 registrou, agora pela API."""
    job_id = enviar(cliente, PDF_REAL).json()["id"]
    corpo = cliente.get(f"/documentos/{job_id}").json()

    assert corpo["status"] == JobStatus.PRONTO.value
    assert len(corpo["paginas"]) == 4
    achadas = entidades(corpo)
    assert sum(e["type"] == "CPF" for e in achadas) == 10
    assert sum(e["type"] == "EMAIL" for e in achadas) == 7


# --------------------------------------------------------------------------- #
# GET /documentos/{id}/original — o PDF de volta, para a interface renderizar
# --------------------------------------------------------------------------- #


def test_original_devolve_o_pdf_enviado(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    """Byte a byte igual ao que subiu: e o mesmo arquivo, nao uma reescrita."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    resposta = cliente.get(f"/documentos/{job_id}/original")
    assert resposta.status_code == 200
    assert resposta.headers["content-type"] == "application/pdf"
    assert resposta.content == pdf_documentos.read_bytes()


def test_original_nao_e_cacheavel(cliente: TestClient, pdf_documentos: Path) -> None:
    """Serve dado pessoal em claro: nao pode ficar em cache de browser."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    resposta = cliente.get(f"/documentos/{job_id}/original")
    assert resposta.headers["cache-control"] == "no-store"
    assert resposta.headers["x-content-type-options"] == "nosniff"


def test_original_de_id_inexistente_devolve_404(cliente: TestClient) -> None:
    assert cliente.get(f"/documentos/{novo_job_id()}/original").status_code == 404


@pytest.mark.parametrize("job_id", ["..", "nao-e-um-id", "%2e%2e", "a" * 31, "A" * 32])
def test_original_com_id_malformado_nao_vira_caminho(
    cliente: TestClient, job_id: str
) -> None:
    assert cliente.get(f"/documentos/{job_id}/original").status_code == 404


def test_original_some_com_o_descarte(
    cliente: TestClient, pdf_documentos: Path
) -> None:
    """O DELETE explicito leva o original junto — nao ha como rebaixa-lo."""
    job_id = enviar(cliente, pdf_documentos).json()["id"]
    assert cliente.get(f"/documentos/{job_id}/original").status_code == 200
    assert cliente.delete(f"/documentos/{job_id}").status_code == 204
    assert cliente.get(f"/documentos/{job_id}/original").status_code == 404


def test_original_disponivel_antes_de_processar(
    cliente_enfileirado: TestClient, pdf_documentos: Path
) -> None:
    """A interface pode buscar o PDF enquanto a deteccao ainda roda."""
    job_id = enviar(cliente_enfileirado, pdf_documentos).json()["id"]
    corpo = cliente_enfileirado.get(f"/documentos/{job_id}").json()
    assert corpo["status"] == "recebido"
    assert cliente_enfileirado.get(f"/documentos/{job_id}/original").status_code == 200
