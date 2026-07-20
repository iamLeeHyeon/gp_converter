import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from '../lib/scoreTypes'

vi.mock('../lib/api', () => ({
  api: {
    syncFile: vi.fn().mockResolvedValue({ ok: true }),
    getGP5Buffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
  },
}))

const REST = { duration: 4 as const, dotted: false, status: 'rest' as const, notes: [] }
const snap1: ScoreSnapshot = {
  tracks: [{
    name: 'Guitar',
    tuning: [64, 59, 55, 50, 45, 40],
    capo: 0,
    measures: [{ timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] }],
  }],
}

import TrackPanel from '../components/Editor/TrackPanel'

describe('TrackPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useEditorStore.setState({ present: snap1, selectedTrackIndex: 0, fileId: 'f1' } as any)
  })

  it('트랙 목록 렌더링', () => {
    render(<TrackPanel />)
    expect(screen.getByText(/Guitar/)).toBeInTheDocument()
  })

  it('트랙 추가 버튼 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByRole('button', { name: /트랙 추가/i })).toBeInTheDocument()
  })

  it('튜닝 프리셋 셀렉트 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByRole('combobox', { name: /튜닝/i })).toBeInTheDocument()
  })

  it('Capo 입력 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByLabelText(/Capo/i)).toBeInTheDocument()
  })

  it('트랙 추가 버튼 클릭 → api.syncFile 호출', async () => {
    const { api } = await import('../lib/api')
    render(<TrackPanel />)
    await userEvent.click(screen.getByRole('button', { name: /트랙 추가/i }))
    expect(api.syncFile).toHaveBeenCalledOnce()
  })

  it('이름 입력 → 500ms 디바운스 후 1회만 syncFile 호출', async () => {
    const { api } = await import('../lib/api')
    render(<TrackPanel />)
    const input = screen.getByLabelText(/이름/i)

    vi.useFakeTimers()
    try {
      fireEvent.change(input, { target: { value: 'L' } })
      fireEvent.change(input, { target: { value: 'Le' } })
      fireEvent.change(input, { target: { value: 'Lea' } })
      fireEvent.change(input, { target: { value: 'Lead' } })

      expect(api.syncFile).not.toHaveBeenCalled() // 디바운스 중에는 호출 안 됨

      await vi.advanceTimersByTimeAsync(500)

      expect(api.syncFile).toHaveBeenCalledOnce()
      expect(api.syncFile).toHaveBeenCalledWith('f1', expect.objectContaining({
        tracks: [expect.objectContaining({ name: 'Lead' })],
      }))
    } finally {
      vi.useRealTimers()
    }
  })

  it('마지막 트랙 선택 후 삭제 → selectedTrackIndex가 새 길이 범위로 클램프', async () => {
    const snap2: ScoreSnapshot = {
      tracks: [
        { name: 'Guitar', tuning: [64, 59, 55, 50, 45, 40], capo: 0, measures: snap1.tracks[0].measures },
        { name: 'Bass', tuning: [43, 38, 33, 28], capo: 0, measures: snap1.tracks[0].measures },
      ],
    }
    useEditorStore.setState({ present: snap2, selectedTrackIndex: 1, fileId: 'f1' } as any)
    render(<TrackPanel />)
    const deleteButtons = screen.getAllByRole('button', { name: '×' })
    await userEvent.click(deleteButtons[1]) // 트랙 2 (index 1) 삭제 → 남은 1개, 유효 인덱스 0
    expect(useEditorStore.getState().selectedTrackIndex).toBe(0)
  })
})
