# Decisões de projeto

Registro das decisões que não dá para reconstruir lendo o código: escolhas de
biblioteca e licença, limitações aceitas de propósito, e o que ficou para
depois com o motivo. Cada seção corresponde a uma fase.

## Fase 2 — Extração de PDF

### 1. PyMuPDF (AGPL-3.0) para extração com posição por caractere

A extração de PDF usa **PyMuPDF** (`pymupdf`, licença AGPL-3.0), inclusive
para obter a *bounding box* de cada caractere via `get_text("rawdict")`.

O uso atual é **interno ao FUNSERV**: a ferramenta roda na própria
infraestrutura, sem distribuição e sem disponibilização a terceiros — cenário
fora do escopo que a AGPL regula.

Se o projeto vier a ser **compartilhado com outro órgão, virar serviço
externo, ou ser distribuído de qualquer forma**, reavaliar com o jurídico
antes. Nesse cenário a alternativa é **pikepdf** (licença MPL, mais
permissiva), com implementação própria da extração posicional — o pikepdf
não entrega bbox por caractere pronto, então esse é o custo da troca.

### 2. Extração página por página

A extração produz uma `PageExtraction` por página; o documento nunca é
concatenado num texto único antes da detecção. Os offsets de uma entidade
são sempre relativos à página, e `bboxes_for_span` só faz sentido dentro de
uma página.

Consequência aceita: **uma entidade partida entre duas páginas não é
detectada**. É limitação documentada, da mesma categoria do CPF quebrado por
linha na Fase 1 (`esperado_fase: 2` no golden set) — ambas dependem de
informação de layout que a Fase 1 não tinha e que a extração por página
ainda não recompõe.

### 3. Tabela por colunas posicionadas: reconstrução da fileira visual

Quando as células de uma tabela são posicionadas por coordenada (o modo como
a maioria dos geradores de PDF escreve tabela), o PyMuPDF segmenta **cada
célula como uma `line` separada** no `rawdict`, sem espaço entre elas e sem
nenhum sinal de que pertencem à mesma fileira. Sem tratamento, "Nome" e
"CPF" caem em linhas de texto distintas, e um rótulo em uma coluna nunca
ancora o valor na coluna ao lado.

O extrator reconstrói a fileira visual: funde `lines` **adjacentes na ordem
de extração** que satisfaçam as duas condições —

- **sobreposição vertical real** de `[y0, y1]` de pelo menos 50% da altura
  da menor `line` (não basta `y0` parecido, que pegaria linhas empilhadas
  com entrelinha apertada);
- **a mesma tolerância de fonte usada para linha única** (`_bordas_coincidem`,
  razão de ~2,7× medida entre 11pt e ~30pt), o que mantém título grande ao
  lado de corpo pequeno como linhas separadas.

As células fundidas são ordenadas por `x0` e unidas por um **espaço
sintético cuja bbox é o próprio vão** entre elas. Só se comparam `lines`
vizinhas, de propósito: um layout em duas colunas de texto corrido tem linhas
na mesma altura que não são fileira, e como o PyMuPDF emite cada coluna como
bloco inteiro, elas nunca ficam adjacentes.

Isso resolve a **âncora de contexto dentro da fileira** — rótulo e valor na
mesma linha de texto (`CPF: 529.982.247-25` a partir de duas células).
Referência: `_mesma_fileira` em `src/redator/pdf/extract.py` e os testes
`test_*_posicionad*` em `tests/test_pdf_extract.py`.

### 4. Limitação conhecida, não resolvida: cabeçalho de coluna

Cabeçalho de **coluna** — rótulo numa linha, valores nas linhas abaixo, o
padrão de `tests/fixtures/textos/doc_teste_1_tabela.txt` — **não é alcançado
pela janela de âncora**, que só olha o texto imediatamente anterior na mesma
linha reconstruída (ou na linha anterior, quando o valor abre a linha).

CPF é encontrado mesmo assim, pelo dígito verificador. Um tipo que dependa
**só** de âncora (RG numa coluna "RG", por exemplo) não seria detectado nesse
padrão. Fica para quando os detectores contextuais forem testados contra
tabela real e a frequência do problema puder ser medida — resolver exige que
a janela conheça a coluna, não só a linha, e isso é uma mudança no sistema
de âncoras, não na extração.

### 5. PDF sintético é bem-comportado demais

O PDF gerado pelo próprio projeto (`tests/fixtures/pdf/gerar_pdf.py`) tende a
esconder lacunas: espaços inseridos via texto literal chegam ao `rawdict`
como **caracteres reais**, com bbox e tudo, enquanto PDF real — e tabela por
coordenada em particular — frequentemente **não escreve espaço nenhum** e
posiciona o texto por deslocamento. Foi exatamente essa diferença que
escondeu o problema do item 3 até ele ser testado com células posicionadas.

Testar só contra PDF gerado pelo projeto pode, portanto, mascarar esse tipo
de falha. Isso reforça a necessidade de **validar contra PDF real do FUNSERV
(com dado fictício)** antes de considerar a Fase 2 encerrada.

### 6. Primeiro teste com PDF real

