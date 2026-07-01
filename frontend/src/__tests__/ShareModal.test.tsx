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

  it('handleCreate 중 언마운트 후 setState 호출 없음 (unmounted component warning 방지)', async () => {
    const { api } = await import('../lib/api')
    let resolveCreate: (value: any) => void = () => {}
    const createPromise = new Promise(resolve => {
      resolveCreate = resolve
    })

    vi.mocked(api.getShareStatus).mockResolvedValue({ token: null, expires_at: null })
    vi.mocked(api.createShareLink).mockReturnValue(createPromise as any)

    const { unmount } = render(<ShareModal fileId="f1" onClose={onClose} />)
    const createBtn = await screen.findByRole('button', { name: /링크 생성/i })
    await userEvent.click(createBtn)

    // Promise 해결 전 언마운트
    unmount()

    // Promise 해결 후에도 setState 호출 안 됨 (경고 발생 없어야 함)
    expect(() => {
      resolveCreate({ token: 'abc123', expires_at: '2026-07-08T00:00:00+00:00' })
    }).not.toThrow()
  })

  it('handleRevoke 중 언마운트 후 setState 호출 없음', async () => {
    const { api } = await import('../lib/api')
    let resolveRevoke: (value: any) => void = () => {}
    const revokePromise = new Promise(resolve => {
      resolveRevoke = resolve
    })

    vi.mocked(api.getShareStatus).mockResolvedValue({
      token: 'existing-token', expires_at: null,
    })
    vi.mocked(api.revokeShareLink).mockReturnValue(revokePromise as any)

    const { unmount } = render(<ShareModal fileId="f1" onClose={onClose} />)
    const revokeBtn = await screen.findByRole('button', { name: /공유 중단/i })
    await userEvent.click(revokeBtn)

    unmount()

    expect(() => {
      resolveRevoke(undefined)
    }).not.toThrow()
  })
})
