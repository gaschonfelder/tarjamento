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

## Desenvolvimento local: API, fila e worker

A suíte de testes **não precisa de Redis** — `tests/test_api.py` usa
`fakeredis`. Esta seção é para o teste de ponta a ponta à mão: subir a API de
verdade, com Redis e worker, e conferir o contrato antes de mexer no front.

### Redis no Windows: WSL2

Não há pacote oficial de Redis para Windows. Nesta máquina não há Docker
Desktop, então o caminho mais curto é o WSL2 — que já estava instalado com
Ubuntu. Uma vez só:

```powershell
wsl -d Ubuntu -- bash -c "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y redis-server"
wsl -d Ubuntu -- systemctl enable --now redis-server
wsl -d Ubuntu -- redis-cli ping          # PONG
```

**Não é preciso abrir o bind.** O Redis fica em `127.0.0.1:6379` *dentro* do
WSL, e o encaminhamento de localhost do WSL2 o torna alcançável do Windows no
mesmo endereço. Confira do lado Windows:

```powershell
uv run python -c "import redis; print(redis.Redis.from_url('redis://127.0.0.1:6379/0').ping())"
```

Mantê-lo em `127.0.0.1` não é detalhe: com `bind 0.0.0.0` o Redis passaria a
aceitar conexão de fora da máquina, e um Redis sem senha guardando fila de
documento pessoal não deve estar exposto a nada.

**Pegadinha: o WSL desliga sozinho quando fica ocioso, e leva o Redis junto.**
O `systemctl enable` garante que ele volte quando o WSL subir de novo, mas no
meio de uma sessão de teste a conexão simplesmente cai. Deixe um processo
segurando o WSL aberto num terminal à parte enquanto trabalha:

```powershell
wsl -d Ubuntu -- sleep infinity
```

(Qualquer terminal WSL aberto serve; o `sleep` é só a forma mais explícita.)

### Worker: no Windows, `rq.SimpleWorker`

O `Worker` padrão do RQ isola cada job num processo filho criado com
`os.fork()` — que **não existe no Windows**. O worker sobe, escuta e morre no
primeiro job, com `AttributeError: module 'os' has no attribute 'fork'`. Use
o `SimpleWorker`, que roda o job no próprio processo:

```powershell
uv run rq worker --with-scheduler --worker-class rq.SimpleWorker --url redis://127.0.0.1:6379/0 redator
```

O que se perde com isso, e só vale no Windows: sem processo filho, o
`job_timeout` (`TIMEOUT_PROCESSAMENTO`, 10 min) não tem quem matar, e um job
que trave prende o worker. Em produção Linux vale o `Worker` normal, e aí o
comando é o do topo de `src/redator/api/jobs.py`, sem `--worker-class`.

O `--with-scheduler` é o que dispara a expiração agendada no vencimento do
TTL. Sem ele a API continua correta — `Armazenamento.obter` destrói o que
venceu antes de responder —, mas um job que ninguém mais leia fica no disco
até alguém chamar `purgar_expirados`.

**Pegadinha: o lock do scheduler não é retentado.** O worker tenta pegar o
lock **uma vez**, na subida. Se outro worker o estiver segurando — inclusive
um que morreu e ainda não teve o lock expirado — ele desiste **em silêncio**:
não há erro, não há aviso, o worker roda normalmente e nada agendado dispara
nunca. O sintoma é exatamente o que se viu aqui: jobs vencidos ficando no
disco enquanto o worker parece saudável.

Confirme, sempre, que a linha abaixo aparece no log da subida:

```
Acquired scheduler lock for redator
```

Se não aparecer, mate todos os workers, espere o lock vencer (~1 min) e suba
um só. Para conferir o que está agendado:

```powershell
uv run python -c "import redis; from rq import Queue; from rq.registry import ScheduledJobRegistry; q=Queue('redator', connection=redis.Redis.from_url('redis://127.0.0.1:6379/0')); r=ScheduledJobRegistry(queue=q); print(len(r), [(j, r.get_scheduled_time(j)) for j in r.get_job_ids()])"
```

### Subir tudo

Três terminais, mais o que segura o WSL:

```powershell
# 1. Redis (via WSL) — e deixe este terminal aberto
wsl -d Ubuntu -- sleep infinity

# 2. Worker
uv run rq worker --with-scheduler --worker-class rq.SimpleWorker --url redis://127.0.0.1:6379/0 redator

# 3. API
uv run uvicorn redator.api.app:app --host 127.0.0.1 --port 8731
```

Variáveis de ambiente úteis (todas com default seguro, veja
`src/redator/api/config.py`): `REDATOR_API_TTL` (segundos, default 1800),
`REDATOR_API_DIR`, `REDATOR_API_MAX_BYTES`, `REDATOR_REDIS_URL`,
`REDATOR_API_HOST`, `REDATOR_API_PORT`.

### Teste de ponta a ponta à mão

```powershell
# POST — devolve 202 e o id, sem esperar o processamento
curl -s -X POST -F "arquivo=@tests/fixtures/pdf_manual/SEU_PDF.pdf" http://127.0.0.1:8731/documentos

# GET — repita até status virar "pronto"
curl -s http://127.0.0.1:8731/documentos/<job_id>

# DELETE — 204, e o diretório do job some do disco
curl -s -X DELETE http://127.0.0.1:8731/documentos/<job_id>
```

Os arquivos de cada job ficam em `%LOCALAPPDATA%\Temp\redator-jobs\<job_id>\`
(`original.pdf`, `estado.json`, `resultado.json`). Para conferir que sumiram:

```powershell
Get-ChildItem "$env:LOCALAPPDATA\Temp\redator-jobs"
```

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
