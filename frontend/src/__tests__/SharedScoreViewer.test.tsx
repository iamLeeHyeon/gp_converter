import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'

const { mockLoad, mockPlayPause, mockDestroy } = vi.hoisted(() => ({
  mockLoad: vi.fn(),
  mockPlayPause: vi.fn(),
  mockDestroy: vi.fn(),
}))

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    load: mockLoad,
    playPause: mockPlayPause,
    destroy: mockDestroy,
    playerStateChanged: { on: vi.fn() },
  }),
}))

vi.mock('../lib/api', () => ({
  api: { fetchSharedGP5: vi.fn() },
}))

import SharedScoreViewer from '../components/Editor/SharedScoreViewer'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/share/:token" element={<SharedScoreViewer />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SharedScoreViewer', () => {
  beforeEach(() => vi.clearAllMocks())

  it('정상 로드 시 재생 버튼 표시 + alphaTab.load 호출', async () => {
    const { api } = await import('../lib/api')
    const buf = new ArrayBuffer(8)
    vi.mocked(api.fetchSharedGP5).mockResolvedValue(buf)

    renderAt('/share/tok123')

    await waitFor(() => expect(mockLoad).toHaveBeenCalledWith(buf))
    expect(screen.getByRole('button', { name: /재생/i })).toBeInTheDocument()
  })

  it('fetchSharedGP5 실패 시 안내 문구 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.fetchSharedGP5).mockRejectedValue(new Error('링크가 만료되었습니다'))

    renderAt('/share/expired')

    await waitFor(() =>
      expect(screen.getByText(/만료되었거나 존재하지 않습니다/)).toBeInTheDocument(),
    )
  })
})
