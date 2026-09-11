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
