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

test('마운트 시 즉시 한 번 갱신하고, 이후 10분마다 자동 호출된다', () => {
  // 이미 만료된 토큰으로 새로고침/재마운트되는 경우를 위해 인터벌을 기다리지
  // 않고 마운트 즉시 1회 갱신한다(실사용 중 "새로고침 직후 401" 버그로 확인).
  render(<App />)
  expect(refreshAccessToken).toHaveBeenCalledTimes(1)

  vi.advanceTimersByTime(10 * 60 * 1000)
  expect(refreshAccessToken).toHaveBeenCalledTimes(2)

  vi.advanceTimersByTime(10 * 60 * 1000)
  expect(refreshAccessToken).toHaveBeenCalledTimes(3)
})
