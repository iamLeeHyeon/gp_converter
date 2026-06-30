import { beforeEach, describe, expect, it } from 'vitest'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from '../lib/scoreTypes'

const SNAP_A: ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 4, den: 4 }, beats: [] }] }],
}
const SNAP_B: ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 3, den: 4 }, beats: [] }] }],
}
const SNAP_C: ScoreSnapshot = {
  tracks: [{ measures: [{ timeSignature: { num: 2, den: 4 }, beats: [] }] }],
}

describe('editorStore', () => {
  beforeEach(() => {
    useEditorStore.getState().clearHistory()
    useEditorStore.getState().setSelected(null)
  })

  it('pushSnapshot이 present를 업데이트한다', () => {
    useEditorStore.getState().pushSnapshot(SNAP_A)
    expect(useEditorStore.getState().present).toEqual(SNAP_A)
  })

  it('undo가 이전 스냅샷을 반환한다', () => {
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    const prev = useEditorStore.getState().undo()
    expect(prev).toEqual(SNAP_A)
    expect(useEditorStore.getState().present).toEqual(SNAP_A)
  })

  it('redo가 되돌린 스냅샷을 복원한다', () => {
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    useEditorStore.getState().undo()
    const redone = useEditorStore.getState().redo()
    expect(redone).toEqual(SNAP_B)
    expect(useEditorStore.getState().present).toEqual(SNAP_B)
  })

  it('pushSnapshot이 future를 초기화한다', () => {
    useEditorStore.getState().pushSnapshot(SNAP_A)
    useEditorStore.getState().pushSnapshot(SNAP_B)
    useEditorStore.getState().undo()
    useEditorStore.getState().pushSnapshot(SNAP_C)
    // redo는 불가 (future 초기화됨)
    const redone = useEditorStore.getState().redo()
    expect(redone).toBeNull()
  })

  it('undo가 불가하면 null 반환', () => {
    expect(useEditorStore.getState().undo()).toBeNull()
  })

  it('히스토리 최대 100단계', () => {
    for (let i = 0; i < 105; i++) {
      useEditorStore.getState().pushSnapshot({
        tracks: [{ measures: [{ timeSignature: { num: i, den: 4 }, beats: [] }] }],
      })
    }
    // past는 최대 100개
    expect(useEditorStore.getState()['past'].length).toBeLessThanOrEqual(100)
  })

  it('setSelected와 setFileId가 상태를 업데이트한다', () => {
    const pos = { trackIndex: 0, measureIndex: 1, voiceIndex: 0, beatIndex: 2, noteIndex: 0 }
    useEditorStore.getState().setSelected(pos)
    useEditorStore.getState().setFileId('file-123')
    expect(useEditorStore.getState().selected).toEqual(pos)
    expect(useEditorStore.getState().fileId).toBe('file-123')
  })
})
