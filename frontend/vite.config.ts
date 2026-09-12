import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

/**
 * O proxy existe por causa de uma decisão do backend, não por conveniência.
 *
 * A API não tem CORS — de propósito: ela devolve o valor real dos dados
 * pessoais detectados, e liberar origem é deixar uma página de terceiro ler
 * documento em revisão (veja `src/redator/api/app.py`). Consequência direta:
 * o browser em `localhost:5173` NÃO pode chamar `127.0.0.1:8731` por fetch.
 *
 * A saída, sem tocar no backend, é o browser falar só com a própria origem e
 * o dev server do Vite repassar a chamada do lado do servidor, onde CORS não
 * existe. Por isso o default de `VITE_API_URL` é `/api`, e não a URL da API.
 *
 * `VITE_API_TARGET` é para onde o proxy aponta. Em produção isso vira um
 * proxy reverso servindo front e API na mesma origem — a mesma ideia, outro
 * programa.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const alvo = env.VITE_API_TARGET || 'http://127.0.0.1:8731';

  return {
    plugins: [react()],
    server: {
      // Loopback, como a API. O front mostra os mesmos dados que ela serve.
      host: '127.0.0.1',
      port: 5173,
      proxy: {
        '/api': {
          target: alvo,
          changeOrigin: true,
          rewrite: (caminho) => caminho.replace(/^\/api/, ''),
        },
      },
    },
  };
});
