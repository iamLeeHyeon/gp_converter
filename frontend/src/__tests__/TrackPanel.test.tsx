import { render, screen } from '@testing-library/react'
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
    useEditorStore.setState({ present: snap1, selectedTrackIndex: 0, activeVoice: 0, fileId: 'f1' } as any)
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

  it('Voice 1/2 토글 버튼 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByRole('button', { name: /Voice 1/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Voice 2/i })).toBeInTheDocument()
  })

  it('Voice 2 클릭 → activeVoice=1 설정', async () => {
    render(<TrackPanel />)
    await userEvent.click(screen.getByRole('button', { name: /Voice 2/i }))
    expect(useEditorStore.getState().activeVoice).toBe(1)
  })

  it('트랙 추가 버튼 클릭 → api.syncFile 호출', async () => {
    const { api } = await import('../lib/api')
    render(<TrackPanel />)
    await userEvent.click(screen.getByRole('button', { name: /트랙 추가/i }))
    expect(api.syncFile).toHaveBeenCalledOnce()
  })
})
