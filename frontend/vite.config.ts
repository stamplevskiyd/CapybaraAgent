/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Default (loopback-only) host: a bare `npm run dev` on the host machine must
    // not expose the /api proxy to the LAN — the backend is deliberately bound to
    // loopback. Inside docker compose the container passes --host 0.0.0.0
    // explicitly (see docker-compose.yml), and its published port is loopback-bound.
    // The proxy target is host-based by default, but overridable via
    // VITE_API_PROXY_TARGET (set to http://api:8000 under docker compose).
    proxy: {
      '/api': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
      // Chainlit runtime (REST + socket.io) mounted by the backend under /chainlit.
      '/chainlit': {
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
  },
})
