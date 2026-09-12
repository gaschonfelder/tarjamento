/**
 * As três chamadas da API. Nada além delas — o backend não tem mais nada.
 *
 * A base default é `/api`, servida pelo proxy do dev server, e não a URL da
 * API: o fetch direto seria cross-origin e a API não tem CORS de propósito.
 * O porquê está em `vite.config.ts`.
 */
import type { JobResponse } from '../types';

const BASE: string = import.meta.env['VITE_API_URL'] ?? '/api';

/** Falha vinda da API, com o status para quem chama decidir o que fazer. */
export class ErroApi extends Error {
  constructor(
    readonly status: number,
    mensagem: string,
  ) {
    super(mensagem);
    this.name = 'ErroApi';
  }
}

/** O job não existe: nunca existiu, expirou, ou já foi descartado. */
export class JobNaoEncontrado extends ErroApi {
  constructor() {
    super(404, 'O job não existe mais no servidor (expirou ou foi descartado).');
    this.name = 'JobNaoEncontrado';
  }
}

async function detalhe(resposta: Response): Promise<string> {
  try {
    const corpo: unknown = await resposta.json();
    if (corpo && typeof corpo === 'object' && 'detail' in corpo) {
      const d = (corpo as { detail: unknown }).detail;
      if (typeof d === 'string') return d;
    }
  } catch {
    // Corpo não-JSON: o status já diz o suficiente.
  }
  return `A API respondeu ${resposta.status}.`;
}

/**
 * Envia o PDF e devolve o job em `recebido` — o POST não espera o
 * processamento, então quem chama precisa fazer polling em seguida.
 */
export async function enviarDocumento(
  arquivo: File,
  sinal?: AbortSignal,
): Promise<JobResponse> {
  const corpo = new FormData();
  corpo.append('arquivo', arquivo, arquivo.name);

  const resposta = await fetch(`${BASE}/documentos`, {
    method: 'POST',
    body: corpo,
    ...(sinal ? { signal: sinal } : {}),
  });

  if (!resposta.ok) {
    // 415 e 413 são recusas esperadas e têm mensagem própria da API.
    throw new ErroApi(resposta.status, await detalhe(resposta));
  }
  return (await resposta.json()) as JobResponse;
}

/** O estado atual do job. Em `pronto`, vem com as páginas e as entidades. */
export async function consultarJob(
  jobId: string,
  sinal?: AbortSignal,
): Promise<JobResponse> {
  const resposta = await fetch(`${BASE}/documentos/${jobId}`, {
    ...(sinal ? { signal: sinal } : {}),
  });

  if (resposta.status === 404) throw new JobNaoEncontrado();
  if (!resposta.ok) throw new ErroApi(resposta.status, await detalhe(resposta));
  return (await resposta.json()) as JobResponse;
}

/**
 * Baixa o PDF original do job.
 *
 * O browser não guarda o `File` do upload entre recarregamentos, então esta é
 * a única forma de a tela de revisão voltar a ter o documento depois de um
 * refresh. Devolve um `File` (e não o `Blob` cru) porque é o que
 * `RevisaoDocumento` espera — ele só chama `arrayBuffer()`, mas o tipo já
 * estava assim para o arquivo recém-enviado.
 */
export async function baixarOriginal(
  jobId: string,
  sinal?: AbortSignal,
): Promise<File> {
  const resposta = await fetch(`${BASE}/documentos/${jobId}/original`, {
    ...(sinal ? { signal: sinal } : {}),
  });

  if (resposta.status === 404) throw new JobNaoEncontrado();
  if (!resposta.ok) throw new ErroApi(resposta.status, await detalhe(resposta));
  return new File([await resposta.blob()], 'documento.pdf', {
    type: 'application/pdf',
  });
}

/**
 * Destrói o job no servidor. Best-effort de propósito: é limpeza, e falhar
 * nela não pode travar a tela — o TTL do backend apaga de qualquer jeito.
 *
 * Só é chamada por ação DELIBERADA do usuário (descartar, recomeçar). Sair da
 * página NÃO destrói o job: o TTL do servidor já cobre o abandono, e apagar
 * na primeira troca de aba puniria qualquer navegação acidental.
 *
 * `keepalive` deixa a requisição sobreviver à navegação, caso ela aconteça
 * logo depois do clique. (`sendBeacon` não serve: ele só faz POST.)
 */
export function descartarJob(jobId: string): void {
  void fetch(`${BASE}/documentos/${jobId}`, {
    method: 'DELETE',
    keepalive: true,
  }).catch(() => {
    // Sem tratamento: o TTL do servidor é a garantia real de destruição.
  });
}
