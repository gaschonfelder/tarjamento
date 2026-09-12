/**
 * Uma página do PDF renderizada, com a camada de tarjas por cima.
 *
 * A escala é o elo entre os dois mundos: o PDF.js recebe `scale` e devolve um
 * viewport em CSS px; as bboxes da API estão em pontos. Como `largura`/
 * `altura` da API também estão em pontos, `pontos * escala = px` vale para os
 * dois, e é por isso que o overlay assenta sobre o canvas sem ajuste nenhum.
 *
 * O canvas é desenhado em `devicePixelRatio` para não sair borrado em tela
 * HiDPI, mas o seu tamanho CSS continua sendo o do viewport — o overlay não
 * enxerga essa diferença.
 */
import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { BBox, PaginaResponse } from '../types';
import type { Modo, Tarja } from '../state/revisao';
import EntidadeOverlay from './EntidadeOverlay';

interface Props {
  documento: PDFDocumentProxy;
  pagina: PaginaResponse;
  tarjas: Tarja[];
  escala: number;
  modo: Modo;
  selecionada: string | null;
  onVista: (id: string) => void;
  onSelecionar: (id: string | null) => void;
  onAlternarRejeicao: (id: string) => void;
  onRemoverManual: (id: string) => void;
  onAjustar: (id: string, indice: number, bbox: BBox) => void;
  onDesenhar: (pagina: number, bbox: BBox) => void;
}

/** Retângulo menor que isto (em px) é clique, não desenho. */
const ARRASTE_MINIMO_PX = 6;

