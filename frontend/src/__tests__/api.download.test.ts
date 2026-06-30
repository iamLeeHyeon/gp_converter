import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

// URL.createObjectURL / revokeObjectURL 모킹 (stubGlobal은 URL 생성자 파괴 → spyOn 사용)
const mockCreateURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock-url')
const mockRevokeURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

// anchor click 모킹
let lastAnchor: { href: string; download: string; click: ReturnType<typeof vi.fn> } | null = null
vi.spyOn(document, 'createElement').mockImplementation((tag) => {
  if (tag === 'a') {
    lastAnchor = { href: '', download: '', click: vi.fn() }
    return lastAnchor as any
  }
  return document.createElement(tag)
})

beforeEach(() => {
  mockFetch.mockReset()
  mockCreateURL.mockClear()
  mockRevokeURL.mockClear()
  lastAnchor = null
})

describe('api.downloadGP5', () => {
  it('GET /files/:id/download 호출 후 blob 다운로드 트리거', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob(['GP5DATA']),
    })
    const { api } = await import('../lib/api')
    await api.downloadGP5('f1', 'my_song.gp5')

    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/download',
      expect.objectContaining({ headers: expect.any(Object) })
    )
    expect(lastAnchor?.download).toBe('my_song.gp5')
    expect(lastAnchor?.click).toHaveBeenCalled()
    expect(mockRevokeURL).toHaveBeenCalledWith('blob:mock-url')
  })

  it('서버 오류 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '파일 없음' }),
    })
    const { api } = await import('../lib/api')
    await expect(api.downloadGP5('bad', 'x.gp5')).rejects.toThrow('파일 없음')
  })
})

describe('api.downloadMIDI', () => {
  it('GET /files/:id/export/midi 호출 후 blob 다운로드 트리거', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      blob: async () => new Blob(['MThd']),
    })
    const { api } = await import('../lib/api')
    await api.downloadMIDI('f1', 'my_song.mid')

    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/export/midi',
      expect.objectContaining({ headers: expect.any(Object) })
    )
    expect(lastAnchor?.download).toBe('my_song.mid')
    expect(lastAnchor?.click).toHaveBeenCalled()
  })
})
