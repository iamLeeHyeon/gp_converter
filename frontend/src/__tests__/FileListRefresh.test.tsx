import { render, screen, fireEvent } from '@testing-library/react'
import { vi, test, expect, beforeEach } from 'vitest'

const load = vi.fn()

vi.mock('../store/authStore', () => ({
  useAuthStore: () => ({
    token: 'valid-token',
    emailVerified: true,
    logout: vi.fn(),
    fetchMe: vi.fn(),
    refreshAccessToken: vi.fn(),
  }),
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: () => ({ setFileId: vi.fn(), clearHistory: vi.fn() }),
}))
vi.mock('../store/fileStore', () => ({
  useFileStore: () => ({ files: [], loading: false, load, remove: vi.fn() }),
}))
vi.mock('../components/FileManager/UploadButton', () => ({
  default: ({ onComplete }: { onComplete: (jobId: string, buf: ArrayBuffer, fileId?: string | null) => void }) => (
    <button onClick={() => onComplete('job1', new ArrayBuffer(8), 'file123')}>변환완료시뮬레이션</button>
  ),
}))
vi.mock('../components/Billing/BillingPanel', () => ({ default: () => null }))
vi.mock('../components/Editor/ScoreViewer', () => ({ default: () => null }))

import App from '../App'

beforeEach(() => {
  load.mockClear()
})

test('변환 완료되면 새로고침 없이 "내 파일" 목록이 다시 로드된다', () => {
  render(<App />)
  load.mockClear() // FileList 마운트 시 초기 load() 호출 제외
  fireEvent.click(screen.getByText('변환완료시뮬레이션'))
  expect(load).toHaveBeenCalled()
})
