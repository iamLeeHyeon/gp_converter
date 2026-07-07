import { render, fireEvent, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from '../lib/scoreTypes'

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
    noteMouseDown: { on: vi.fn() },
    load: vi.fn(),
    playPause: vi.fn(),
    destroy: vi.fn(),
    render: vi.fn(),
    score: null,
  }),
}))
vi.mock('../lib/useSyncFile', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/useSyncFile')>()
  return { ...actual, useSyncFile: vi.fn() }
})
vi.mock('../lib/api', () => ({
  api: {
    syncFile: vi.fn().mockResolvedValue({ ok: true }),
    getGP5Buffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
    downloadGP5: vi.fn(),
    downloadMIDI: vi.fn(),
  },
}))

import ScoreViewer from '../components/Editor/ScoreViewer'

const REST = { duration: 4 as const, dotted: false, status: 'rest' as const, notes: [] }
const SNAP_A: ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] }] }],
}
const SNAP_B: ScoreSnapshot = {
  tracks: [{
    measures: [
      { timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] },
      { timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] },
    ],
  }],
}

describe('ScoreViewer undo/redo 구조 편집 재동기화', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useEditorStore.getState().clearHistory()
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    useEditorStore.setState({ fileId: 'f1', gp5Buffer: null })
  })

  it('Ctrl+Z → 이전 스냅샷 백엔드 재동기화 후 gp5Buffer 리로드', async () => {
    const { api } = await import('../lib/api')
    render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)

    fireEvent.keyDown(window, { key: 'z', ctrlKey: true })

    await waitFor(() => expect(api.syncFile).toHaveBeenCalledWith('f1', SNAP_A))
    expect(api.getGP5Buffer).toHaveBeenCalledWith('f1')
    await waitFor(() => expect(useEditorStore.getState().gp5Buffer).not.toBeNull())
  })
})