Documento: `FUNSERV_Ata_Conselho_Fiscal_DADOS_FICTICIOS_TESTE.pdf` — ata de
conselho fiscal com estrutura real do FUNSERV e dados fictícios, 4 páginas.
Fica em `tests/fixtures/pdf_manual/`, pasta **fora do controle de versão**
(coberta pelo `*.pdf` do `.gitignore`); o relatório abaixo é o registro do
que se viu, já que o arquivo não acompanha o repositório.

**Resultado.** `process_pdf` com todos os detectores da Fase 1 devolveu
**17 entidades corretas — 10 CPF e 7 EMAIL —, zero falso positivo e zero
falso negativo** nos padrões esperados. Os sete CPFs no formato
`(email, CPF 529.982.247-25)` saíram ancorados (`context='CPF'`, 0.99); os
e-mails, todos os sete, detectados. Foram corretamente ignorados: os três
nomes em texto corrido (ainda não há detector de NOME), os IPs `192.0.2.x`,
as coordenadas `-23.5000 / -47.4500`, o hash SHA-256 de 64 caracteres e o
identificador `TESTE-FUNSERV-2026-0001`. Páginas 1 e 2 sem nenhuma marca.

**Limitação identificada — mesma categoria do cabeçalho de coluna (item 4).**
A janela de âncora só enxerga a própria linha de texto (ou a anterior, quando
o valor abre a linha). Dois padrões de documento real ficam fora do alcance
de qualquer detector que dependa **só de âncora**, e não de DV:

- **cabeçalho de coluna** — rótulo numa linha, valores nas linhas abaixo;
- **bloco de assinatura** — nome numa linha, identificador sozinho na linha
  seguinte, sem rótulo nenhum. Foi o caso dos três CPFs restantes desta ata
  (`Assinatura fictícia` / `Nome do signatário` / `168.995.350-09`), que
  saíram com 0.95 e sem `context`.

CPF é resistente a isso porque tem DV e não depende de âncora para ser
aceito — os três do bloco de assinatura foram detectados normalmente. RG,
CNH e outros tipos sem DV forte, se aparecerem nesse padrão, **não seriam
detectados hoje**. Fica como pendência para quando o padrão aparecer com
frequência que justifique um **detector estrutural de bloco de assinatura**:
reconhecer nome + linha numérica curta logo abaixo e propagar uma âncora
sintética para ela.

**Achado positivo.** A regra de fronteira alfanumérica (Fase 1c,
`_ANTES`/`_DEPOIS` em `src/redator/detectors/_fronteiras.py`) generalizou
bem para o hash SHA-256 e para o identificador alfanumérico do documento
real, **sem nenhum ajuste**: nenhum dos dois disparou falso positivo de
CPF, CNH ou PIS por coincidência de dígitos. As corridas numéricas dentro
deles estão coladas a letras ou a `letra-`, e a fronteira as descarta antes
mesmo de o DV ser consultado.

## Fase 2.5 — OCR

### 1. Teste de degradação: o que sobrevive e o que quebra

Três imagens sintéticas do mesmo contrato fictício, em graus crescentes de
degradação de scanner/foto — rotação, ruído gaussiano, blur e recompressão
JPEG —, com CPF, CNPJ, RG, CEP, telefone e e-mail.

**Dígitos com pontuação sobrevivem bem**, mesmo no ruído forte: CPF, os dois
CEPs e o telefone saíram idênticos e ancorados nas três variantes. O dígito
verificador (CPF, CNPJ) ou o formato rígido (CEP, telefone) tolera pequeno
erro de leitura — há redundância suficiente para o candidato ainda fechar.

**O que quebra é caractere isolado de forma ambígua**, e quebra justamente
nos tipos que dependem de forma exata, sem DV para segurar:

- `@` lido como `&` derrubou o e-mail nas **três** variantes, inclusive na
  limpa (item 2);
- um espaço fantasma — `42 .815.739-6` em vez de `42.815.739-6` — derrubou o
  RG no ruído forte;
- `CNPJ` lido como `CNP)` fez o CNPJ perder a âncora, mas **não** a detecção:
  o DV segurou o número com 0,95 e `context=None`. É a demonstração mais
  clara do que o DV compra — tipo validado sobrevive a rótulo corrompido.

Nenhum falso positivo em nenhuma variante: a fronteira alfanumérica e o DV
seguraram fragmentos como `047/2026` e `no 450`.

### 2. Falso negativo silencioso de e-mail: `@` lido como `&`

O achado mais sério, e o motivo de ele ser sério não é a troca em si — é que
**a confiança do OCR não protegia dela**. Na variante de ruído leve a palavra
corrompida saiu com confiança **61, acima do limiar de 60**, então não entrou
em `low_confidence_words`. O e-mail simplesmente desaparecia: nem detectado,
nem sinalizado para revisão. Para uma ferramenta que prioriza recall, é a
pior falha possível — pior que um falso positivo, que ao menos aparece.

