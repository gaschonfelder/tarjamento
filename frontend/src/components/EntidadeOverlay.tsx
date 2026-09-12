/**
 * Uma tarja desenhada sobre a página: seus retângulos, as ações e o tooltip.
 *
 * Uma entidade pode ter MAIS DE UM retângulo — um valor que atravessa quebra
 * de linha rende um por linha, e pintar o vão entre eles seria tarjar o que
 * não é dado. Todos são desenhados; as ações ficam no primeiro.
 *
 * Geometria: as bboxes vêm em pontos da página e a escala converte para CSS
 * px. Todo cálculo de arraste faz o caminho inverso (dividir pela escala)
 * antes de gravar, para o estado guardar sempre pontos — independentes do
 * zoom em que o usuário estava.
 */
import { useRef, useState } from 'react';
import type { CSSProperties, PointerEvent as PointerEventoReact } from 'react';
import type { BBox } from '../types';
import { aparenciaDe, type Tarja } from '../state/revisao';

type Canto = 'nw' | 'ne' | 'sw' | 'se';

const CANTOS: Canto[] = ['nw', 'ne', 'sw', 'se'];

/** Menor lado de uma tarja, em pontos. Abaixo disso vira um clique perdido. */
const LADO_MINIMO = 4;

interface Props {
  tarja: Tarja;
  escala: number;
  selecionada: boolean;
  onVista: () => void;
  onSelecionar: () => void;
  onAlternarRejeicao: () => void;
  onRemover: (() => void) | null;
  onAjustar: (indice: number, bbox: BBox) => void;
}

function estiloDe(bbox: BBox, escala: number): CSSProperties {
  const [x0, y0, x1, y1] = bbox;
  return {
    left: `${x0 * escala}px`,
    top: `${y0 * escala}px`,
    width: `${(x1 - x0) * escala}px`,
    height: `${(y1 - y0) * escala}px`,
  };
}

function mover(bbox: BBox, canto: Canto, dx: number, dy: number): BBox {
  let [x0, y0, x1, y1] = bbox;
  if (canto === 'nw' || canto === 'sw') x0 += dx;
  else x1 += dx;
  if (canto === 'nw' || canto === 'ne') y0 += dy;
  else y1 += dy;

  // Normaliza: arrastar um canto para além do oposto inverte as bordas, e o
  // retângulo continua válido — é o comportamento que se espera de um editor.
  const [ex0, ex1] = x0 <= x1 ? [x0, x1] : [x1, x0];
  const [ey0, ey1] = y0 <= y1 ? [y0, y1] : [y1, y0];
  return [ex0, ey0, Math.max(ex1, ex0 + LADO_MINIMO), Math.max(ey1, ey0 + LADO_MINIMO)];
}

