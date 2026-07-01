import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    getShareStatus: vi.fn(),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
  },
}))

// --- setState 호출 추적용 'react' 부분 모킹 ---
// 주의: React 18+ 부터 "Can't perform a React state update on an unmounted
// component" 콘솔 경고가 완전히 제거됐다 (실측 확인, React 19.2.7).
// unmount 후 setState 호출은 조용히 no-op 처리되고 throw도, console.error도
// 발생하지 않는다. 즉 console.error 스파이 방식으로는 isMountedRef 가드의
// 유무를 절대 구분할 수 없다 (가드를 지워도 항상 통과함 — teeth 없음).
// 그래서 실제 신호를 얻기 위해 useState의 setter를 감싸 "호출 자체가
// 실제로 일어났는지"를 직접 카운트한다. 이러면 React가 그 호출을 내부적으로
// 어떻게 처리하든 상관없이, 우리 코드(handleCreate/handleRevoke/handleCopy)가
// 가드를 통과해 setter를 불렀는지를 정확히 검증할 수 있다.
const stateTracking = vi.hoisted(() => ({ totalCalls: 0 }))

vi.mock('react', async importOriginal => {
  const actual = await importOriginal<typeof import('react')>()
  const cache = new WeakMap<(...args: any[]) => void, (...args: any[]) => void>()
  return {
    ...actual,
    useState: (initial: any) => {
      const [state, setState] = actual.useState(initial)
      let wrapped = cache.get(setState)
      if (!wrapped) {
        wrapped = (...args: any[]) => {
          stateTracking.totalCalls += 1
          return setState(...args)
        }
        cache.set(setState, wrapped)
      }
      return [state, wrapped]
    },
  }
})

import ShareModal from '../components/Editor/ShareModal'

describe('ShareModal', () => {
  const onClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    stateTracking.totalCalls = 0
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

  it('handleCreate: 언마운트 후 응답 도착해도 setState 호출 안 됨 (isMountedRef 가드 검증)', async () => {
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

    // setLoading(true)까지 반영된 시점 기준 스냅샷
    const callsBeforeUnmount = stateTracking.totalCalls

    // Promise 해결 전 언마운트
    unmount()

    // 언마운트 후 응답 도착 → 가드가 있으면 setInfo/setLoading 호출 자체가 없어야 함
    resolveCreate({ token: 'abc123', expires_at: '2026-07-08T00:00:00+00:00' })
    await new Promise(r => setTimeout(r, 0))

    expect(stateTracking.totalCalls).toBe(callsBeforeUnmount)
  })

  it('handleRevoke: 언마운트 후 응답 도착해도 setState 호출 안 됨 (isMountedRef 가드 검증)', async () => {
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

    const callsBeforeUnmount = stateTracking.totalCalls

    unmount()

    resolveRevoke(undefined)
    await new Promise(r => setTimeout(r, 0))

    expect(stateTracking.totalCalls).toBe(callsBeforeUnmount)
  })

  it('handleCopy: 언마운트 후 1500ms 타이머 발동해도 setState 호출 안 됨 (isMountedRef 가드 검증)', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({
      token: 'existing-token', expires_at: null,
    })

    const { unmount } = render(<ShareModal fileId="f1" onClose={onClose} />)
    const copyBtn = await screen.findByRole('button', { name: /복사/i })
    fireEvent.click(copyBtn)

    // setCopied(true)까지 반영된 시점 기준 스냅샷
    const callsBeforeUnmount = stateTracking.totalCalls

    unmount()

    // handleCopy의 1500ms setTimeout이 발동할 때까지 실제 대기
    await new Promise(r => setTimeout(r, 1600))

    expect(stateTracking.totalCalls).toBe(callsBeforeUnmount)
  }, 10000)
})
