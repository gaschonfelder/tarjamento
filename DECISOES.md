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
