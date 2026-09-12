"""Configuração da API, lida do ambiente.

Módulo a mais em relação à estrutura pedida (``app``/``jobs``/``schemas``/
``storage``), e de propósito: os quatro precisam dos mesmos parâmetros, e
deixá-los em qualquer um deles faria os outros três importarem um módulo por
uma razão que não é a dele.

Todo valor tem default seguro; nenhum precisa estar no ambiente para a API
subir. Os dois que são decisão de segurança — ``host`` e ``ttl_segundos`` —
estão comentados onde são definidos.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "HOST_PADRAO",
    "MAXIMO_BYTES_PADRAO",
    "TTL_PADRAO_SEGUNDOS",
    "Config",
]

#: Só loopback. Esta API devolve o VALOR REAL dos dados pessoais que detecta
#: (é o que a função de hover da revisão consome), então expô-la na rede é
#: decisão explícita de quem opera, nunca o default. Para rede interna,
#: ``REDATOR_API_HOST`` tem de ser escrito à mão.
HOST_PADRAO = "127.0.0.1"
PORTA_PADRAO = 8000

#: 50 MB. Acima disso o upload é recusado antes de tocar o disco.
MAXIMO_BYTES_PADRAO = 50 * 1024 * 1024

#: 30 minutos. É uma ferramenta de revisão em sessão: o tempo de uma pessoa
#: abrir o documento, revisar e baixar. Não há retenção depois disso.
TTL_PADRAO_SEGUNDOS = 30 * 60

REDIS_URL_PADRAO = "redis://127.0.0.1:6379/0"
FILA_PADRAO = "redator"

#: Subdiretório FIXO do temp do sistema, e não um ``mkdtemp`` por processo:
#: a API e o worker RQ são processos diferentes e precisam enxergar o mesmo
#: lugar. Fica fora do repositório, que é o que importa — nenhum PDF de
#: usuário encosta na árvore do projeto.
_NOME_DIRETORIO = "redator-jobs"


def _inteiro_do_ambiente(nome: str, padrao: int) -> int:
    bruto = os.environ.get(nome)
    if bruto is None or not bruto.strip():
        return padrao
    try:
        valor = int(bruto)
    except ValueError as erro:
        raise ValueError(f"{nome} precisa ser um inteiro, recebido {bruto!r}") from erro
    if valor <= 0:
        raise ValueError(f"{nome} precisa ser positivo, recebido {valor}")
    return valor


@dataclass(frozen=True, slots=True)
class Config:
    """Os parâmetros de uma instância da API."""

    diretorio_base: Path
    tamanho_maximo_bytes: int = MAXIMO_BYTES_PADRAO
    ttl_segundos: int = TTL_PADRAO_SEGUNDOS
    redis_url: str = REDIS_URL_PADRAO
    fila: str = FILA_PADRAO
    host: str = HOST_PADRAO
    porta: int = PORTA_PADRAO

    @classmethod
    def do_ambiente(cls) -> Config:
        """Lê o ambiente, caindo nos defaults para o que não estiver definido."""
        base = os.environ.get("REDATOR_API_DIR")
        return cls(
            diretorio_base=(
                Path(base) if base else Path(tempfile.gettempdir()) / _NOME_DIRETORIO
            ),
            tamanho_maximo_bytes=_inteiro_do_ambiente(
                "REDATOR_API_MAX_BYTES", MAXIMO_BYTES_PADRAO
            ),
            ttl_segundos=_inteiro_do_ambiente("REDATOR_API_TTL", TTL_PADRAO_SEGUNDOS),
            redis_url=os.environ.get("REDATOR_REDIS_URL", REDIS_URL_PADRAO),
            fila=os.environ.get("REDATOR_API_FILA", FILA_PADRAO),
            host=os.environ.get("REDATOR_API_HOST", HOST_PADRAO),
            porta=_inteiro_do_ambiente("REDATOR_API_PORT", PORTA_PADRAO),
        )

    @property
    def exposto_na_rede(self) -> bool:
        """Se o bind alcança outra máquina — o caso que exige decisão consciente."""
        return self.host not in ("127.0.0.1", "localhost", "::1")
