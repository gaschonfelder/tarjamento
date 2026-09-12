/**
 * Tela de entrada: escolher o PDF e acompanhar o processamento.
 *
 * O indicador de progresso vive aqui e não numa tela própria porque, para
 * quem usa, é o mesmo momento: mandou o arquivo e está esperando. A API
 * responde o POST na hora, com status `recebido`, e o resto vem do polling.
 */
import { useRef, useState } from 'react';
import type { JobStatus } from '../types';

interface Props {
  enviando: boolean;
  status: JobStatus | null;
  progresso: number | null;
  erro: string | null;
  onEnviar: (arquivo: File) => void;
  onTentarNovamente: () => void;
}

const LEGENDA: Record<JobStatus, string> = {
  recebido: 'Na fila…',
  processando: 'Extraindo texto e detectando dados pessoais…',
  pronto: 'Pronto.',
  erro: 'Falhou.',
};

export default function Upload({
  enviando,
  status,
  progresso,
  erro,
  onEnviar,
  onTentarNovamente,
}: Props) {
  const [sobre, setSobre] = useState(false);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const ocupado = enviando || status === 'recebido' || status === 'processando';

  function aceitar(arquivos: FileList | null) {
    const arquivo = arquivos?.[0];
    if (arquivo) onEnviar(arquivo);
  }

  if (erro) {
    return (
      <div className="entrada">
        <div className="aviso aviso--erro">
          <h2>Não deu certo</h2>
          <p>{erro}</p>
        </div>
        <button type="button" className="botao botao--primario" onClick={onTentarNovamente}>
          Tentar de novo
        </button>
      </div>
    );
  }

  if (ocupado) {
    const pct = progresso !== null ? Math.round(progresso * 100) : null;
    return (
      <div className="entrada">
        <div className="processando">
          <div className="processando__barra">
            <div
              className={`processando__preenchimento ${pct === null ? 'processando__preenchimento--indeterminado' : ''}`}
              style={pct !== null ? { width: `${pct}%` } : undefined}
            />
          </div>
          <p className="processando__legenda">
            {status ? LEGENDA[status] : 'Enviando o arquivo…'}
            {pct !== null && ` (${pct}%)`}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="entrada">
      <div
        className={`solta ${sobre ? 'solta--sobre' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setSobre(true);
        }}
        onDragLeave={() => setSobre(false)}
        onDrop={(e) => {
          e.preventDefault();
          setSobre(false);
          aceitar(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
      >
        <p className="solta__titulo">Arraste um PDF aqui</p>
        <p className="solta__ou">ou clique para escolher</p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          hidden
          onChange={(e) => aceitar(e.target.files)}
        />
      </div>
      <p className="entrada__nota">
        O documento fica no seu computador e num diretório temporário do servidor, destruído ao fim
        da revisão ou quando o prazo do job vencer.
      </p>
    </div>
  );
}
