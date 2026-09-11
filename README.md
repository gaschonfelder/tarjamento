# redator

Ferramenta de tarja de dados pessoais em documentos administrativos do
FUNSERV. Detecta CPF, CNPJ, RG, telefone, e-mail, CEP e outros tipos em texto,
PDF nativo e PDF digitalizado (OCR), e marca onde cada um está na página.

As decisões de projeto e as limitações conhecidas estão em
[`DECISOES.md`](DECISOES.md).

## Requisitos

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

```sh
uv sync
uv run pytest
```

## Dependência de sistema: Tesseract (só para OCR)

O OCR usa o [Tesseract](https://github.com/tesseract-ocr/tesseract) por meio
do `pytesseract`. **O binário do Tesseract e o pacote de idioma português
não são dependências Python** — `uv sync` não os instala. Sem eles tudo o
que não é OCR funciona normalmente, e os testes de OCR que precisam do
binário são **pulados** com a mensagem
`Tesseract não encontrado — instale e configure para rodar este teste`.

### Debian / Ubuntu

```sh
sudo apt-get update
sudo apt-get install -y tesseract-ocr tesseract-ocr-por
tesseract --list-langs   # precisa listar "por"
```

### Windows

O instalador oficial é o da UB-Mannheim, disponível pelo winget. Ele exige
elevação (UAC), então rode num PowerShell **como administrador**:

```powershell
winget install --id UB-Mannheim.TesseractOCR --exact --accept-source-agreements --accept-package-agreements
```

A instalação silenciosa costuma trazer só `eng` e `osd`. Para o português,
baixe o `por.traineddata` do repositório oficial e coloque-o numa pasta
`tessdata`. A pasta do instalador fica em `C:\Program Files\Tesseract-OCR\tessdata`
e também exige elevação para receber arquivos; a alternativa sem elevação é
uma pasta no seu perfil, que o projeto reconhece sozinho:

```powershell
New-Item -ItemType Directory -Force "$env:LOCALAPPDATA\tessdata" | Out-Null
uv run python -c "import urllib.request,os; urllib.request.urlretrieve('https://github.com/tesseract-ocr/tessdata/raw/main/por.traineddata', os.path.join(os.environ['LOCALAPPDATA'],'tessdata','por.traineddata'))"
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --tessdata-dir "$env:LOCALAPPDATA\tessdata" --list-langs
```

(O `Invoke-WebRequest` do PowerShell 5.1 falha no GitHub por TLS antigo; por
isso o download acima é feito pelo Python do projeto.)

### Como o projeto encontra o Tesseract

`redator.ocr.TesseractEngine` procura o binário nesta ordem: a variável de
ambiente `TESSERACT_CMD`, o `PATH`, e os locais usuais do instalador no
Windows. Para os idiomas: se `TESSDATA_PREFIX` estiver definida, o próprio
Tesseract a usa; senão, `%LOCALAPPDATA%\tessdata` é usada quando existir.
Os dois podem ser passados explicitamente ao construir o motor
(`tesseract_cmd=`, `tessdata_dir=`).

## Uso básico

```python
from redator.detectors import TODOS_DETECTORES
from redator.pdf import process_pdf, gerar_pdf_debug
from redator.ocr import extract_pdf_scanned

# PDF com camada de texto
entidades = process_pdf("documento.pdf", list(TODOS_DETECTORES))

# PDF digitalizado: mesmo pipeline, extrator diferente
entidades = process_pdf(
    "digitalizado.pdf", list(TODOS_DETECTORES), extrator=extract_pdf_scanned
)

# PDF de inspeção visual, com cada entidade marcada em vermelho
gerar_pdf_debug("digitalizado.pdf", "debug.pdf", entidades, extrator=extract_pdf_scanned)
```

`process_pdf` devolve `dict[página -> list[Entity]]`, com offsets no texto
extraído daquela página. Passe o **mesmo** `extrator` a `gerar_pdf_debug`: os
offsets só fazem sentido no texto que aquele extrator produziu.

## Layout

```
src/redator/
  entities.py, overlap.py, anchors.py, normalize.py, pipeline.py   # Fase 1: deteccao em texto
  validators.py, detectors/                                         # DV e detectores
  pdf/        extract.py (texto + bbox por caractere), pipeline.py (por pagina, debug)
  ocr/        base.py (Protocol OcrEngine), tesseract_engine.py, scanned.py
tests/
  fixtures/textos/     corpus anotado (golden set)
  fixtures/pdf/        gerador de PDFs sinteticos (nenhum binario versionado)
  fixtures/pdf_manual/ PDFs reais de teste — fora do git
```
