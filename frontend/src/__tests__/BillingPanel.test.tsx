import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

// --- setState 호출 추적용 'react' 부분 모킹 ---
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

vi.mock('../lib/api', () => ({
  api: {
    getUsage: vi.fn(),
    createCheckoutSession: vi.fn(),
    createPortalSession: vi.fn(),
  },
}))

import BillingPanel from '../components/Billing/BillingPanel'

describe('BillingPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    stateTracking.totalCalls = 0
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
      configurable: true,
    })
  })

  it('free 유저: 사용량 표시 + 업그레이드 버튼', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'free', conversions_used: 1, conversions_limit: 3,
      files_used: 2, files_limit: 5,
    })

    render(<BillingPanel />)

    await waitFor(() => expect(screen.getByText(/1\/3/)).toBeInTheDocument())
    expect(screen.getByText(/2\/5/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /업그레이드/i })).toBeInTheDocument()
  })

  it('pro 유저: 무제한 표시 + 구독관리 버튼', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'pro', conversions_used: 10, conversions_limit: 3,
      files_used: 20, files_limit: 5,
    })

    render(<BillingPanel />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /구독 관리/i })).toBeInTheDocument(),
    )
  })

  it('업그레이드 클릭 → checkout url로 리다이렉트', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'free', conversions_used: 0, conversions_limit: 3,
      files_used: 0, files_limit: 5,
    })
    vi.mocked(api.createCheckoutSession).mockResolvedValue({
      url: 'https://checkout.stripe.com/x',
    })

    render(<BillingPanel />)
    await waitFor(() => screen.getByRole('button', { name: /업그레이드/i }))
    await userEvent.click(screen.getByRole('button', { name: /업그레이드/i }))

    await waitFor(() => expect(window.location.href).toBe('https://checkout.stripe.com/x'))
  })

  it('구독관리 클릭 → portal url로 리다이렉트', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'pro', conversions_used: 0, conversions_limit: 3,
      files_used: 0, files_limit: 5,
    })
    vi.mocked(api.createPortalSession).mockResolvedValue({
      url: 'https://billing.stripe.com/x',
    })

    render(<BillingPanel />)
    await waitFor(() => screen.getByRole('button', { name: /구독 관리/i }))
    await userEvent.click(screen.getByRole('button', { name: /구독 관리/i }))

    await waitFor(() => expect(window.location.href).toBe('https://billing.stripe.com/x'))
  })

  it('handleUpgrade: 언마운트 후 응답 도착해도 setState 호출 안 됨 (isMountedRef 가드 검증)', async () => {
    const { api } = await import('../lib/api')
    let resolveCheckout: (value: any) => void = () => {}
    const checkoutPromise = new Promise(resolve => {
      resolveCheckout = resolve
    })

    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'free', conversions_used: 0, conversions_limit: 3,
      files_used: 0, files_limit: 5,
    })
    vi.mocked(api.createCheckoutSession).mockReturnValue(checkoutPromise as any)

    const { unmount } = render(<BillingPanel />)
    const upgradeBtn = await screen.findByRole('button', { name: /업그레이드/i })
    await userEvent.click(upgradeBtn)

    // setBusy(true)까지 반영된 시점 기준 스냅샷
    const callsBeforeUnmount = stateTracking.totalCalls

    // Promise 해결 전 언마운트
    unmount()

    // 언마운트 후 응답 도착 → 가드가 있으면 setBusy(false) 호출이 없어야 함
    resolveCheckout({ url: 'https://checkout.stripe.com/x' })
    await new Promise(r => setTimeout(r, 0))

    expect(stateTracking.totalCalls).toBe(callsBeforeUnmount)
  })

  it('handleManage: 언마운트 후 응답 도착해도 setState 호출 안 됨 (isMountedRef 가드 검증)', async () => {
    const { api } = await import('../lib/api')
    let resolvePortal: (value: any) => void = () => {}
    const portalPromise = new Promise(resolve => {
      resolvePortal = resolve
    })

    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'pro', conversions_used: 0, conversions_limit: 3,
      files_used: 0, files_limit: 5,
    })
    vi.mocked(api.createPortalSession).mockReturnValue(portalPromise as any)

    const { unmount } = render(<BillingPanel />)
    const manageBtn = await screen.findByRole('button', { name: /구독 관리/i })
    await userEvent.click(manageBtn)

    const callsBeforeUnmount = stateTracking.totalCalls

    unmount()

    resolvePortal({ url: 'https://billing.stripe.com/x' })
    await new Promise(r => setTimeout(r, 0))

    expect(stateTracking.totalCalls).toBe(callsBeforeUnmount)
  })
})
