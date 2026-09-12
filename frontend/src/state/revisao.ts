/**
 * O estado da revisão: a lista de tarjas e o que o usuário fez com cada uma.
 *
 * Módulo a mais em relação à estrutura pedida, e pela mesma razão de sempre:
 * `RevisaoDocumento.tsx` já cuida de PDF.js, zoom, modos e o modal de
 * finalização; pôr o reducer lá dentro faria dele o arquivo onde tudo mora.
 *
 * A `Tarja` é o modelo de TRABALHO, diferente do `EntidadeResponse` que chega
 * da API: ela carrega o que só existe nesta tela — rejeitada, vista,
 * ajustada, origem — e aceita coisas que a API nunca produz, como uma tarja
 * manual sem confiança e sem texto por trás.
 */
import type { BBox, EntidadeResponse, PaginaResponse } from '../types';

export type Origem = 'api' | 'manual';

/** Tipo sintético das tarjas que o usuário desenha à mão. */
export const TIPO_MANUAL = 'MANUAL';

export interface Tarja {
  id: string;
  type: string;
  pagina: number;
  bboxes: BBox[];
  /** `null` em tarja manual: o front não detectou nada, o usuário apontou. */
  confidence: number | null;
  context: string | null;
  requiresReview: boolean;
  validated: boolean;
  /**
   * `null` em tarja manual — e isso não é um buraco a preencher: o front só
   * teve acesso à ÁREA marcada, nunca ao texto por baixo dela. Quem tem o
   * texto é o backend, e ele não foi consultado sobre esse retângulo.
   */
  textoOriginal: string | null;
  origem: Origem;
  rejeitada: boolean;
  /** O usuário já olhou esta tarja (hover ou clique). Alimenta o aviso final. */
  vista: boolean;
  /** Alguma bbox foi redimensionada à mão. */
  ajustada: boolean;
}

/**
 * Como a tarja é pintada. A ordem das regras é a da especificação:
 * `requires_review` ganha de tudo, independente da confiança.
 */
export type Aparencia = 'padrao' | 'sem_contexto' | 'revisao' | 'manual';

export const CONFIANCA_ALTA = 0.9;

export function aparenciaDe(tarja: Tarja): Aparencia {
  if (tarja.requiresReview) return 'revisao';
  if (tarja.origem === 'manual') return 'manual';
  if (tarja.confidence !== null && tarja.confidence >= CONFIANCA_ALTA && tarja.context === null) {
    // Achado por validador (dígito verificador), sem âncora textual por
    // perto — o CPF em bloco de assinatura é o caso típico. Confiável, mas
    // sem nada no texto que confirme o que ele é.
    return 'sem_contexto';
  }
  return 'padrao';
}

export type Modo = 'navegar' | 'desenhar';

export interface EstadoRevisao {
  tarjas: Tarja[];
  selecionada: string | null;
  modo: Modo;
}

export type AcaoRevisao =
  | { tipo: 'carregar'; paginas: PaginaResponse[] }
  | { tipo: 'alternarRejeicao'; id: string }
  | { tipo: 'marcarVista'; id: string }
  | { tipo: 'selecionar'; id: string | null }
  | { tipo: 'definirModo'; modo: Modo }
  | { tipo: 'adicionarManual'; pagina: number; bbox: BBox }
  | { tipo: 'ajustarBBox'; id: string; indice: number; bbox: BBox }
  | { tipo: 'removerManual'; id: string };

export const ESTADO_INICIAL: EstadoRevisao = {
  tarjas: [],
  selecionada: null,
  modo: 'navegar',
};

function daApi(entidade: EntidadeResponse): Tarja {
  return {
    id: entidade.id,
    type: entidade.type,
    pagina: entidade.pagina,
    bboxes: entidade.bboxes,
    confidence: entidade.confidence,
    context: entidade.context,
    requiresReview: entidade.requires_review,
    validated: entidade.validated,
    textoOriginal: entidade.texto_original,
    origem: 'api',
    rejeitada: false,
    vista: false,
    ajustada: false,
  };
}

let contadorManual = 0;

function novaManual(pagina: number, bbox: BBox): Tarja {
  contadorManual += 1;
  return {
    id: `manual-${contadorManual}-${Date.now().toString(36)}`,
    type: TIPO_MANUAL,
    pagina,
    bboxes: [bbox],
    confidence: null,
    context: null,
    requiresReview: false,
    validated: false,
    textoOriginal: null,
    origem: 'manual',
    rejeitada: false,
    // Nasce vista: quem a desenhou acabou de olhar para ela.
    vista: true,
    ajustada: false,
  };
}

