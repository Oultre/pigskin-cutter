import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The build lands in the Python package (web/static/) so `cutup serve` ships it
// same-origin — no separate web server, no CORS. In dev, `npm run dev` proxies
// /api to a running `cutup serve` on :8000.
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: '../src/cutup/web/static',
    emptyOutDir: true,
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
