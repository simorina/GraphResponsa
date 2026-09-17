import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    port: 5173,
    // Le rotte del backend, da tenere allineate a quelle di src/server.py.
    //
    // Una rotta dimenticata non da' errore: Vite risponde con la pagina, il
    // frontend prova a leggerla come JSON e fallisce in silenzio. E' successo
    // con /conversazioni, che porta lo storico e i contatori di consumo:
    // andavano entrambi nel catch, e in sviluppo la barra laterale restava
    // vuota senza che niente lo dicesse. In produzione sono lo stesso
    // servizio, quindi il guasto si vedeva solo qui.
    proxy: Object.fromEntries(
      ['/chat', '/stato', '/documenti', '/conversazioni', '/riscontro'].map((r) => [
        r,
        { target: 'http://127.0.0.1:8000', changeOrigin: true },
      ])
    ),
  }
})
