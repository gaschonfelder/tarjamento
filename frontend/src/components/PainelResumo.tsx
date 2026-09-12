/**
 * Painel lateral: contagem ao vivo, legenda das cores e as ações da revisão.
 *
 * A contagem é derivada das tarjas a cada render — não há contador guardado
 * em lugar nenhum, então não existe o bug clássico de ele sair de sincronia
 * com a lista.
 */
import type { Resumo, Tarja } from '../state/revisao';
import { aparenciaDe } from '../state/revisao';

interface Props {
  resumo: Resumo;
  tarjas: Tarja[];
  selecionada: string | null;
  modo: 'navegar' | 'desenhar';
  escala: number;
  onSelecionar: (id: string | null) => void;
  onAlternarModo: () => void;
  onZoom: (escala: number) => void;
  onFinalizar: () => void;
  onDescartar: () => void;
}

const ROTULOS: Record<ReturnType<typeof aparenciaDe>, string> = {
  padrao: 'Detectada com âncora no texto',
  sem_contexto: 'Validada, mas sem âncora textual próxima',
  revisao: 'Sinalizada para revisão',
  manual: 'Marcada à mão',
};

export default function PainelResumo({
  resumo,
  tarjas,
  selecionada,
  modo,
  escala,
  onSelecionar,
  onAlternarModo,
  onZoom,
  onFinalizar,
  onDescartar,
}: Props) {
  const pendentes = tarjas.filter((t) => !t.rejeitada && t.requiresReview && !t.vista);

  return (
    <aside className="painel">
      <h2 className="painel__titulo">Revisão</h2>

      <dl className="painel__numeros">
        <div className="painel__numero">
          <dt>Tarjas ativas</dt>
          <dd>{resumo.ativas}</dd>
        </div>
        <div className="painel__numero">
          <dt>Rejeitadas</dt>
          <dd>{resumo.rejeitadas}</dd>
        </div>
        <div className={`painel__numero ${resumo.sinalizadas > 0 ? 'painel__numero--alerta' : ''}`}>
          <dt>Sinalizadas para revisão</dt>
          <dd>{resumo.sinalizadas}</dd>
        </div>
      </dl>

      {(resumo.manuais > 0 || resumo.ajustadas > 0) && (
        <p className="painel__extra">
          {resumo.manuais > 0 && `${resumo.manuais} marcada(s) à mão`}
          {resumo.manuais > 0 && resumo.ajustadas > 0 && ' · '}
          {resumo.ajustadas > 0 && `${resumo.ajustadas} com borda ajustada`}
        </p>
      )}

      {pendentes.length > 0 && (
        <div className="painel__aviso">
          <strong>{pendentes.length}</strong> sinalizada(s) que você ainda não abriu. Passe o mouse
          sobre cada uma para ver o valor antes de finalizar.
        </div>
      )}

      <div className="painel__acoes">
        <button
          type="button"
          className={`botao ${modo === 'desenhar' ? 'botao--ativo' : ''}`}
          onClick={onAlternarModo}
        >
          {modo === 'desenhar' ? 'Cancelar marcação' : 'Adicionar tarja manual'}
        </button>
        {modo === 'desenhar' && (
          <p className="painel__dica">Clique e arraste sobre a página para marcar a área.</p>
        )}
      </div>

      <div className="painel__zoom">
        <span>Zoom</span>
        <button type="button" className="botao botao--pequeno" onClick={() => onZoom(escala - 0.25)}>
          −
        </button>
        <span className="painel__escala">{Math.round(escala * 100)}%</span>
        <button type="button" className="botao botao--pequeno" onClick={() => onZoom(escala + 0.25)}>
          +
        </button>
      </div>

      <h3 className="painel__subtitulo">Legenda</h3>
      <ul className="painel__legenda">
        {(['padrao', 'sem_contexto', 'revisao', 'manual'] as const).map((a) => (
          <li key={a}>
            <span className={`amostra amostra--${a}`} />
            {ROTULOS[a]}
          </li>
        ))}
      </ul>

      <h3 className="painel__subtitulo">Tarjas ({tarjas.length})</h3>
      <ul className="painel__lista">
        {tarjas.map((t) => (
          <li key={t.id}>
            <button
              type="button"
              className={[
                'item',
                `item--${aparenciaDe(t)}`,
                t.rejeitada ? 'item--rejeitada' : '',
                selecionada === t.id ? 'item--selecionada' : '',
              ]
                .filter(Boolean)
                .join(' ')}
              onClick={() => onSelecionar(selecionada === t.id ? null : t.id)}
            >
              <span className="item__tipo">{t.type}</span>
              <span className="item__pagina">p. {t.pagina + 1}</span>
              {t.requiresReview && !t.vista && !t.rejeitada && (
                <span className="item__pendente" title="Ainda não revisada">
                  •
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>

      <div className="painel__rodape">
        <button type="button" className="botao botao--primario" onClick={onFinalizar}>
          Finalizar revisão
        </button>
        <button type="button" className="botao botao--discreto" onClick={onDescartar}>
          Descartar e recomeçar
        </button>
      </div>
    </aside>
  );
}
