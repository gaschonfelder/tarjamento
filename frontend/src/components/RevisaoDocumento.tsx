/**
 * A tela de revisão: PDF renderizado, tarjas por cima, painel e finalização.
 *
 * O PDF vem do `File` que o usuário escolheu, que já está no browser — não é
 * pedido de volta à API. Além de poupar um download, isso mantém o PDF fora
 * da rede: a API já devolve os valores detectados, não precisa devolver o
 * documento inteiro também.
 */
import { useEffect, useMemo, useReducer, useState } from 'react';
import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentLoadingTask,
  type PDFDocumentProxy,
} from 'pdfjs-dist';
import trabalhadorUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { ErroApi, ExportacaoIncompleta, VerificacaoReprovada, exportarDocumento } from '../api/client';
import type { BBox, EntidadeFaltando, JobResponse } from '../types';
import {
  ESTADO_INICIAL,
  montarDecisoes,
  reduzir,
  resumir,
  type Modo,
} from '../state/revisao';
import PaginaPdf from './PaginaPdf';
import PainelResumo from './PainelResumo';

GlobalWorkerOptions.workerSrc = trabalhadorUrl;

const ESCALA_MINIMA = 0.5;
const ESCALA_MAXIMA = 3;
/** Largura-alvo da página na tela, em px, para a escala inicial. */
const LARGURA_ALVO = 820;

interface Props {
  job: JobResponse;
  arquivo: File;
  onDescartar: () => void;
}

/** `<nome original>_redigido.pdf` — a extensão original, se houver, não dobra. */
function nomeExportado(nomeOriginal: string): string {
  const semExtensao = nomeOriginal.replace(/\.pdf$/i, '') || 'documento';
  return `${semExtensao}_redigido.pdf`;
}

/**
 * Dispara o download de um blob no browser, sem navegar a página.
 *
 * O sandbox de artefatos bloqueia isso, mas esta é a aplicação real rodando
 * no navegador do usuário, não um artefato — o padrão `<a download>` + URL de
 * objeto é o jeito correto aqui.
 */
