import { renderHook, act, cleanup } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: { syncFile: vi.fn().mockResolvedValue(undefined) },
}))
vi.mock('../store/editorStore', () => ({
  useEditorStore: (sel: any) => {
    let _status = 'idle'
    return sel({
      saveStatus: _status,
      setSaveStatus: (s: string) => { _status = s },
    })
  },
}))

import type { ScoreSnapshot } from '../lib/scoreTypes'

const SNAP: ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 4, den: 4 }, beats: [] }] }],
}

describe('useSyncFile', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => {
    // 언마운트 시 flush(pendingRef 있으면 syncFile 호출)가 새로 생겨서,
    // 이전 테스트에서 마운트된 컴포넌트를 여기서 먼저 명시적으로
    // 정리해야 그 flush 호출이 다음 테스트로 새지 않는다.
    cleanup()
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('3초 후 syncFile을 호출한다', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile('file-1', SNAP))
    expect(api.syncFile).not.toHaveBeenCalled()

    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).toHaveBeenCalledWith('file-1', SNAP)
  })

  it('fileId가 null이면 호출 안 함', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile(null, SNAP))
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).not.toHaveBeenCalled()
  })

  it('snapshot이 null이면 호출 안 함', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile('file-1', null))
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).not.toHaveBeenCalled()
  })

  it('3초 안에 다른 파일로 전환하면 이전 파일의 편집을 즉시 flush한다', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    const { rerender } = renderHook(
      ({ fileId, snapshot }: { fileId: string; snapshot: ScoreSnapshot }) => useSyncFile(fileId, snapshot),
      { initialProps: { fileId: 'file-1', snapshot: SNAP } },
    )
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(api.syncFile).not.toHaveBeenCalled()

    rerender({ fileId: 'file-2', snapshot: SNAP })
    expect(api.syncFile).toHaveBeenCalledWith('file-1', SNAP)
  })

  it('3초 안에 언마운트되면 편집을 즉시 flush한다', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    const { unmount } = renderHook(() => useSyncFile('file-1', SNAP))
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(api.syncFile).not.toHaveBeenCalled()

    unmount()
    expect(api.syncFile).toHaveBeenCalledWith('file-1', SNAP)
  })

  it('이미 저장이 완료됐으면 파일 전환 시 다시 flush하지 않는다', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    const { rerender } = renderHook(
      ({ fileId, snapshot }: { fileId: string; snapshot: ScoreSnapshot }) => useSyncFile(fileId, snapshot),
      { initialProps: { fileId: 'file-1', snapshot: SNAP } },
    )
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(api.syncFile).toHaveBeenCalledTimes(1)

    rerender({ fileId: 'file-2', snapshot: SNAP })
    expect(api.syncFile).toHaveBeenCalledTimes(1)
  })

  it('beforeunload 시 keepalive 옵션으로 flush를 시도한다', async () => {
    const { api } = await import('../lib/api')
    const { useSyncFile } = await import('../lib/useSyncFile')

    renderHook(() => useSyncFile('file-1', SNAP))
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(api.syncFile).not.toHaveBeenCalled()

    window.dispatchEvent(new Event('beforeunload'))
    expect(api.syncFile).toHaveBeenCalledWith('file-1', SNAP, { keepalive: true })
  })
})
