import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/convert': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
      '/auth': {
        target: 'http://localhost:8000',
        // /auth/callback은 백엔드 라우트가 아니라 프론트엔드 전용(OAuthCallback.tsx)
        // 라우트다 — 프록시하면 백엔드가 404를 뱉으니 그 경로만 제외한다.
        bypass: (req) => {
          if (req.url === '/auth/callback') return req.url
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
