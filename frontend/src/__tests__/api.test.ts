import { describe, it, expect, vi, beforeEach } from 'vitest'

// fetch 모킹
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => mockFetch.mockReset())

describe('api.upload', () => {
  it('POST /convert FormData 전송 후 job_id 반환', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ job_id: 'abc123', file_id: null }),
    })
    const { api } = await import('../lib/api')
    const file = new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })
    const result = await api.upload(file)
    expect(result.job_id).toBe('abc123')
    expect(mockFetch).toHaveBeenCalledWith('/convert', expect.objectContaining({ method: 'POST' }))
  })

  it('업로드 실패 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '파일이 너무 큽니다' }),
    })
    const { api } = await import('../lib/api')
    const file = new File(['x'], 'test.pdf')
    await expect(api.upload(file)).rejects.toThrow('파일이 너무 큽니다')
  })
})

describe('api.listFiles', () => {
  it('GET /files 반환값 파싱', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: '1', name: 'song', created_at: '2026-01-01' }],
    })
    const { api } = await import('../lib/api')
    const files = await api.listFiles()
    expect(files).toHaveLength(1)
    expect(files[0].name).toBe('song')
  })
})
