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
import type { BBox, JobResponse } from '../types';
import {
  ESTADO_INICIAL,
  montarPayload,
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
  const [consolidado, setConsolidado] = useState<number | null>(null);

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

  function confirmar() {
    const payload = montarPayload(job.id, estado.tarjas);
    // A exportação não existe no backend (Fase 3/4). O contrato fica no
    // console para conferência — nenhuma chamada é feita.
    console.info('[redator] payload de exportação consolidado:', payload);
    console.info('[redator] JSON:', JSON.stringify(payload, null, 2));
    setConsolidado(payload.tarjas.length);
    setResumoAberto(false);
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

            <p className="modal__nota">
              A exportação ainda não existe no backend. Confirmar consolida a lista e imprime o
              payload no console do navegador.
            </p>

            <div className="modal__acoes">
              <button type="button" className="botao" onClick={() => setResumoAberto(false)}>
                Voltar e revisar
              </button>
              <button type="button" className="botao botao--primario" onClick={confirmar}>
                {resumo.pendentes > 0 ? 'Confirmar mesmo assim' : 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {consolidado !== null && (
        <div className="faixa faixa--sucesso" role="status">
          Lista consolidada: <strong>{consolidado}</strong> tarja(s). O payload que seria enviado
          para exportação está no console do navegador.
          <button type="button" className="botao botao--pequeno" onClick={() => setConsolidado(null)}>
            Fechar
          </button>
        </div>
      )}
    </div>
  );
}
