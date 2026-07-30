import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/static/',
  build: {
    outDir: '../src/webui/static',
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:9238', changeOrigin: true },
      '/api/ws': { target: 'ws://localhost:9238', ws: true },
    },
  },
})
