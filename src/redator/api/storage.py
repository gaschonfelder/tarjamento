"""Armazenamento temporário de um job: PDF original e resultado.

**Escolha: diretório por job no disco, e não um dict em memória.** O dict
seria mais simples, mas não funcionaria: a API e o worker RQ são processos
distintos, e o worker escreve o que a API precisa ler de volta. Um dict só
sobreviveria à arquitetura se o processamento fosse síncrono, que é
exatamente o que a fila existe para não ser.

**O que fica no disco, e o que não fica.** Ficam o PDF original
(``original.pdf``) e o resultado (``resultado.json``), que contém os valores
reais dos dados pessoais detectados. O **texto extraído nunca é gravado**:
ele vive na memória do worker durante o processamento e morre com ele. Era o
maior volume de dado pessoal em repouso e não havia por que persistir.

**Limitação aceita.** Não há bloqueio entre processos. Escritas são atômicas
(arquivo temporário + ``os.replace``), então nunca se lê um JSON parcial, mas
duas escritas simultâneas no mesmo job — que só aconteceriam se o mesmo
``job_id`` fosse processado duas vezes — resolvem por última-a-escrever. Para
uma ferramenta interna, em que cada job é enfileirado uma vez, é suficiente.
"""

from __future__ import annotations

import os
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .schemas import JobResponse, JobStatus, PaginaResponse

__all__ = ["Armazenamento", "job_id_valido", "novo_job_id"]

_NOME_PDF = "original.pdf"
_NOME_ESTADO = "estado.json"
_NOME_RESULTADO = "resultado.json"

#: ``job_id`` só existe na forma que :func:`novo_job_id` produz. A validação
#: não é cosmética: o id vira nome de diretório, e aceitar ``..`` ou barra
#: transformaria ``GET /documentos/{job_id}`` em leitura de caminho arbitrário.
_PADRAO_JOB_ID = re.compile(r"\A[0-9a-f]{32}\Z")


def novo_job_id() -> str:
    return uuid.uuid4().hex


def job_id_valido(job_id: str) -> bool:
    return _PADRAO_JOB_ID.match(job_id) is not None


class _Resultado(BaseModel):
    """Envelope do ``resultado.json`` — só existe para o Pydantic ter raiz."""

    paginas: list[PaginaResponse]


