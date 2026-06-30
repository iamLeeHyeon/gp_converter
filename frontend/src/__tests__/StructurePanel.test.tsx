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
const snap2: ScoreSnapshot = {
  tracks: [{
    measures: [
      { timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] },
      { timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] },
    ],
  }],
}

import StructurePanel from '../components/Editor/StructurePanel'

describe('StructurePanel', () => {
  beforeEach(() => {
    useEditorStore.setState({
      present: snap2,
      selectedMeasureIndex: 0,
      fileId: 'f1',
    } as any)
  })

  it('마디 목록 렌더링', () => {
    render(<StructurePanel />)
    expect(screen.getByText(/마디 1/)).toBeInTheDocument()
    expect(screen.getByText(/마디 2/)).toBeInTheDocument()
  })

  it('마디 추가 버튼 존재', () => {
    render(<StructurePanel />)
    expect(screen.getByRole('button', { name: /마디 추가/i })).toBeInTheDocument()
  })

  it('마디 삭제 버튼 존재', () => {
    render(<StructurePanel />)
    expect(screen.getAllByRole('button', { name: /삭제/i }).length).toBeGreaterThan(0)
  })

  it('섹션 마커 입력 필드 존재', () => {
    render(<StructurePanel />)
    expect(screen.getByPlaceholderText(/섹션/i)).toBeInTheDocument()
  })

  it('박자표 num/den 입력 존재', () => {
    render(<StructurePanel />)
    // 박자 numerator input
    const inputs = screen.getAllByRole('spinbutton')
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })
})
