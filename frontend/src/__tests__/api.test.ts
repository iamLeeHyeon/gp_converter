import { describe, it, expect, vi, beforeEach } from 'vitest'

// fetch 모킹
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

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

describe('api.deleteFile', () => {
  it('204 No Content(빈 바디) 응답이어도 에러 없이 완료돼야 한다', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      status: 204,
      json: async () => { throw new SyntaxError('Unexpected end of JSON input') },
    })
    const { api } = await import('../lib/api')
    await expect(api.deleteFile('file-1')).resolves.not.toThrow()
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

// 액세스 토큰이 만료된 채로 요청을 보내면 401을 받는데, App.tsx의 10분 주기
// 자동갱신 타이밍에 의존하지 않고 그 즉시 복구돼야 한다(실사용 중 재현된
// 버그: 변환은 되는데 "내 파일"에 하나도 안 남았음 — 만료 토큰이 조용히
// 익명 요청으로 처리됨).
describe('401 자동 재시도(액세스 토큰 만료 시 리프레시 후 재시도)', () => {
  beforeEach(() => localStorage.clear())

  it('401을 받으면 리프레시 토큰으로 갱신 후 원래 요청을 재시도한다', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'valid-refresh')
    mockFetch
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ detail: 'expired' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => ({ access_token: 'new-token', refresh_token: 'new-refresh' }) })
      .mockResolvedValueOnce({ ok: true, json: async () => [{ id: '1', name: 'song', created_at: '2026-01-01' }] })

    const { api } = await import('../lib/api')
    const files = await api.listFiles()

    expect(files).toHaveLength(1)
    expect(localStorage.getItem('access_token')).toBe('new-token')
    expect(mockFetch).toHaveBeenCalledTimes(3)
  })

  it('리프레시 토큰도 무효하면 원래 401 에러를 그대로 던진다', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'invalid-refresh')
    mockFetch
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ detail: '만료됨' }) })
      .mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) })

    const { api } = await import('../lib/api')
    await expect(api.listFiles()).rejects.toThrow('만료됨')
  })

  it('리프레시 토큰 자체가 없으면 재시도 없이 바로 실패한다', async () => {
    localStorage.setItem('access_token', 'expired-token')
    mockFetch.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({ detail: '만료됨' }) })

    const { api } = await import('../lib/api')
    await expect(api.listFiles()).rejects.toThrow('만료됨')
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })
})