Corrigido com um **segundo detector**
(`_DetectorEmailOcrAmbiguo`, em `src/redator/detectors/contato.py`), ativo só
quando a origem é OCR, que aceita `&` onde o padrão estrito exige `@`. É
estritamente aditivo: os dois nunca casam o mesmo trecho, porque um exige o
caractere que o outro proíbe. Toda entidade que sai por essa via vem com
`confidence=0.5`, `requires_review=True` e `context="email_ocr_ambiguo"`,
**sempre e independentemente da confiança que o OCR reportou** — se um
caractere já veio trocado, os outros podem ter vindo também, e o padrão não
tem como ver isso.

O caminho de PDF nativo **não muda**. Ali um `&` no lugar de `@` é erro de
digitação do próprio documento, não degradação de leitura, e não deve ser
tratado como candidato a e-mail.

### 3. RG em origem OCR: sempre para revisão

RG não tem dígito verificador, e o teste mostrou que a sua forma quebra fácil
com ruído de imagem. Por isso, quando a origem é OCR, toda entidade de RG sai
com `requires_review=True` — **mesmo com casamento limpo e âncora presente**.

A confiança não muda: se o match foi limpo e ancorado, ela continua 0,99. O
que o campo sinaliza é **fragilidade estrutural do tipo naquela origem**, não
incerteza daquela detecção específica. São duas afirmações diferentes, e
misturá-las na confiança apagaria a informação de que o match foi bom.

CPF e CNPJ **não** recebem essa marca: o DV já é rede de segurança suficiente.
A lista está em `redator.detectors.TIPOS_FRAGEIS_EM_OCR` e hoje contém só o
RG.

### 4. `origem_ocr` é campo do dado, não parâmetro do chamador

`PageExtraction.origem_ocr` (default `False`) diz se o texto veio de OCR.
`TesseractEngine` e `extract_pdf_scanned` o marcam sozinhos, e `process_pdf`
o lê da própria página para repassar a `detect_all`.

A alternativa seria um parâmetro em `process_pdf`, e ela foi descartada de
propósito: esquecer de passá-lo desligaria silenciosamente as duas proteções
dos itens 2 e 3 — e a falha seria invisível, que é exatamente o tipo de
problema que essas proteções existem para evitar. Marcado no dado, não há
como processar texto de OCR e deixar de tratá-lo como tal.

## Fase 3 — API de revisão

### 1. A API serve o valor real do dado, e isso define o resto

A interface de revisão mostra, no hover, o dado que está por baixo da tarja —
sem isso quem revisa não tem como julgar se a detecção está certa. Logo
`GET /documentos/{id}` devolve `texto_original` com CPF, e-mail e RG em texto
claro.

É decisão deliberada, e todas as restrições abaixo existem por causa dela:

- **nenhum CORS.** Não há `CORSMiddleware` no `app.py`, e acrescentar um é
  liberar que uma página de terceiro leia o conteúdo de um documento em
  revisão. Se algum dia a interface for servida de outra origem, a resposta é
  um proxy reverso na mesma origem, não uma lista de origens permitidas;
- **bind em `127.0.0.1` por default.** Rede interna exige `REDATOR_API_HOST`
  escrito à mão por quem opera, e `servir()` registra no log o que isso
  significa. Nunca `0.0.0.0` por conveniência;
- **`Cache-Control: no-store` em toda resposta.** Sem isso o dado
  sobreviveria ao TTL dentro do cache do navegador ou de um proxy, que é
  exatamente a retenção que o TTL existe para impedir;
- **nenhuma autenticação.** Fica de fora de propósito nesta fase: a API só
  escuta em loopback, e uma autenticação mal feita daria a sensação de
  proteção sem a proteção. Se o bind sair do loopback, autenticação passa a
  ser pré-requisito, não melhoria.

### 2. Armazenamento em disco, não dict em memória

A tarefa deixava a escolha aberta. O dict foi descartado por um motivo
estrutural, não de gosto: **a API e o worker RQ são processos diferentes**.
O worker escreve o resultado que a API precisa ler de volta, e um dict só
funcionaria se o processamento fosse síncrono — que é justamente o que a fila
existe para não ser.

Então cada job é um diretório sob `REDATOR_API_DIR` (default: um subdiretório
fixo do temp do sistema, **fora do repositório**), com `original.pdf`,
`estado.json` e, quando pronto, `resultado.json`.

**O texto extraído nunca é gravado.** Vive na memória do worker durante o
processamento e morre com ele. Era o maior volume de dado pessoal em repouso
e não havia razão para persistir — o que a interface precisa já está no
`resultado.json`, entidade a entidade.

**Limitação aceita:** não há bloqueio entre processos. As escritas são
atômicas (`os.replace`), então nunca se lê um JSON parcial, mas duas escritas
simultâneas no mesmo job resolveriam por última-a-escrever. Como cada job é
enfileirado uma única vez, o caso não ocorre hoje.

### 3. Expiração por duas vias, porque nenhuma basta sozinha

O TTL (default 30 min) é aplicado de duas formas ao mesmo tempo:

- **agendada** — `enqueue_in` marca `expirar_job` para o vencimento. Depende
  de `rq worker --with-scheduler`; sem o scheduler, o agendamento
  simplesmente nunca dispara, sem erro visível;
