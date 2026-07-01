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
    vi.clearAllMocks()
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

  it('박자표 num 입력 + den 셀렉트 존재', () => {
    render(<StructurePanel />)
    const spinbuttons = screen.getAllByRole('spinbutton')
    expect(spinbuttons.length).toBeGreaterThanOrEqual(1)  // num input
    const selects = screen.getAllByRole('combobox')
    expect(selects.length).toBeGreaterThanOrEqual(1)  // den select (+ key sig select)
  })

  it('마디 추가 버튼 클릭 → api.syncFile 호출', async () => {
    const { api } = await import('../lib/api')
    render(<StructurePanel />)
    await userEvent.click(screen.getByRole('button', { name: /마디 추가/i }))
    expect(api.syncFile).toHaveBeenCalledOnce()
  })

  it('삭제 버튼 클릭 → api.syncFile 호출 (2개 마디일 때)', async () => {
    const { api } = await import('../lib/api')
    render(<StructurePanel />)
    const deleteButtons = screen.getAllByRole('button', { name: /삭제/i })
    await userEvent.click(deleteButtons[0])
    expect(api.syncFile).toHaveBeenCalledOnce()
  })

  it('마지막 마디 선택 후 삭제 → selectedMeasureIndex가 새 길이 범위로 클램프', async () => {
    useEditorStore.setState({ present: snap2, selectedMeasureIndex: 1, fileId: 'f1' } as any)
    render(<StructurePanel />)
    const deleteButtons = screen.getAllByRole('button', { name: /삭제/i })
    await userEvent.click(deleteButtons[1]) // 마디 2 (index 1) 삭제 → 남은 1개, 유효 인덱스 0
    expect(useEditorStore.getState().selectedMeasureIndex).toBe(0)
  })
})