function mapear(tarjas: Tarja[], id: string, f: (t: Tarja) => Tarja): Tarja[] {
  return tarjas.map((t) => (t.id === id ? f(t) : t));
}

export function reduzir(estado: EstadoRevisao, acao: AcaoRevisao): EstadoRevisao {
  switch (acao.tipo) {
    case 'carregar':
      return {
        ...ESTADO_INICIAL,
        tarjas: acao.paginas.flatMap((p) => p.entidades.map(daApi)),
      };

    case 'alternarRejeicao':
      return {
        ...estado,
        // Rejeitar também conta como ter olhado: a decisão foi tomada.
        tarjas: mapear(estado.tarjas, acao.id, (t) => ({
          ...t,
          rejeitada: !t.rejeitada,
          vista: true,
        })),
      };

    case 'marcarVista': {
      const alvo = estado.tarjas.find((t) => t.id === acao.id);
      if (!alvo || alvo.vista) return estado; // evita re-render a cada hover
      return { ...estado, tarjas: mapear(estado.tarjas, acao.id, (t) => ({ ...t, vista: true })) };
    }

    case 'selecionar':
      if (estado.selecionada === acao.id) return estado;
      return { ...estado, selecionada: acao.id };

    case 'definirModo':
      return { ...estado, modo: acao.modo, selecionada: null };

    case 'adicionarManual': {
      const tarja = novaManual(acao.pagina, acao.bbox);
      return {
        ...estado,
        tarjas: [...estado.tarjas, tarja],
        selecionada: tarja.id,
        // Uma tarja por vez: volta a navegar em vez de desenhar em série.
        modo: 'navegar',
      };
    }

    case 'ajustarBBox':
      return {
        ...estado,
        tarjas: mapear(estado.tarjas, acao.id, (t) => ({
          ...t,
          bboxes: t.bboxes.map((b, i) => (i === acao.indice ? acao.bbox : b)),
          ajustada: true,
          vista: true,
        })),
      };

    case 'removerManual':
      return {
        ...estado,
        tarjas: estado.tarjas.filter((t) => t.id !== acao.id || t.origem !== 'manual'),
        selecionada: estado.selecionada === acao.id ? null : estado.selecionada,
      };

    default: {
      const _exaustivo: never = acao;
      return _exaustivo;
    }
  }
}

export interface Resumo {
  ativas: number;
  rejeitadas: number;
  sinalizadas: number;
  /** Sinalizadas, ainda ativas, que o usuário nunca abriu. É o que trava a confirmação. */
  pendentes: number;
  manuais: number;
  ajustadas: number;
}

export function resumir(tarjas: Tarja[]): Resumo {
  const ativas = tarjas.filter((t) => !t.rejeitada);
  return {
    ativas: ativas.length,
    rejeitadas: tarjas.length - ativas.length,
    sinalizadas: ativas.filter((t) => t.requiresReview).length,
    pendentes: ativas.filter((t) => t.requiresReview && !t.vista).length,
    manuais: ativas.filter((t) => t.origem === 'manual').length,
    ajustadas: ativas.filter((t) => t.ajustada).length,
  };
}

/**
 * O que seria enviado para exportação quando a Fase 3/4 do backend existir.
 *
 * `texto_original` fica de FORA de propósito. A exportação precisa de onde
 * tarjar, não do que estava escrito ali, e o backend já tem o texto. Repetir
 * o dado pessoal num payload que vai para outro lugar seria espalhá-lo sem
 * ganhar nada.
 */
export interface PayloadExportacao {
  job_id: string;
  gerado_em: string;
  resumo: Resumo;
  tarjas: {
    id: string;
    type: string;
    pagina: number;
    bboxes: BBox[];
    origem: Origem;
    confidence: number | null;
    context: string | null;
    requires_review: boolean;
    ajustada: boolean;
  }[];
  descartadas: { id: string; type: string; pagina: number }[];
}

export function montarPayload(jobId: string, tarjas: Tarja[]): PayloadExportacao {
  return {
    job_id: jobId,
    gerado_em: new Date().toISOString(),
    resumo: resumir(tarjas),
    tarjas: tarjas
      .filter((t) => !t.rejeitada)
      .map((t) => ({
        id: t.id,
        type: t.type,
        pagina: t.pagina,
        bboxes: t.bboxes,
        origem: t.origem,
        confidence: t.confidence,
        context: t.context,
        requires_review: t.requiresReview,
        ajustada: t.ajustada,
      })),
    descartadas: tarjas
      .filter((t) => t.rejeitada)
      .map((t) => ({ id: t.id, type: t.type, pagina: t.pagina })),
  };
}