function baixar(blob: Blob, nomeArquivo: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = nomeArquivo;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function RevisaoDocumento({ job, arquivo, onDescartar }: Props) {
  const paginas = useMemo(() => job.paginas ?? [], [job.paginas]);

  const [estado, despachar] = useReducer(reduzir, ESTADO_INICIAL);
  const [documento, setDocumento] = useState<PDFDocumentProxy | null>(null);
  const [erroPdf, setErroPdf] = useState<string | null>(null);
  const [escala, setEscala] = useState(() => {
    const primeira = paginas[0];
    if (!primeira) return 1;
    return Math.min(ESCALA_MAXIMA, Math.max(ESCALA_MINIMA, LARGURA_ALVO / primeira.largura));
  });
  const [resumoAberto, setResumoAberto] = useState(false);
  const [exportando, setExportando] = useState(false);
  const [erroExportacao, setErroExportacao] = useState<string | null>(null);
  const [faltandoRevisao, setFaltandoRevisao] = useState<EntidadeFaltando[] | null>(null);

  // As tarjas nascem das páginas da API, uma vez.
  useEffect(() => {
    despachar({ tipo: 'carregar', paginas });
  }, [paginas]);

  // O documento PDF.js, a partir do arquivo local. Quem se destrói é a
  // TAREFA de carregamento (ela é a dona do worker), não o documento.
  useEffect(() => {
    let cancelado = false;
    let tarefa: PDFDocumentLoadingTask | null = null;

    void (async () => {
      try {
        const dados = await arquivo.arrayBuffer();
        if (cancelado) return;
        tarefa = getDocument({ data: new Uint8Array(dados) });
        const aberto = await tarefa.promise;
        if (cancelado) return;
        setDocumento(aberto);
      } catch (e) {
        if (!cancelado) setErroPdf(e instanceof Error ? e.message : 'falha ao abrir o PDF');
      }
    })();

    return () => {
      cancelado = true;
      void tarefa?.destroy();
    };
  }, [arquivo]);

  // Selecionar pelo painel leva a página até a tarja.
  useEffect(() => {
    if (!estado.selecionada) return;
    const alvo = document.getElementById(`tarja-${estado.selecionada}`);
    alvo?.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }, [estado.selecionada]);

  const resumo = useMemo(() => resumir(estado.tarjas), [estado.tarjas]);

  function ajustarZoom(nova: number) {
    setEscala(Math.min(ESCALA_MAXIMA, Math.max(ESCALA_MINIMA, Number(nova.toFixed(2)))));
  }

  async function confirmar() {
    setExportando(true);
    setErroExportacao(null);
    setFaltandoRevisao(null);
    try {
      const blob = await exportarDocumento(job.id, montarDecisoes(estado.tarjas));
      baixar(blob, nomeExportado(arquivo.name));
      // O job já foi destruído no servidor ao servir o download: só resta
      // limpar o estado local e voltar para a tela de upload.
      setResumoAberto(false);
      onDescartar();
    } catch (e) {
      if (e instanceof ExportacaoIncompleta) {
        setFaltandoRevisao(e.faltando);
      } else if (e instanceof VerificacaoReprovada) {
        setErroExportacao(e.message);
      } else {
        setErroExportacao(
          e instanceof ErroApi ? e.message : 'Não consegui falar com a API para exportar.',
        );
      }
    } finally {
      setExportando(false);
    }
  }

  if (erroPdf) {
    return (
      <div className="aviso aviso--erro">
        <p>Não consegui abrir este PDF no navegador: {erroPdf}</p>
        <button type="button" className="botao" onClick={onDescartar}>
          Voltar
        </button>
      </div>
    );
  }

  const modoAtual: Modo = estado.modo;

  return (
    <div className="revisao">
      <main className="revisao__paginas">
        {!documento && <p className="revisao__carregando">Abrindo o documento…</p>}

        {documento &&
          paginas.map((pagina) => (
            <PaginaPdf
              key={pagina.numero}
              documento={documento}
              pagina={pagina}
              tarjas={estado.tarjas.filter((t) => t.pagina === pagina.numero)}
              escala={escala}
              modo={modoAtual}
              selecionada={estado.selecionada}
              onVista={(id) => despachar({ tipo: 'marcarVista', id })}
              onSelecionar={(id) => despachar({ tipo: 'selecionar', id })}
              onAlternarRejeicao={(id) => despachar({ tipo: 'alternarRejeicao', id })}
              onRemoverManual={(id) => despachar({ tipo: 'removerManual', id })}
              onAjustar={(id, indice, bbox: BBox) =>
                despachar({ tipo: 'ajustarBBox', id, indice, bbox })
              }
              onDesenhar={(numero, bbox) =>
                despachar({ tipo: 'adicionarManual', pagina: numero, bbox })
              }
            />
          ))}
      </main>

      <PainelResumo
        resumo={resumo}
        tarjas={estado.tarjas}
        selecionada={estado.selecionada}
        modo={modoAtual}
        escala={escala}
        onSelecionar={(id) => despachar({ tipo: 'selecionar', id })}
        onAlternarModo={() =>
          despachar({ tipo: 'definirModo', modo: modoAtual === 'desenhar' ? 'navegar' : 'desenhar' })
        }
        onZoom={ajustarZoom}
        onFinalizar={() => setResumoAberto(true)}
        onDescartar={onDescartar}
      />

      {resumoAberto && (
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="titulo-resumo">
          <div className="modal__caixa">
            <h2 id="titulo-resumo">Finalizar revisão</h2>

            <ul className="modal__numeros">
              <li>
                <strong>{resumo.ativas}</strong> tarja(s) serão aplicadas
              </li>
              <li>
                <strong>{resumo.rejeitadas}</strong> rejeitada(s)
              </li>
              <li>
                <strong>{resumo.sinalizadas}</strong> sinalizada(s) para revisão
              </li>
              {resumo.manuais > 0 && (
                <li>
                  <strong>{resumo.manuais}</strong> marcada(s) à mão
                </li>
              )}
            </ul>

            {resumo.pendentes > 0 ? (
              <div className="aviso aviso--atencao">
                <p>
                  <strong>{resumo.pendentes}</strong> tarja(s) sinalizadas para revisão ainda não
                  foram abertas. Elas são justamente as que o detector considera frágeis — vale
                  olhar cada uma antes de confirmar.
                </p>
              </div>
            ) : (
              <p className="modal__ok">Todas as tarjas sinalizadas foram revisadas.</p>
            )}

            {faltandoRevisao && (
              <div className="aviso aviso--erro">
                <p>
                  O servidor recusou a exportação: faltou decisão para{' '}
                  <strong>{faltandoRevisao.length}</strong> tarja(s) que ele ainda conhece. Nada
                  foi perdido — a revisão continua como estava.
                </p>
                <ul>
                  {faltandoRevisao.map((f) => (
                    <li key={f.entidade_id}>
                      {f.type} · página {f.pagina + 1}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {erroExportacao && (
              <div className="aviso aviso--erro">
                <p>
                  <strong>A exportação falhou — este documento NÃO deve ser considerado seguro.</strong>{' '}
                  {erroExportacao}
                </p>
              </div>
            )}

            <p className="modal__nota">
              Confirmar redige o documento de verdade no servidor e baixa o PDF pronto. O job é
              destruído no servidor assim que o download começa — esta é a única chance de exportar
              esta revisão.
            </p>

            <div className="modal__acoes">
              <button
                type="button"
                className="botao"
                onClick={() => setResumoAberto(false)}
                disabled={exportando}
              >
                Voltar e revisar
              </button>
              <button
                type="button"
                className="botao botao--primario"
                onClick={() => void confirmar()}
                disabled={exportando}
              >
                {exportando
                  ? 'Exportando…'
                  : resumo.pendentes > 0
                    ? 'Confirmar mesmo assim'
                    : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
