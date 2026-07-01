import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    getShareStatus: vi.fn(),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
  },
}))

import ShareModal from '../components/Editor/ShareModal'

describe('ShareModal', () => {
  const onClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(navigator, { clipboard: { writeText: vi.fn() } })
  })

  it('링크 없으면 만료기간 선택 + 생성 버튼 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({ token: null, expires_at: null })

    render(<ShareModal fileId="f1" onClose={onClose} />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /링크 생성/i })).toBeInTheDocument(),
    )
  })

  it('링크 생성 클릭 → api.createShareLink 호출 후 링크 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({ token: null, expires_at: null })
    vi.mocked(api.createShareLink).mockResolvedValue({
      token: 'abc123', expires_at: '2026-07-08T00:00:00+00:00',
    })

    render(<ShareModal fileId="f1" onClose={onClose} />)
    await waitFor(() => screen.getByRole('button', { name: /링크 생성/i }))
    await userEvent.click(screen.getByRole('button', { name: /링크 생성/i }))

    expect(api.createShareLink).toHaveBeenCalledWith('f1', 7)
    await waitFor(() =>
      expect(screen.getByDisplayValue(/\/share\/abc123/)).toBeInTheDocument(),
    )
  })

  it('기존 링크 있으면 링크+복사+공유중단 버튼 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({
      token: 'existing-token', expires_at: null,
    })

    render(<ShareModal fileId="f1" onClose={onClose} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue(/\/share\/existing-token/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /공유 중단/i })).toBeInTheDocument()
  })

  it('공유 중단 클릭 → api.revokeShareLink 호출 후 생성 폼으로 복귀', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({
      token: 'existing-token', expires_at: null,
    })
    vi.mocked(api.revokeShareLink).mockResolvedValue(undefined)

    render(<ShareModal fileId="f1" onClose={onClose} />)
    await waitFor(() => screen.getByRole('button', { name: /공유 중단/i }))
    await userEvent.click(screen.getByRole('button', { name: /공유 중단/i }))

    expect(api.revokeShareLink).toHaveBeenCalledWith('f1')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /링크 생성/i })).toBeInTheDocument(),
    )
  })
})
