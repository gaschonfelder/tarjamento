/**
 * Orquestra as duas telas: entrada (upload + espera) e revisão.
 *
 * É aqui que mora o ciclo de vida do job — criar, retomar, acompanhar,
 * destruir — porque ele atravessa as duas telas e não pertence a nenhuma
 * delas.
 *
 * O id do job vive na query string (`?job=<id>`). Isso é o que faz um refresh
 * não jogar fora um documento já processado: ao carregar, se houver `?job=`,
 * a tela tenta retomar aquele job antes de oferecer o upload. O que NÃO
 * sobrevive é o estado da revisão (aceito/rejeitado/manual), que só existe no
 * reducer de `state/revisao.ts` e nunca foi para o servidor.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  baixarOriginal,
  consultarJob,
  descartarJob,
  enviarDocumento,
  ErroApi,
} from './api/client';
import type { JobResponse } from './types';
import Upload from './components/Upload';
import RevisaoDocumento from './components/RevisaoDocumento';

/** Intervalo do polling. O processamento típico leva menos que isso. */
const INTERVALO_MS = 1500;

/** Nome do parâmetro na URL. Um só, e nenhuma biblioteca de rotas por isso. */
const PARAM_JOB = 'job';

function jobDaUrl(): string | null {
  return new URLSearchParams(window.location.search).get(PARAM_JOB);
}

/**
 * Escreve (ou apaga) o `?job=` sem recarregar.
 *
 * `replaceState`, não `pushState`: a aplicação não escuta `popstate`, então um
 * `pushState` deixaria o botão "voltar" mudando a URL sem mudar a tela —
 * inconsistência pior que a ausência de histórico. Com `replaceState` a URL
 * sempre descreve o que está na tela, que é o necessário para o refresh
 * funcionar.
 */
function definirJobNaUrl(jobId: string | null): void {
  const url = new URL(window.location.href);
  if (jobId === null) url.searchParams.delete(PARAM_JOB);
  else url.searchParams.set(PARAM_JOB, jobId);
  window.history.replaceState(null, '', url);
}

export default function App() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  // Começa em `true` só quando há o que retomar: sem isso a tela de upload
  // apareceria por um instante antes de a retomada terminar.
  const [retomando, setRetomando] = useState(() => jobDaUrl() !== null);

  const jobId = job?.id ?? null;
  const status = job?.status ?? null;

  // Retomada: roda uma vez, na carga da página.
  useEffect(() => {
    const id = jobDaUrl();
    if (id === null) return;

    const controlador = new AbortController();
    void (async () => {
      try {
        // O estado primeiro: se o job morreu, nem vale baixar o PDF.
        const atual = await consultarJob(id, controlador.signal);
        const original = await baixarOriginal(id, controlador.signal);
        if (controlador.signal.aborted) return;
        setJob(atual);
        setArquivo(original);
        if (atual.status === 'erro') {
          setErro(atual.erro ?? 'O processamento falhou no servidor.');
        }
      } catch {
        if (controlador.signal.aborted) return;
        // Expirado, destruído ou id inventado: cai na tela de upload limpa.
        // Não é erro do usuário, então não vira mensagem de erro.
        definirJobNaUrl(null);
      } finally {
        if (!controlador.signal.aborted) setRetomando(false);
      }
    })();

    return () => controlador.abort();
  }, []);

  const enviar = useCallback(async (escolhido: File) => {
    setErro(null);
    setEnviando(true);
    setArquivo(escolhido);
    try {
      const novo = await enviarDocumento(escolhido);
      setJob(novo);
      definirJobNaUrl(novo.id);
    } catch (e) {
      setArquivo(null);
      setErro(
        e instanceof ErroApi
          ? e.message
          : 'Não consegui falar com a API. Ela está no ar em 127.0.0.1:8731?',
      );
    } finally {
      setEnviando(false);
    }
  }, []);

  // Polling: só enquanto o job não chegou a um estado terminal. Depender de
  // `status` (e não do objeto `job`) evita recriar o timer a cada resposta.
  useEffect(() => {
    if (jobId === null || status === null) return;
    if (status === 'pronto' || status === 'erro') return;

    const controlador = new AbortController();
    const temporizador = window.setInterval(() => {
      void (async () => {
        try {
          const atual = await consultarJob(jobId, controlador.signal);
          setJob(atual);
          if (atual.status === 'erro') {
            setErro(atual.erro ?? 'O processamento falhou no servidor.');
          }
        } catch (e) {
          if (controlador.signal.aborted) return;
          setErro(
            e instanceof ErroApi ? e.message : 'Perdi contato com a API durante o processamento.',
          );
        }
      })();
    }, INTERVALO_MS);

    return () => {
      controlador.abort();
      window.clearInterval(temporizador);
    };
  }, [jobId, status]);

  // Sair da página NÃO destrói o job: o TTL do servidor já cobre o abandono, e
  // destruir no `pagehide` punia qualquer troca de aba ou refresh acidental.
  // O DELETE só sai de ação deliberada — este `descartar`, ligado aos botões
  // de descartar e de recomeçar.
  const descartar = useCallback(() => {
    if (jobId !== null) descartarJob(jobId);
    definirJobNaUrl(null);
    setJob(null);
    setArquivo(null);
    setErro(null);
  }, [jobId]);

  const pronto = job !== null && job.status === 'pronto' && arquivo !== null && erro === null;

  return (
    <div className="app">
      <header className="app__cabecalho">
        <h1>redator</h1>
        <p className="app__subtitulo">
          Revisão de tarjas — os valores exibidos são dados pessoais reais do documento enviado.
        </p>
        {job && (
          <span className="app__job" title={`Job ${job.id}`}>
            job {job.id.slice(0, 8)} · expira {new Date(job.expira_em).toLocaleTimeString('pt-BR')}
          </span>
        )}
      </header>

      {retomando ? (
        <p className="app__retomando" role="status">
          Retomando o documento…
        </p>
      ) : pronto ? (
        <RevisaoDocumento job={job} arquivo={arquivo} onDescartar={descartar} />
      ) : (
        <Upload
          enviando={enviando}
          status={status}
          progresso={job?.progresso ?? null}
          erro={erro}
          onEnviar={(f) => void enviar(f)}
          onTentarNovamente={descartar}
        />
      )}
    </div>
  );
}
