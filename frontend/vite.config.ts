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
    proxy: {
      '/chat': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/stato': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/documenti': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      }
    }
  }
})
