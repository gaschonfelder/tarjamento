/**
 * Orquestra as duas telas: entrada (upload + espera) e revisão.
 *
 * É aqui que mora o ciclo de vida do job — criar, acompanhar, destruir —
 * porque ele atravessa as duas telas e não pertence a nenhuma delas.
 */
import { useCallback, useEffect, useState } from 'react';
import { consultarJob, descartarJob, enviarDocumento, ErroApi } from './api/client';
import type { JobResponse } from './types';
import Upload from './components/Upload';
import RevisaoDocumento from './components/RevisaoDocumento';

/** Intervalo do polling. O processamento típico leva menos que isso. */
const INTERVALO_MS = 1500;

export default function App() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);

  const jobId = job?.id ?? null;
  const status = job?.status ?? null;

  const enviar = useCallback(async (escolhido: File) => {
    setErro(null);
    setEnviando(true);
    setArquivo(escolhido);
    try {
      setJob(await enviarDocumento(escolhido));
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

  // Fechar a aba destrói o job. Só aqui e no descarte explícito — NUNCA na
  // limpeza de um efeito, que o StrictMode dispara no desenvolvimento e
  // apagaria o job recém-criado.
  useEffect(() => {
    if (jobId === null) return;
    const aoSair = () => descartarJob(jobId);
    window.addEventListener('pagehide', aoSair);
    return () => window.removeEventListener('pagehide', aoSair);
  }, [jobId]);

  const descartar = useCallback(() => {
    if (jobId !== null) descartarJob(jobId);
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

      {pronto ? (
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
