import { renderHook, act } from '@testing-library/react'
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
  afterEach(() => { vi.useRealTimers(); vi.clearAllMocks() })

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
})
