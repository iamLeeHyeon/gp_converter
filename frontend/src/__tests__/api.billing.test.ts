import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

beforeEach(() => mockFetch.mockReset())

describe('api 결제', () => {
  it('getUsage: GET /billing/usage 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        plan: 'free', conversions_used: 1, conversions_limit: 3,
        files_used: 2, files_limit: 5,
      }),
    })
    const { api } = await import('../lib/api')
    const result = await api.getUsage()
    expect(mockFetch).toHaveBeenCalledWith(
      '/billing/usage',
      expect.objectContaining({ headers: expect.anything() }),
    )
    expect(result.plan).toBe('free')
    expect(result.conversions_used).toBe(1)
  })

  it('createCheckoutSession: POST /billing/checkout 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ url: 'https://checkout.stripe.com/x' }),
    })
    const { api } = await import('../lib/api')
    const result = await api.createCheckoutSession()
    expect(mockFetch).toHaveBeenCalledWith(
      '/billing/checkout',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result.url).toBe('https://checkout.stripe.com/x')
  })

  it('createPortalSession: POST /billing/portal 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ url: 'https://billing.stripe.com/x' }),
    })
    const { api } = await import('../lib/api')
    const result = await api.createPortalSession()
    expect(mockFetch).toHaveBeenCalledWith(
      '/billing/portal',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result.url).toBe('https://billing.stripe.com/x')
  })

  it('createPortalSession 실패 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '구독 정보가 없습니다' }),
    })
    const { api } = await import('../lib/api')
    await expect(api.createPortalSession()).rejects.toThrow('구독 정보가 없습니다')
  })
})
