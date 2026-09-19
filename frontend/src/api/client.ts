/**
 * As três chamadas da API. Nada além delas — o backend não tem mais nada.
 *
 * A base default é `/api`, servida pelo proxy do dev server, e não a URL da
 * API: o fetch direto seria cross-origin e a API não tem CORS de propósito.
 * O porquê está em `vite.config.ts`.
 */
import type { DecisaoEntidade, EntidadeFaltando, ExportarRequest, JobResponse } from '../types';

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

/**
 * Faltou decisão para alguma tarja do resultado original — 400.
 *
 * Não deveria acontecer em uso normal: `montarDecisoes` sempre manda uma
 * decisão por tarja do estado. Se acontecer mesmo assim, é sinal de que o
 * estado local e o servidor divergiram, e a interface precisa mostrar o quê
 * falta sem jogar fora a revisão já feita.
 */
export class ExportacaoIncompleta extends ErroApi {
  constructor(
    readonly faltando: EntidadeFaltando[],
    mensagem: string,
  ) {
    super(400, mensagem);
    this.name = 'ExportacaoIncompleta';
  }
}

/**
 * A verificação pós-redação (Fase 4) reprovou o documento gerado — 500.
 *
 * O arquivo existe no servidor mas NÃO foi servido: um documento com dado
 * pessoal ainda detectável não pode ser tratado como pronto. O job continua
 * vivo para nova tentativa.
 */
export class VerificacaoReprovada extends ErroApi {
  constructor(mensagem: string) {
    super(500, mensagem);
    this.name = 'VerificacaoReprovada';
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

/** O `detail` de uma resposta de erro, cru — string simples ou objeto estruturado. */
async function corpoDetalhe(resposta: Response): Promise<unknown> {
  try {
    const corpo: unknown = await resposta.json();
    if (corpo && typeof corpo === 'object' && 'detail' in corpo) {
      return (corpo as { detail: unknown }).detail;
    }
  } catch {
    // Corpo não-JSON: quem chama cai no fallback genérico.
  }
  return undefined;
}

/**
 * Redige de verdade (Fase 4) e devolve os bytes do PDF pronto para download.
 *
 * Só pode ser chamada uma vez por job: uma exportação bem-sucedida destrói o
 * job no servidor (é o próprio backend quem faz isso, depois de servir o
 * arquivo) — chamar de novo com o mesmo `jobId` encontra `JobNaoEncontrado`.
 *
 * 400 e 500 chegam com `detail` estruturado (não uma string simples, ao
 * contrário do resto da API), por isso o corpo é lido uma vez só, com
 * `corpoDetalhe`, e não por `detalhe()` (que já consumiria o corpo sozinho):
 * um vira `ExportacaoIncompleta` com a lista de tarjas sem decisão, o outro
 * vira `VerificacaoReprovada` com o motivo. Qualquer outro código cai no
 * `ErroApi` genérico.
 */
export async function exportarDocumento(
  jobId: string,
  decisoes: DecisaoEntidade[],
  sinal?: AbortSignal,
): Promise<Blob> {
  const corpo: ExportarRequest = { decisoes };
  const resposta = await fetch(`${BASE}/documentos/${jobId}/exportar`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corpo),
    ...(sinal ? { signal: sinal } : {}),
  });

  if (resposta.status === 404) throw new JobNaoEncontrado();

  if (resposta.status === 400) {
    const detail = await corpoDetalhe(resposta);
    if (detail && typeof detail === 'object' && Array.isArray((detail as { faltando?: unknown }).faltando)) {
      const estruturado = detail as { faltando: EntidadeFaltando[]; mensagem?: unknown };
      throw new ExportacaoIncompleta(
        estruturado.faltando,
        typeof estruturado.mensagem === 'string'
          ? estruturado.mensagem
          : 'Faltam decisões de revisão para uma ou mais tarjas.',
      );
    }
    throw new ErroApi(400, typeof detail === 'string' ? detail : `A API respondeu ${resposta.status}.`);
  }

  if (resposta.status === 500) {
    const detail = await corpoDetalhe(resposta);
    const mensagem =
      detail && typeof detail === 'object' && typeof (detail as { mensagem?: unknown }).mensagem === 'string'
        ? (detail as { mensagem: string }).mensagem
        : 'A verificação pós-redação reprovou este documento — ele não deve ser ' +
          'considerado seguro para publicação.';
    throw new VerificacaoReprovada(mensagem);
  }

  if (!resposta.ok) throw new ErroApi(resposta.status, await detalhe(resposta));
  return await resposta.blob();
}
