import { describe, it, expect, beforeEach } from 'vitest'
import { useEditorStore } from '../store/editorStore'

describe('editorStore v2 상태', () => {
  beforeEach(() => {
    useEditorStore.setState({
      selectedTrackIndex: 0,
      selectedMeasureIndex: 0,
      activeVoice: 0,
      gp5Buffer: null,
    })
  })

  it('selectedTrackIndex 초기값 0', () => {
    expect(useEditorStore.getState().selectedTrackIndex).toBe(0)
  })

  it('selectedMeasureIndex 초기값 0', () => {
    expect(useEditorStore.getState().selectedMeasureIndex).toBe(0)
  })

  it('activeVoice 초기값 0', () => {
    expect(useEditorStore.getState().activeVoice).toBe(0)
  })

  it('setGp5Buffer로 gp5Buffer 업데이트', () => {
    const buf = new ArrayBuffer(8)
    useEditorStore.getState().setGp5Buffer(buf)
    expect(useEditorStore.getState().gp5Buffer).toBe(buf)
  })

  it('selectedTrackIndex 변경', () => {
    useEditorStore.setState({ selectedTrackIndex: 2 })
    expect(useEditorStore.getState().selectedTrackIndex).toBe(2)
  })

  it('activeVoice 토글 0↔1', () => {
    useEditorStore.setState({ activeVoice: 1 })
    expect(useEditorStore.getState().activeVoice).toBe(1)
  })
})
