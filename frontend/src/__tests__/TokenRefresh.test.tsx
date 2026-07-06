import { render } from '@testing-library/react'
import { vi, beforeEach, afterEach, test, expect } from 'vitest'

const refreshAccessToken = vi.fn()

vi.mock('../store/authStore', () => ({
  useAuthStore: () => ({
    token: 'valid-token',
    emailVerified: true,
    plan: 'free',
    logout: vi.fn(),
    fetchMe: vi.fn(),
    refreshAccessToken,
  }),
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: () => ({ setFileId: vi.fn(), clearHistory: vi.fn() }),
}))
vi.mock('../components/FileManager/FileList', () => ({ default: () => null }))
vi.mock('../components/FileManager/UploadButton', () => ({ default: () => null }))
vi.mock('../components/Billing/BillingPanel', () => ({ default: () => null }))
vi.mock('../components/Editor/ScoreViewer', () => ({ default: () => null }))

import App from '../App'

beforeEach(() => {
  vi.useFakeTimers()
  refreshAccessToken.mockClear()
})

afterEach(() => {
  vi.useRealTimers()
})

test('로그인된 상태로 10분마다 refreshAccessToken이 자동 호출된다', () => {
  render(<App />)

  expect(refreshAccessToken).not.toHaveBeenCalled()

  vi.advanceTimersByTime(10 * 60 * 1000)
  expect(refreshAccessToken).toHaveBeenCalledTimes(1)

  vi.advanceTimersByTime(10 * 60 * 1000)
  expect(refreshAccessToken).toHaveBeenCalledTimes(2)
})
