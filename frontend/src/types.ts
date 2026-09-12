/**
 * Espelho dos schemas Pydantic de `src/redator/api/schemas.py`.
 *
 * Os nomes são os do backend, em snake_case, sem tradução: o que chega da
 * rede fica exatamente como chegou. A conversão para o modelo de trabalho da
 * tela (`Tarja`, em `state/revisao.ts`) acontece num lugar só, e é lá que os
 * campos ganham nome de front.
 */

/** `(x0, y0, x1, y1)` em PONTOS da página, origem no canto superior esquerdo. */
export type BBox = [number, number, number, number];

export type JobStatus = 'recebido' | 'processando' | 'pronto' | 'erro';

export interface EntidadeResponse {
  id: string;
  type: string;
  confidence: number;
  context: string | null;
  requires_review: boolean;
  validated: boolean;
  bboxes: BBox[];
  /** O VALOR REAL do dado. É o que o hover mostra por baixo da tarja. */
  texto_original: string;
  pagina: number;
}

export interface PaginaResponse {
  numero: number;
  /** Em pontos. É a mesma unidade das bboxes — daí sair a escala do overlay. */
  largura: number;
  altura: number;
  entidades: EntidadeResponse[];
}

export interface JobResponse {
  id: string;
  status: JobStatus;
  progresso: number | null;
  erro: string | null;
  /** Só vem preenchido em `pronto`. `null` != `[]` (documento sem entidade). */
  paginas: PaginaResponse[] | null;
  expira_em: string;
}