export default function EntidadeOverlay({
  tarja,
  escala,
  selecionada,
  onVista,
  onSelecionar,
  onAlternarRejeicao,
  onRemover,
  onAjustar,
}: Props) {
  const [sobre, setSobre] = useState(false);
  const arraste = useRef<{ x: number; y: number; original: BBox; indice: number; canto: Canto } | null>(
    null,
  );

  const aparencia = aparenciaDe(tarja);
  const ativa = !tarja.rejeitada;
  const mostrarTooltip = sobre && ativa && arraste.current === null;

  function aoEntrar() {
    setSobre(true);
    // "Visto" é marcado no hover porque é aqui que o valor real aparece —
    // o hover É o ato de revisar, não um efeito colateral dele.
    onVista();
  }

  function iniciarArraste(
    evento: PointerEventoReact<HTMLDivElement>,
    indice: number,
    canto: Canto,
  ) {
    const bbox = tarja.bboxes[indice];
    if (!bbox) return;
    evento.stopPropagation();
    evento.preventDefault();
    evento.currentTarget.setPointerCapture(evento.pointerId);
    arraste.current = { x: evento.clientX, y: evento.clientY, original: bbox, indice, canto };
  }

  function aoArrastar(evento: PointerEventoReact<HTMLDivElement>) {
    const atual = arraste.current;
    if (!atual) return;
    const dx = (evento.clientX - atual.x) / escala;
    const dy = (evento.clientY - atual.y) / escala;
    onAjustar(atual.indice, mover(atual.original, atual.canto, dx, dy));
  }

  function encerrarArraste(evento: PointerEventoReact<HTMLDivElement>) {
    if (!arraste.current) return;
    evento.currentTarget.releasePointerCapture(evento.pointerId);
    arraste.current = null;
  }

  return (
    <>
      {tarja.bboxes.map((bbox, indice) => {
        const primeiro = indice === 0;
        const classes = [
          'tarja',
          `tarja--${aparencia}`,
          tarja.rejeitada ? 'tarja--rejeitada' : '',
          selecionada ? 'tarja--selecionada' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <div
            key={`${tarja.id}-${indice}`}
            {...(primeiro ? { id: `tarja-${tarja.id}` } : {})}
            className={classes}
            style={estiloDe(bbox, escala)}
            onPointerEnter={aoEntrar}
            onPointerLeave={() => setSobre(false)}
            onClick={(e) => {
              e.stopPropagation();
              onSelecionar();
            }}
          >
            {/* Sinaliza "confiável, mas sem âncora textual por perto". O sinal
                PERMANENTE deste estado é a borda dupla; o badge só aparece no
                hover porque, em tabela densa, uma bolinha por entidade cobre o
                texto vizinho e atrapalha justamente quem está conferindo. */}
            {primeiro && aparencia === 'sem_contexto' && !tarja.rejeitada && (sobre || selecionada) && (
              <span className="tarja__marca" title="Validado por dígito verificador, sem rótulo no texto ao lado">
                ?
              </span>
            )}

            {primeiro && (sobre || selecionada) && (
              <div className="tarja__acoes" onPointerEnter={aoEntrar}>
                <button
                  type="button"
                  className="tarja__botao"
                  title={tarja.rejeitada ? 'Restaurar esta tarja' : 'Rejeitar esta tarja'}
                  onClick={(e) => {
                    e.stopPropagation();
                    onAlternarRejeicao();
                  }}
                >
                  {tarja.rejeitada ? '↺' : '×'}
                </button>
                {onRemover && (
                  <button
                    type="button"
                    className="tarja__botao"
                    title="Apagar esta tarja manual"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemover();
                    }}
                  >
                    {'␡'}
                  </button>
                )}
              </div>
            )}

            {/* Alças só na seleção: 17 entidades com 4 alças cada viraria ruído. */}
            {selecionada &&
              CANTOS.map((canto) => (
                <div
                  key={canto}
                  className={`tarja__alca tarja__alca--${canto}`}
                  onPointerDown={(e) => iniciarArraste(e, indice, canto)}
                  onPointerMove={aoArrastar}
                  onPointerUp={encerrarArraste}
                  onPointerCancel={encerrarArraste}
                />
              ))}

            {primeiro && mostrarTooltip && (
              <div className="tarja__tooltip" role="tooltip">
                <strong>{tarja.type}</strong>
                {tarja.textoOriginal !== null ? (
                  <span className="tarja__valor">{tarja.textoOriginal}</span>
                ) : (
                  <span className="tarja__valor tarja__valor--ausente">
                    área marcada à mão — sem texto associado
                  </span>
                )}
                <span className="tarja__meta">
                  {tarja.confidence !== null ? `confiança ${tarja.confidence.toFixed(2)}` : 'manual'}
                  {' · '}
                  {tarja.context !== null ? `âncora "${tarja.context}"` : 'sem âncora'}
                  {tarja.requiresReview ? ' · requer revisão' : ''}
                </span>
              </div>
            )}
          </div>
        );
      })}
    </>
  );
}