- **na leitura** — `Armazenamento.obter` destrói o que já venceu antes de
  responder, e o GET vira 404.

A segunda é a que garante que **nada vencido é servido**, mesmo com o
scheduler fora do ar. A primeira é a que garante que **nada abandonado fica
no disco**, para o job que ninguém mais lê. `purgar_expirados()` existe para
ser chamada por fora (cron, job periódico, mão) e cobre o mesmo buraco da
primeira sem depender do scheduler.

### 4. `job_id` validado por regex, porque vira nome de diretório

`job_id` é `uuid4().hex` e só é aceito nessa forma (`[0-9a-f]{32}`). A
validação não é cosmética: o id vira nome de diretório, e aceitar `..` ou
barra transformaria `GET /documentos/{job_id}` em leitura de caminho
arbitrário. Id malformado, job inexistente e job expirado devolvem todos
**404**, indistinguíveis de propósito.

### 5. OCR decidido pelo documento inteiro, não página a página

`extrair()` tenta `extract_pdf`; só se **todas** as páginas vierem sem texto
é que cai em `extract_pdf_scanned`. O critério é o documento inteiro porque
um PDF misto — capa digitalizada, miolo nativo — perderia o texto nativo se
fosse OCRado por causa da capa, e o OCR é ordens de grandeza mais caro.

**Consequência aceita:** num documento misto, as páginas que são só imagem
saem vazias. É da mesma família das limitações registradas na Fase 2 (itens 4
e 6): conhecida, medida e adiada até a frequência justificar o custo de um
critério por página.

### 6. Falha do worker vira estado, não exceção

`processar_documento` nunca propaga exceção: qualquer falha grava
`status=ERRO` com a mensagem no próprio job. Deixar a exceção subir mandaria
o job para a fila de falhas do RQ, onde a interface não o enxerga — e o
usuário veria o job parado em `PROCESSANDO` para sempre, que é pior que ver o
erro.

### 7. Testes sem Redis

A suíte usa um `rq.Queue` de verdade sobre `fakeredis`: o caminho de código
do RQ é o mesmo de produção, só o servidor é falso. Duas montagens, porque
as duas metades do assíncrono precisam ser observadas — `is_async=False` para
ver o resultado sem levantar worker, e `is_async=True` **sem worker** para
ver o estado que a interface enxerga entre o POST e o fim do processamento.

`enqueue_in` não executa em nenhuma das duas (o RQ o põe no
`ScheduledJobRegistry`, e quem dispara é o scheduler), então a expiração é
testada chamando `expirar_job` e `purgar_expirados` diretamente — que é
exatamente o que o scheduler faria.

### 8. Windows: o `Worker` padrão do RQ não roda, e a falha perde o job

Constatado ao subir a pilha de verdade nesta máquina, não em teste. O
`Worker` padrão do RQ isola cada job num processo filho criado com
`os.fork()`, que **não existe no Windows**. O worker sobe, escuta, aceita o
primeiro job e morre com
`AttributeError: module 'os' has no attribute 'fork'`.

O que torna isso pior que um crash comum: o job **já tinha saído da fila**
quando o worker morreu. Ninguém o reprocessa, e ele fica **preso em
`RECEBIDO` permanentemente** — a interface o mostra como "recebido, aguarde"
para sempre, sem erro em lugar nenhum. Não é o caminho do item 6: ali a
exceção é do processamento e vira `ERRO` visível; aqui o worker morre antes
de chegar ao nosso código, então não há quem escreva estado nenhum.

**Correção em ambiente Windows:** `--worker-class rq.SimpleWorker`, que
executa o job no próprio processo, sem fork.

**Custo aceito:** sem processo filho não há quem matar quando o
`job_timeout` (`TIMEOUT_PROCESSAMENTO`) estoura, e um job travado prende o
worker indefinidamente. **Em produção Linux usa-se o `Worker` padrão**, que
não tem essa limitação e faz o timeout valer de novo.

É diferença de ambiente de desenvolvimento, não de arquitetura: nada em
`redator.api` muda por causa disso.

### 9. O lock do scheduler do RQ falha em silêncio, e o TTL para de existir

O scheduler é quem dispara o que foi agendado — no nosso caso, o
`expirar_job` de **todo** job, ou seja, o TTL inteiro do item 3.

O lock do scheduler é adquirido **uma única vez, na subida do processo**, e
**a falha ao adquiri-lo é silenciosa**. Se um worker morre segurando o lock e
outro sobe antes de o lock expirar, o segundo worker **processa jobs
normalmente** e **nunca executa nada agendado** — sem erro, sem aviso, sem
nenhuma linha no log dizendo que o scheduler não subiu. Não há retentativa.

**O sintoma é uma falha de segurança, não de disponibilidade.** O TTL
configurado não dispara, e o dado pessoal **fica retido em disco além do
prazo prometido** — exatamente a retenção que o item 1 diz não existir. E
fica sem nenhum log de erro para denunciar: tudo parece saudável, os jobs são
processados, só a destruição nunca acontece.

