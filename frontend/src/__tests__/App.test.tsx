import { render } from '@testing-library/react'
import { vi } from 'vitest'

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
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
