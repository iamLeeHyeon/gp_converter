import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

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
})