Foi o que aconteceu aqui: o worker do item 8 morreu segurando o lock, o
substituto subiu 18 segundos depois, e jobs vencidos ficaram no disco
indefinidamente enquanto o worker parecia perfeito.

**Como verificar, sempre, ao subir o worker:** a linha

```
Acquired scheduler lock for redator
```

tem de aparecer no log da subida. **A ausência dela é o problema.** Se não
aparecer: mate todos os workers, espere o lock vencer (~1 min) e suba um só.

Vale registrar o que *não* é o problema: o scheduler **funciona no Windows**
(`RQScheduler` cai em `multiprocessing` com spawn quando não há fork).
Verificado com TTL de 60 s — o `expirar_job` agendado disparou e removeu o
diretório do disco sem nenhum GET envolvido, que é a prova de que a via
agendada trabalha sozinha. O que quase mascarou isso foi o lock órfão.

A via preguiçosa do item 3 (`Armazenamento.obter` destrói o vencido antes de
responder) continua sendo a rede de segurança: mesmo com o scheduler morto,
nada vencido chega a ser **servido**. O que se perde sem o scheduler é a
destruição do job que ninguém mais lê — e é por isso que as duas vias existem.

### 10. Redis local no Windows exige WSL2 com `redis-server` como serviço

Não há build oficial de Redis para Windows, e esta máquina não tem Docker
Desktop. O caminho é o WSL2 (Ubuntu), com `redis-server` instalado e
habilitado como serviço systemd.

O Redis fica em `127.0.0.1:6379` **dentro** do WSL e chega ao Windows no
mesmo endereço pelo encaminhamento de localhost do WSL2 — **sem abrir o
bind**. Isso não é detalhe de conveniência: um Redis sem senha guardando fila
de documento com dado pessoal não deve aceitar conexão de fora da máquina, e
`bind 0.0.0.0` faria exatamente isso.

Pegadinha operacional: **o WSL desliga sozinho quando fica ocioso e leva o
Redis junto**. O `systemctl enable` o traz de volta quando o WSL sobe, mas no
meio de uma sessão a conexão simplesmente cai.

Os passos exatos — instalação, verificação do alcance a partir do Windows, o
processo que segura o WSL aberto e os três comandos para subir a pilha —
estão no README, em **Desenvolvimento local: API, fila e worker**. Aqui fica
só o porquê; lá, o como.

### 11. Windows: `rmtree(ignore_errors=True)` pode não apagar nada, e ninguém saberia

Terceira falha silenciosa específica de Windows, na mesma família dos itens
8 e 9 (fork ausente, lock do scheduler): todas as três só aparecem rodando de
verdade nesta plataforma, e todas as três são silenciosas por padrão — o
sintoma é "tudo parece saudável" e o dado pessoal fica retido além do
prometido.

`Armazenamento.remover` apagava o diretório do job com
`shutil.rmtree(diretorio, ignore_errors=True)`. No Windows, `rmtree` pode
falhar mesmo com todo arquivo do nosso próprio código fechado corretamente
(`pymupdf.open` e o `anyio.open_file` do `FileResponse` de `/original` já
fecham em `finally`/`async with`) — o SO leva um instante a mais para
liberar o lock depois do `close()`, e nesse intervalo um antivírus ou
indexador que tenha aberto o arquivo para escanear pode segurá-lo por mais
alguns milissegundos. `ignore_errors=True` mascarava exatamente isso: a
função devolvia como se tivesse apagado — `not diretorio.exists()` também
dava `False` de forma consistente com "apaguei" — e o diretório inteiro
(PDF original incluso) ficava para trás, sem nenhum log denunciando.

Reproduzido de forma determinística (não é hipótese): abrir o
`original.pdf` de um job e chamar `remover` enquanto o handle está aberto
falha a apagar o diretório, silenciosamente, todas as vezes — e rodando a
suíte de testes em sequência (`tests/test_api.py`), isso batia em ~5-10% das
execuções de `test_job_vencido_nao_e_servido_mesmo_sem_scheduler` e de
`test_original_some_com_o_descarte`, cada uma abrindo e fechando o PDF (via
processamento síncrono ou via `/original`) pouco antes de o teste seguinte —
ou o próprio DELETE — tentar remover o mesmo diretório.

**Correção:** `_remover_com_retentativa` tenta `shutil.rmtree` (sem
`ignore_errors`) até 5 vezes com 0.1s entre tentativas — suficiente para a
folga do SO/antivírus, insuficiente para mascarar um problema de verdade. Se
o diretório ainda existir depois de esgotadas as tentativas, `remover`
levanta `ErroLimpeza` em vez de devolver um booleano que finge sucesso.

Cada chamador decide o que fazer com essa exceção, porque o significado é
diferente em cada caminho:

- `obter`/`ler_estado` (TTL vencido ou estado corrompido): o job já está
  logicamente morto — a resposta ao cliente é 404 de qualquer jeito. A
  exceção é capturada, vira **log crítico** (dado pessoal potencialmente
  retido além do TTL) e o job continua tratado como ausente. Não fazia
  sentido virar 500 aqui: quem pergunta por um job vencido não pode ver a
  diferença entre "nunca existiu" e "venceu", e uma falha de limpeza física
  não muda essa resposta.