export default function PaginaPdf({
  documento,
  pagina,
  tarjas,
  escala,
  modo,
  selecionada,
  onVista,
  onSelecionar,
  onAlternarRejeicao,
  onRemoverManual,
  onAjustar,
  onDesenhar,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const camadaRef = useRef<HTMLDivElement | null>(null);
  const inicioRef = useRef<{ x: number; y: number } | null>(null);
  const [rascunho, setRascunho] = useState<BBox | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  const largura = pagina.largura * escala;
  const altura = pagina.altura * escala;

  useEffect(() => {
    let cancelado = false;
    let tarefa: { cancel: () => void } | null = null;

    void (async () => {
      try {
        const pdfPagina = await documento.getPage(pagina.numero + 1);
        if (cancelado) return;

        const viewport = pdfPagina.getViewport({ scale: escala });
        const canvas = canvasRef.current;
        if (!canvas) return;

        // Se o PDF.js e o PyMuPDF discordarem do tamanho da página, o overlay
        // fica deslocado — e em silêncio. Melhor gritar no console.
        const difLargura = Math.abs(viewport.width - largura);
        const difAltura = Math.abs(viewport.height - altura);
        if (difLargura > 1 || difAltura > 1) {
          console.warn(
            `[redator] pagina ${pagina.numero}: PDF.js diz ${viewport.width}x${viewport.height}, ` +
              `a API diz ${largura}x${altura}. As tarjas podem sair deslocadas.`,
          );
        }

        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(viewport.width * dpr);
        canvas.height = Math.floor(viewport.height * dpr);
        canvas.style.width = `${viewport.width}px`;
        canvas.style.height = `${viewport.height}px`;

        tarefa = pdfPagina.render({
          canvas,
          viewport,
          ...(dpr !== 1 ? { transform: [dpr, 0, 0, dpr, 0, 0] } : {}),
        });
        await (tarefa as unknown as { promise: Promise<void> }).promise;
        if (!cancelado) setErro(null);
      } catch (e) {
        // `cancel()` rejeita a promessa de propósito quando o zoom muda no
        // meio do desenho; isso não é falha.
        if (cancelado) return;
        const nome = e instanceof Error ? e.name : '';
        if (nome === 'RenderingCancelledException') return;
        setErro(e instanceof Error ? e.message : 'falha ao renderizar a página');
      }
    })();

    return () => {
      cancelado = true;
      tarefa?.cancel();
    };
  }, [documento, pagina.numero, escala, largura, altura]);

  function pontosDoEvento(evento: React.PointerEvent<HTMLDivElement>): { x: number; y: number } {
    const caixa = camadaRef.current?.getBoundingClientRect();
    if (!caixa) return { x: 0, y: 0 };
    return {
      x: (evento.clientX - caixa.left) / escala,
      y: (evento.clientY - caixa.top) / escala,
    };
  }

  function aoPressionar(evento: React.PointerEvent<HTMLDivElement>) {
    if (modo !== 'desenhar' || evento.button !== 0) return;
    evento.preventDefault();
    evento.currentTarget.setPointerCapture(evento.pointerId);
    const p = pontosDoEvento(evento);
    inicioRef.current = p;
    setRascunho([p.x, p.y, p.x, p.y]);
  }

  function aoMover(evento: React.PointerEvent<HTMLDivElement>) {
    const inicio = inicioRef.current;
    if (!inicio) return;
    const p = pontosDoEvento(evento);
    setRascunho([
      Math.min(inicio.x, p.x),
      Math.min(inicio.y, p.y),
      Math.max(inicio.x, p.x),
      Math.max(inicio.y, p.y),
    ]);
  }

  function aoSoltar(evento: React.PointerEvent<HTMLDivElement>) {
    const inicio = inicioRef.current;
    inicioRef.current = null;
    if (!inicio || !rascunho) return;
    evento.currentTarget.releasePointerCapture(evento.pointerId);
    setRascunho(null);

    const [x0, y0, x1, y1] = rascunho;
    if ((x1 - x0) * escala < ARRASTE_MINIMO_PX || (y1 - y0) * escala < ARRASTE_MINIMO_PX) return;
    // Nunca deixa a tarja escapar da página: o backend só sabe tarjar dentro dela.
    onDesenhar(pagina.numero, [
      Math.max(0, x0),
      Math.max(0, y0),
      Math.min(pagina.largura, x1),
      Math.min(pagina.altura, y1),
    ]);
  }

  return (
    <section className="pagina" aria-label={`Página ${pagina.numero + 1}`}>
      <header className="pagina__cabecalho">
        <span className="pagina__numero">Página {pagina.numero + 1}</span>
        <span className="pagina__contagem">
          {tarjas.filter((t) => !t.rejeitada).length} de {tarjas.length} ativas
        </span>
      </header>

      <div className="pagina__palco" style={{ width: `${largura}px`, height: `${altura}px` }}>
        <canvas ref={canvasRef} className="pagina__canvas" />

        {erro && <div className="pagina__erro">Não consegui renderizar esta página: {erro}</div>}

        <div
          ref={camadaRef}
          className={`pagina__camada ${modo === 'desenhar' ? 'pagina__camada--desenhando' : ''}`}
          onPointerDown={aoPressionar}
          onPointerMove={aoMover}
          onPointerUp={aoSoltar}
          onPointerCancel={aoSoltar}
          onClick={() => onSelecionar(null)}
        >
          {tarjas.map((tarja) => (
            <EntidadeOverlay
              key={tarja.id}
              tarja={tarja}
              escala={escala}
              selecionada={selecionada === tarja.id}
              onVista={() => onVista(tarja.id)}
              onSelecionar={() => onSelecionar(tarja.id)}
              onAlternarRejeicao={() => onAlternarRejeicao(tarja.id)}
              onRemover={tarja.origem === 'manual' ? () => onRemoverManual(tarja.id) : null}
              onAjustar={(indice, bbox) => onAjustar(tarja.id, indice, bbox)}
            />
          ))}

          {rascunho && (
            <div
              className="tarja tarja--rascunho"
              style={{
                left: `${rascunho[0] * escala}px`,
                top: `${rascunho[1] * escala}px`,
                width: `${(rascunho[2] - rascunho[0]) * escala}px`,
                height: `${(rascunho[3] - rascunho[1]) * escala}px`,
              }}
            />
          )}
        </div>
      </div>
    </section>
  );
}
