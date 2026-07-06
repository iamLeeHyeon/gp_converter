import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
    noteMouseDown: { on: vi.fn() },
    load: vi.fn(),
    playPause: vi.fn(),
    destroy: vi.fn(),
  }),
}))

import App from '../App'

test('앱이 렌더링된다', () => {
  render(<App />)
  expect(document.body).toBeTruthy()
})

test('로그아웃 상태면 메인 페이지 사이드바에 로그인 링크가 보인다', () => {
  localStorage.removeItem('access_token')
  render(<App />)
  expect(screen.getByRole('link', { name: /로그인/i })).toBeInTheDocument()
})