class Armazenamento:
    """Os jobs sob um diretório base. Um subdiretório por job."""

    def __init__(self, diretorio_base: Path) -> None:
        self._base = Path(diretorio_base)

    @property
    def base(self) -> Path:
        return self._base

    # ------------------------------------------------------------------ #
    # caminhos
    # ------------------------------------------------------------------ #

    def _diretorio(self, job_id: str) -> Path:
        if not job_id_valido(job_id):
            raise ValueError(f"job_id invalido: {job_id!r}")
        return self._base / job_id

    def caminho_pdf(self, job_id: str) -> Path:
        """Onde está o PDF original. Não garante que exista."""
        return self._diretorio(job_id) / _NOME_PDF

    def existe(self, job_id: str) -> bool:
        return (
            job_id_valido(job_id) and (self._diretorio(job_id) / _NOME_ESTADO).is_file()
        )

    # ------------------------------------------------------------------ #
    # escrita
    # ------------------------------------------------------------------ #

    def criar(self, job_id: str, pdf: bytes, ttl_segundos: int) -> JobResponse:
        """Grava o PDF e o estado inicial, e devolve o JobResponse de RECEBIDO."""
        diretorio = self._diretorio(job_id)
        # 0o700: no Linux ninguem alem do dono le o PDF. No Windows o modo e
        # ignorado — la a protecao e o ACL do proprio temp do usuario.
        diretorio.mkdir(parents=True, exist_ok=False, mode=0o700)
        (diretorio / _NOME_PDF).write_bytes(pdf)
        estado = JobResponse(
            id=job_id,
            status=JobStatus.RECEBIDO,
            progresso=0.0,
            expira_em=datetime.now(UTC) + timedelta(seconds=ttl_segundos),
        )
        self.escrever_estado(estado)
        return estado

    def escrever_estado(self, estado: JobResponse) -> None:
        """Persiste o estado SEM as páginas — o resultado tem arquivo próprio."""
        sem_paginas = estado.model_copy(update={"paginas": None})
        self._gravar(
            self._diretorio(estado.id) / _NOME_ESTADO, sem_paginas.model_dump_json()
        )

    def escrever_resultado(self, job_id: str, paginas: list[PaginaResponse]) -> None:
        self._gravar(
            self._diretorio(job_id) / _NOME_RESULTADO,
            _Resultado(paginas=paginas).model_dump_json(),
        )

    @staticmethod
    def _gravar(destino: Path, conteudo: str) -> None:
        """Escrita atômica: ninguém lê um JSON pela metade."""
        temporario = destino.with_suffix(destino.suffix + ".tmp")
        temporario.write_text(conteudo, encoding="utf-8")
        os.replace(temporario, destino)

    # ------------------------------------------------------------------ #
    # leitura
    # ------------------------------------------------------------------ #

    def ler_estado(self, job_id: str) -> JobResponse | None:
        """O estado cru, sem páginas e sem checar expiração."""
        if not job_id_valido(job_id):
            return None
        arquivo = self._diretorio(job_id) / _NOME_ESTADO
        try:
            bruto = arquivo.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return None
        try:
            return JobResponse.model_validate_json(bruto)
        except ValidationError:
            # Estado corrompido e job perdido, nao job travado: some com ele
            # em vez de devolver 500 para sempre.
            self.remover(job_id)
            return None

    def obter(self, job_id: str) -> JobResponse | None:
        """O job completo, ou ``None`` se não existe **ou já expirou**.

        Um job vencido é destruído aqui, na leitura. É a rede de segurança que
        torna a expiração independente de o scheduler do RQ estar de pé: nada
        vencido é servido, mesmo que ninguém o tenha varrido ainda.
        """
        estado = self.ler_estado(job_id)
        if estado is None:
            return None
        if estado.expira_em <= datetime.now(UTC):
            self.remover(job_id)
            return None
        if estado.status is not JobStatus.PRONTO:
            return estado
        return estado.model_copy(update={"paginas": self._ler_resultado(job_id)})

    def _ler_resultado(self, job_id: str) -> list[PaginaResponse]:
        arquivo = self._diretorio(job_id) / _NOME_RESULTADO
        try:
            bruto = arquivo.read_text(encoding="utf-8")
        except (FileNotFoundError, NotADirectoryError):
            return []
        return _Resultado.model_validate_json(bruto).paginas

    # ------------------------------------------------------------------ #
    # destruição
    # ------------------------------------------------------------------ #

    def remover(self, job_id: str) -> bool:
        """Apaga o diretório do job inteiro. ``False`` se não havia nada.

        Vale para os três caminhos de fim de vida — DELETE explícito, TTL
        vencido e varredura —, porque os três querem a mesma coisa: nenhum
        resto em disco.
        """
        if not job_id_valido(job_id):
            return False
        diretorio = self._diretorio(job_id)
        if not diretorio.is_dir():
            return False
        shutil.rmtree(diretorio, ignore_errors=True)
        return not diretorio.exists()

    def purgar_expirados(self) -> list[str]:
        """Remove todo job já vencido e devolve os ids removidos."""
        if not self._base.is_dir():
            return []
        agora = datetime.now(UTC)
        removidos: list[str] = []
        for diretorio in sorted(self._base.iterdir()):
            if not diretorio.is_dir() or not job_id_valido(diretorio.name):
                continue
            estado = self.ler_estado(diretorio.name)
            if (estado is None or estado.expira_em <= agora) and self.remover(
                diretorio.name
            ):
                removidos.append(diretorio.name)
        return removidos
