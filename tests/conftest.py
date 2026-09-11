"""Fixtures compartilhadas da suíte.

O gerador de PDFs mora em ``tests/fixtures/pdf/gerar_pdf.py``, que não é um
pacote importável. Carregá-lo aqui por caminho evita mexer em ``sys.path`` e
mantém os arquivos de teste sem essa plumbing.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

_CAMINHO_GERADOR = Path(__file__).parent / "fixtures" / "pdf" / "gerar_pdf.py"


def _carregar_gerador() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_gerar_pdf_fixtures", _CAMINHO_GERADOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"nao consegui carregar {_CAMINHO_GERADOR}")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = modulo
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="session")
def gerador() -> ModuleType:
    """O módulo gerador de PDFs sintéticos."""
    return _carregar_gerador()


@pytest.fixture
def pdf_documentos(gerador: ModuleType, tmp_path: Path) -> Path:
    """Três linhas com CPF, CNPJ e telefone rotulados."""
    return gerador.gerar_pdf(tmp_path / "documentos.pdf", gerador.LINHAS_DOCUMENTOS)


@pytest.fixture
def pdf_cep(gerador: ModuleType, tmp_path: Path) -> Path:
    """Duas linhas de endereço terminando em CEP."""
    return gerador.gerar_pdf(tmp_path / "cep.pdf", gerador.LINHAS_CEP)


@pytest.fixture
def pdf_quebrado(gerador: ModuleType, tmp_path: Path) -> Path:
    """CPF partido de propósito entre duas linhas."""
    return gerador.gerar_pdf(tmp_path / "quebrado.pdf", gerador.LINHAS_QUEBRADAS)


@pytest.fixture
def pdf_vazio(gerador: ModuleType, tmp_path: Path) -> Path:
    """Página em branco, sem texto nem imagem."""
    return gerador.gerar_pdf_vazio(tmp_path / "vazio.pdf")


@pytest.fixture
def pdf_so_imagem(gerador: ModuleType, tmp_path: Path) -> Path:
    """Página com imagem e nenhum caractere."""
    return gerador.gerar_pdf_so_imagem(tmp_path / "imagem.pdf")


@pytest.fixture
def pdf_tabela_posicionada(gerador: ModuleType, tmp_path: Path) -> Path:
    """Cabeçalho Nome/CPF e duas fileiras, colunas por coordenada."""
    return gerador.gerar_pdf_tabela_posicionada(tmp_path / "tabela.pdf")


@pytest.fixture
def pdf_formulario_posicionado(gerador: ModuleType, tmp_path: Path) -> Path:
    """Rótulo e valor em colunas, na mesma fileira."""
    return gerador.gerar_pdf_tabela_posicionada(
        tmp_path / "formulario.pdf", gerador.FORMULARIO_POSICIONADO
    )