- `DELETE /documentos/{id}`: o cliente pediu a destruição explicitamente —
  aqui fingir sucesso (204) seria pior que nos outros casos. Vira **500**,
  com log crítico, para o cliente saber que precisa tentar de novo.
- `purgar_expirados`: um job preso não entra na lista de removidos nem trava
  a varredura dos demais — fica para a próxima passada (ou para o próximo
  `obter`), e a falha é logada como crítica a cada tentativa malsucedida.
- `expirar_job` (o `expirar_job` do scheduler): a exceção **não é
  capturada** — sobe e o RQ marca o agendamento como falho no seu próprio
  registro, visível a quem opera. É background, sem cliente HTTP esperando;
  deixar o erro visível ali é melhor que inventar um retorno.

**Em produção Linux** o mesmo código de retentativa continua valendo — não é
específico de Windows, só *raramente necessário* lá, porque o SO libera o
lock de arquivo de forma mais previsível. Não custa nada mantê-lo: a
diferença é só quantas vezes, na prática, a segunda tentativa é chamada.

## Fase 3b — Perfil de redação

### 1. A decisão é só por tipo, e a exceção institucional ficou de fora

`redator.perfil` decide TARJAR ou PUBLICAR a partir de `PERFIL_PADRAO`, um
dict por `EntityType`. Três tipos são publicados — CNPJ, PROCESSO_CNJ e NOME —
e todo o resto é tarjado.

A exceção óbvia que **não** foi implementada: dado **institucional**. O
telefone da própria fundação no cabeçalho de um ofício é público, e deveria
sair publicado; hoje sai tarjado, igual ao celular de um cidadão. Ficou de fora
porque não há sinal que a sustente, e implementá-la sem sinal seria inventar
um.

### 2. Investigação: a `Entity` não tem como distinguir institucional de pessoal

Os campos de `Entity` são `type`, `start`, `end`, `text`, `confidence`,
`detector`, `validated`, `context` e `requires_review`. Nenhum carrega essa
informação, e os dois candidatos aparentes não servem:

- **`allowlist` do golden set é anotação de teste, não sinal de produção.**
  Existe só nos `.json` de `tests/fixtures/textos/` (o `doc_teste_1_oficio.json`
  marca CNPJ, CEP, telefone e e-mail da fundação como `allowlist: true`) e só é
  lido por `tests/test_golden_set.py`. Nenhum detector o produz; nenhum código
  em `src/` o conhece.
- **`context` é o rótulo da âncora, não uma classificação.** Medido no próprio
  ofício: o telefone precedido de `Telefone institucional:` sai com
  `context='Telefone'`; o telefone pessoal do contrato, precedido de
  `telefone`, sai com `context='telefone'`. A palavra decisiva é descartada no
  caminho — a âncora reconhece "telefone" e para ali. Classificar por
  `context` seria distinguir os dois pela **maiúscula**.

`tests/test_perfil.py::test_telefone_institucional_e_pessoal_sao_ambos_tarjados`
fixa essa ausência: os dois saem TARJAR, e o teste mostra que o rótulo está no
texto mas não chega à `Entity`. Se ele quebrar porque o institucional passou a
ser publicado, a primeira pergunta é de onde veio o sinal.

### 3. O caminho mais barato quando a exceção for retomada

O ofício já tem a pista literal: **`Telefone institucional:`**. Uma **âncora
composta** que reconheça esse rótulo específico (e seus pares —
`E-mail institucional:`, e o que mais aparecer em documento real) e gere um
**sinal próprio na `Entity`** — um campo novo, não `context` reaproveitado — é
a implementação mais direta. Com o sinal no dado, a regra entra dentro de
`decidir_acao`, antes da consulta ao perfil, e a assinatura não muda: é o mesmo
princípio de `origem_ocr` (Fase 2.5, item 4), marcado no dado para não haver
como esquecer de passá-lo.

`context` não deve ser o veículo, mesmo parecendo mais curto: ele alimenta a
confiança e a revisão, e misturar nele uma classificação faria o mesmo campo
responder a duas perguntas diferentes.

**Limite já visível dessa abordagem**, no mesmo ofício: o número aparece duas
vezes, e a segunda (`...ou pelo telefone (15) 3238-0000`) não tem rótulo
institucional nenhum. A âncora composta pegaria só a primeira. Propagar a
marca para outras ocorrências do mesmo valor no documento é uma segunda
decisão, com risco próprio — um número pessoal que coincida com um
institucional seria publicado junto —, e não deve vir embutida na primeira.

## Fase 4 — Redação real de PDF

### 1. `apply_redactions`: o default de `graphics` deixa forma vetorial sobreviver

> **Nota:** esta correção foi implementada e testada no commit anterior (`d7e063c`, limpeza de conteúdo — texto/imagem/gráfico/link); a menção aqui é recapitulação de contexto para o leitor entender o estado completo do módulo, não um achado novo da tarefa de limpeza de metadados.

