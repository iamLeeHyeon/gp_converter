import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { alphaTab } from '@coderline/alphatab-vite'

// https://vite.dev/config/
export default defineConfig({
  // alphaTab은 렌더링/재생을 Web Worker·Audio Worklet으로 오프로드하는데,
  // 이 플러그인 없이는 Vite의 의존성 사전번들링 구조상 워커 스크립트 경로를
  // 자동감지하지 못해 재생 버튼을 눌러도 아무 반응이 없었다(워커 요청이
  // 계속 pending으로 멈춰있음 — 실사용 중 재현). 폰트/사운드폰트도
  // public/font, public/soundfont로 자동 복사해준다.
  plugins: [react(), ...alphaTab()],
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
