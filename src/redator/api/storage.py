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

import logging
import os
import re
import shutil
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .schemas import JobResponse, JobStatus, PaginaResponse

__all__ = ["Armazenamento", "ErroLimpeza", "job_id_valido", "novo_job_id"]

_log = logging.getLogger(__name__)

_NOME_PDF = "original.pdf"
_NOME_ESTADO = "estado.json"
_NOME_RESULTADO = "resultado.json"

#: Tentativas de `shutil.rmtree` antes de desistir e levantar erro. Ver
#: :func:`_remover_com_retentativa` — existe por causa de uma falha real e
#: intermitente no Windows, documentada no DECISOES.md (Fase 3, item 11).
_TENTATIVAS_REMOCAO = 5
_INTERVALO_RETENTATIVA_SEGUNDOS = 0.1


class ErroLimpeza(RuntimeError):
    """O diretório de um job não pôde ser apagado do disco.

    Levantado por :meth:`Armazenamento.remover` quando o diretório ainda
    existe depois de todas as tentativas. Quem chama decide o que fazer —
    esta exceção não decide sozinha se o dado pessoal retido é aceitável.
    """


def _remover_com_retentativa(diretorio: Path) -> None:
    """Apaga ``diretorio``, tentando de novo antes de desistir.

    **Por que retentativa, e não uma tentativa só com ``ignore_errors``.** No
    Windows, ``shutil.rmtree`` pode falhar mesmo que nosso código já tenha
    fechado todo arquivo que abriu (via ``with``/``finally``, como em
    ``pymupdf.open`` e no ``anyio.open_file`` do ``FileResponse``): o SO leva
    um instante a mais para liberar o lock depois do ``close()`` — e um
    antivírus ou indexador que tenha aberto o arquivo para escanear pode
    segurá-lo por mais um punhado de milissegundos. ``ignore_errors=True``
    mascarava exatamente isso: a função devolvia como se tivesse apagado, e o
    diretório ficava para trás, calado. Reproduzido de forma determinística:
    ver ``tests/test_api.py::test_remocao_sobrevive_a_handle_momentaneamente_aberto``.

    Poucas tentativas curtas resolvem essa folga. Se depois delas o
    diretório ainda existe, o erro sobe — não é mais aceitável engolir uma
    falha de uma operação cuja função é garantir não-retenção de dado
    pessoal.
    """
    ultimo_erro: OSError | None = None
    for tentativa in range(_TENTATIVAS_REMOCAO):
        if tentativa:
            time.sleep(_INTERVALO_RETENTATIVA_SEGUNDOS)
        try:
            shutil.rmtree(diretorio)
        except FileNotFoundError:
            return  # outra thread/processo já apagou; o objetivo foi atingido
        except OSError as erro:
            ultimo_erro = erro
            continue
        else:
            return
    raise ErroLimpeza(
        f"nao consegui apagar {diretorio} apos {_TENTATIVAS_REMOCAO} tentativas"
    ) from ultimo_erro

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
            self._remover_ignorando_falha(job_id, motivo="estado corrompido")
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
            self._remover_ignorando_falha(job_id, motivo="job vencido")
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

        Levanta :class:`ErroLimpeza` se o diretório existia mas não pôde ser
        apagado (ver :func:`_remover_com_retentativa`) — não devolve ``False``
        nesse caso, porque ``False`` aqui já significa "não havia nada", e os
        dois são situações diferentes para quem chama.
        """
        if not job_id_valido(job_id):
            return False
        diretorio = self._diretorio(job_id)
        if not diretorio.is_dir():
            return False
        _remover_com_retentativa(diretorio)
        return True

    def _remover_ignorando_falha(self, job_id: str, *, motivo: str) -> None:
        """Remove o job por uma via que já decidiu que ele está logicamente morto.

        Usado por :meth:`ler_estado` (estado corrompido) e :meth:`obter` (TTL
        vencido): nos dois casos a resposta a quem pergunta é a mesma — o job
        não existe — esteja a limpeza física do disco ok ou não. Mas a falha
        de limpeza em si nunca é silenciosa: vira log crítico, porque significa
        dado pessoal potencialmente retido em disco além do prometido. Quem
        varre o log tem no ``job_id`` e no ``motivo`` o suficiente para agir.
        """
        try:
            self.remover(job_id)
        except ErroLimpeza:
            _log.critical(
                "falha ao apagar job %s do disco (%s); dado pessoal pode ter"
                " ficado retido alem do TTL prometido",
                job_id,
                motivo,
                exc_info=True,
            )

    def purgar_expirados(self) -> list[str]:
        """Remove todo job já vencido e devolve os ids removidos.

        Um job cuja remoção física falhou não entra em ``removidos`` — ele
        continua no disco e será tentado de novo na próxima varredura, ou no
        próximo acesso via :meth:`obter`. A falha em si é logada como crítica,
        nunca engolida.
        """
        if not self._base.is_dir():
            return []
        agora = datetime.now(UTC)
        removidos: list[str] = []
        for diretorio in sorted(self._base.iterdir()):
            if not diretorio.is_dir() or not job_id_valido(diretorio.name):
                continue
            estado = self.ler_estado(diretorio.name)
            if estado is not None and estado.expira_em > agora:
                continue
            try:
                if self.remover(diretorio.name):
                    removidos.append(diretorio.name)
            except ErroLimpeza:
                _log.critical(
                    "purgar_expirados: falha ao apagar job %s do disco; dado"
                    " pessoal pode ter ficado retido alem do TTL prometido",
                    diretorio.name,
                    exc_info=True,
                )
        return removidos