Achado ao implementar, não hipótese de leitura de documentação. `redator.
redacao.redigir_pdf` marca cada entidade com `add_redact_annot` e aplica
`apply_redactions` por página — mas os três parâmetros dessa chamada
importam, e nenhum é o default do PyMuPDF:

- `images=PDF_REDACT_IMAGE_PIXELS` **é** o default, mas fica explícito de
  propósito: apaga só os pixels da imagem sob a área marcada, não a imagem
  inteira. Verificado com uma imagem de fundo 400×400 e uma redação de
  50×20 num canto — o resto da imagem sai intacto. Importa para o caso comum
  de um carimbo ou campo pequeno sobre uma página inteira digitalizada:
  `PDF_REDACT_IMAGE_REMOVE` faria a página toda sumir.
- `graphics=PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED`, e **não** o default
  (`REMOVE_IF_COVERED`) — aqui está o achado real. Reproduzido com o
  `redigir_pdf` de verdade: um retângulo desenhado exatamente nas mesmas
  coordenadas do bbox de um CPF (simulando uma tarja gráfica pré-existente,
  ou qualquer elemento decorativo posicionado sobre o texto) **sobrevivia**
  à redação com o default. `REMOVE_IF_COVERED` não considera bordas
  coincidentes como "cobertas" o suficiente — só forma estritamente contida
  com folga é removida. `REMOVE_IF_TOUCHED` resolve, ao custo de remover
  qualquer forma que apenas toque a área (mais agressivo). Para uma
  ferramenta cuja função é garantir que nada de dado pessoal sobreviva, esse
  é o lado seguro do erro.
- `text=PDF_REDACT_TEXT_REMOVE` é o comportamento central, sem ele não há
  redação — fica explícito só para os três aparecerem juntos.

**O que some de graça, sem parâmetro nenhum:** anotações que colidem com a
área marcada — inclusive um link (`/Annots` tipo `Link`) — são descartadas
por um mecanismo do PyMuPDF independente do `graphics`. Relevante para um
link de verificação (QR/URL) cuja área caia sob uma entidade tarjada.

`tests/test_redacao.py` tem os três testes que provam isso por inspeção
direta do PDF de saída (`get_drawings()`, pixel a pixel, `get_links()`), não
só por texto extraído — e o de forma vetorial falha de verdade se
`graphics` voltar ao default, não é teste vácuo.

### 2. Limpeza de metadados é incondicional, e cobre mais que os campos padrão

Adicionada como etapa dentro de `redigir_pdf`, depois das redações de
conteúdo e antes do save — não como módulo separado, e não como opção.

- **`/Info`, campos customizados inclusos.** Investigado antes de assumir:
  `doc.set_metadata({})` não edita campo por campo — com `/Info` já
  existente, ele substitui a referência inteira no trailer por `null`.
  Verificado gravando um campo fora do conjunto que `set_metadata` sequer
  sabe nomear (`doc.xref_set_key(info_xref, "CampoCustomizado", ...)`): ele
  desaparece do arquivo bruto depois do save com `garbage=4` — é o garbage
  collector do PyMuPDF descartando o objeto órfão, e cobre qualquer campo,
  não só os padrão. Não foi preciso varredura de xref adicional para `/Info`.
- **XMP**, ao contrário, recebeu a varredura: `del_xml_metadata()` cobre o
  caso referenciado pelo catálogo, mas um objeto `/Type /Metadata` solto
  (não referenciado dali) escaparia. A varredura de todo o xref, zerando
  qualquer objeto desse tipo, é a mesma técnica que `Document.scrub()` usa
  internamente — `scrub()` em si não foi adotado porque faz mais coisa fora
  de escopo (mexe em link, thumbnail, texto oculto).
- **`AcroForm` e todo widget — removidos por completo, nunca redigidos.**
  Decisão já tomada na fase de planejamento: um certificado de assinatura
  carrega nome e CPF do signatário em DER binário dentro do widget,
  invisível a qualquer extração de texto, e fora do alcance de
  `apply_redactions` (não é conteúdo de página). `page.delete_widget` em
  cada widget de cada página, mais a chave `/AcroForm` do catálogo anulada
  (`xref_set_key(..., "AcroForm", "null")` — mesma convenção que o próprio
  `scrub()` usa para `/Thumb`: o valor fica `null`, não a chave apagada, o
  que já basta para `is_form_pdf` virar `False`).
- **Anexos embutidos** e **JavaScript** (qualquer objeto `/S /JavaScript`
  em qualquer xref — ação de abertura, de campo, de widget) seguem o mesmo
  padrão de `scrub()`: sem exceção, sem parâmetro.

`RelatorioRedacao` ganhou quatro campos para auditoria
(`metadados_removidos`, `acroform_removido`, `anexos_removidos`,
`javascript_removido`). Registram o que **havia** e foi removido, não se o
passo rodou — ele sempre roda. `anexos_removidos == 0` significa "não havia
anexo", não "a limpeza falhou".

### 3. Optional Content (OCG/camadas): risco real, documentado, não tratado

