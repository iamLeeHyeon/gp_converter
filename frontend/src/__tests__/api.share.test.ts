import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

beforeEach(() => mockFetch.mockReset())

describe('api 공유 링크', () => {
  it('getShareStatus: GET /files/{id}/share 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ token: null, expires_at: null }),
    })
    const { api } = await import('../lib/api')
    const result = await api.getShareStatus('f1')
    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/share',
      expect.objectContaining({ headers: expect.anything() }),
    )
    expect(result).toEqual({ token: null, expires_at: null })
  })

  it('createShareLink: POST /files/{id}/share에 expires_in_days 전송', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ token: 'abc123', expires_at: '2026-07-08T00:00:00+00:00' }),
    })
    const { api } = await import('../lib/api')
    const result = await api.createShareLink('f1', 7)
    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/share',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ expires_in_days: 7 }),
      }),
    )
    expect(result.token).toBe('abc123')
  })

  it('revokeShareLink: DELETE /files/{id}/share 호출', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) })
    const { api } = await import('../lib/api')
    await api.revokeShareLink('f1')
    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/share',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('fetchSharedGP5: 인증 헤더 없이 GET /files/shared/{token} 호출', async () => {
    const buf = new ArrayBuffer(8)
    mockFetch.mockResolvedValueOnce({ ok: true, arrayBuffer: async () => buf })
    const { api } = await import('../lib/api')
    const result = await api.fetchSharedGP5('tok123')
    expect(mockFetch).toHaveBeenCalledWith('/files/shared/tok123')
    expect(result).toBe(buf)
  })

  it('fetchSharedGP5 실패 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '링크가 만료되었습니다' }),
    })
    const { api } = await import('../lib/api')
    await expect(api.fetchSharedGP5('expired')).rejects.toThrow('링크가 만료되었습니다')
  })
})