Investigado a pedido explícito, para não passar batido. Uma camada
desligada por padrão (`doc.add_ocg(..., on=False)`) faz `page.get_text()` —
e portanto `extract_pdf`, e portanto todo detector deste projeto — devolver
texto vazio para o conteúdo daquela camada. Verificado empiricamente: o
mesmo texto, na mesma posição, aparece com a camada ligada e desaparece com
ela desligada.

A consequência é séria: uma entidade escondida numa camada assim **nunca
chega a ser detectada** — não é que a redação falhe nela, é que o pipeline
inteiro não a vê. O dado permanece no arquivo, alcançável por qualquer
leitor que ligue a camada, ou por um extrator de texto que (ao contrário do
PyMuPDF) ignore o estado padrão de OCG — o que muitos fazem.

**Por que não foi tratado agora:** nenhum PDF deste projeto — nem os
gerados pelo gerador de teste, nem os PDFs reais de ata/ofício usados na
suíte — usa Optional Content. Não há caso de uso real que justifique a
complexidade de "forçar todas as camadas ligadas antes de extrair para
detecção, mas preservar o estado original no resultado" (ou alternativa
equivalente) sem um documento real que precise disso. Fica registrado aqui,
não como lacuna silenciosa: se um PDF com camadas aparecer em produção,
`redigir_pdf` não é, hoje, defesa contra dado pessoal escondido nelas — e
`_verificar_optional_content` loga um aviso (nível `WARNING`) sempre que o
documento tem qualquer OCG, exatamente para essa lacuna não ficar muda.

### 4. Verificação pós-redação independente, e as três lacunas que ela expôs

`redator.verificacao.verificar_redacao` reabre o PDF de saída do zero e
procura o que sobrou em sete canais (texto, metadados, AcroForm, anexos,
JavaScript, Optional Content), sem parar no primeiro. `redigir_pdf` a chama
sozinho depois de salvar e devolve o resultado em
`RelatorioRedacao.verificacao`. Reprovado não apaga o arquivo (descartar é
de quem chama), mas cada vazamento vira log `CRITICAL`.

**Independência é regra de desenho, e virou teste.** A verificação não
importa nada de `redator.redacao` — `test_verificacao_nao_importa_nada_de_redacao`
lê o fonte e falha se isso mudar. O motivo apareceu na prática: a tarefa
pedia para reaproveitar a técnica de varredura de JavaScript da redação, e
essa técnica é justamente a que tem ponto cego. Reaproveitá-la teria deixado
a verificação cega ao mesmo bug. As técnicas de detecção são, de propósito,
diferentes e mais amplas que as de remoção.

**As três lacunas em `redacao.py`, todas verificadas com `redigir_pdf` real:**

1. **JavaScript inline sobrevive.** A remoção procura objetos cujo `/S` é
   `/JavaScript` no nível do xref. Uma ação aninhada em outro dicionário (ex.:
   o `/AA` de uma página) não é xref próprio, escapa, e o relatório ainda diz
   `javascript_removido=False`. A verificação lê o fonte de todo objeto e acusa
   `/JS` com conteúdo, onde quer que esteja.
2. **Anexo por anotação `FileAttachment` sobrevive.** A remoção limpa o name
   tree de anexos (`embfile_*`); a anotação é outro mecanismo, e
   `embfile_count()` dá zero com ela presente. O critério literal "`embfile_count()
   == 0`" aprovaria o documento. A verificação checa os dois.
3. **`/Info` dentro do catálogo sobrevive.** Fora do lugar padrão (que é o
   trailer), mas o MuPDF grava ali `/Producer` em todo PDF que cria — toda
   fixture do gerador tem. `doc.metadata` não enxerga, e a limpeza não o toca.
   Hoje só carrega a assinatura da biblioteca, não dado do documento. A
   verificação tolera `/Producer` sozinho ali (acusar seria falso positivo em
   todo PDF gerado pelo PyMuPDF) e acusa qualquer outra chave.

**Não corrigidas nesta tarefa**, que era de verificação: ficam acusadas, não
silenciosas. Um documento real com qualquer uma delas sai de `redigir_pdf`
com `verificacao.aprovado == False` e log `CRITICAL`. Os testes dessas três
verificam `verificar_redacao` direto sobre PDF montado à mão, e não via
`redigir_pdf` — assim não codificam o bug da redação e não quebram quando ele
for corrigido.

**Limites do canal de texto, aceitos:** só se acusa o que um detector
reconhece (meio CPF cortado por uma caixa mal posicionada não casa com
detector nenhum), e só entidade que corresponde a uma esperada TARJAR (mesmo
tipo e mesmo texto sem separador). A correspondência ignora página e posição
de propósito: o mesmo dado pessoal achado em qualquer página é vazamento.

**Os testes não são vácuos — conferido por sabotagem.** Cada um dos canais,
mais o filtro de PUBLICAR, a regex de JS e a checagem de `FileAttachment`,
foi anulado um de cada vez no código da verificação: todas as nove sabotagens
quebraram ao menos um teste. Os dois PDFs manuais da ata (`pdf_manual/`) saem
aprovados, com 17 entidades tarjadas cada.
