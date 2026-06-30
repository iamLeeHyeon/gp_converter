import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect } from 'vitest'
import EditPanel from '../components/Editor/EditPanel'
import type { NotePosition } from '../lib/scoreTypes'

const POS: NotePosition = { trackIndex: 0, measureIndex: 0, voiceIndex: 0, beatIndex: 0, noteIndex: 0 }
const BEAT = { duration: 4, dotted: false, status: 'normal', dynamic: 'mf' as const }
const NOTE = { string: 1, fret: 5 }

describe('EditPanel', () => {
  it('선택 없으면 안내 문구를 표시한다', () => {
    render(<EditPanel selectedPosition={null} currentBeat={null} currentNote={null} onEditBeat={vi.fn()} onEditNote={vi.fn()} />)
    expect(screen.getByText(/음표를 클릭/i)).toBeInTheDocument()
  })

  it('프렛 값을 표시한다', () => {
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={vi.fn()} />)
    const input = screen.getByLabelText(/프렛/i) as HTMLInputElement
    expect(input.value).toBe('5')
  })

  it('프렛 변경 시 onEditNote를 호출한다', async () => {
    const onEditNote = vi.fn()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={onEditNote} />)
    const input = screen.getByLabelText(/프렛/i)
    await userEvent.clear(input)
    await userEvent.type(input, '7')
    await userEvent.keyboard('{Enter}')
    expect(onEditNote).toHaveBeenCalledWith({ type: 'fret', value: 7 })
  })

  it('지속시간 버튼 클릭 시 onEditBeat를 호출한다', async () => {
    const onEditBeat = vi.fn()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={onEditBeat} onEditNote={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: '8' }))
    expect(onEditBeat).toHaveBeenCalledWith({ type: 'duration', value: 8 })
  })

  it('음표 추가 버튼이 존재한다', () => {
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={null} onEditBeat={vi.fn()} onEditNote={vi.fn()} />)
    expect(screen.getByRole('button', { name: /추가|add|\+/i })).toBeInTheDocument()
  })

  it('음표 삭제 버튼 클릭 시 onEditNote를 호출한다', async () => {
    const onEditNote = vi.fn()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={onEditNote} />)
    await userEvent.click(screen.getByRole('button', { name: /삭제|delete|×/i }))
    expect(onEditNote).toHaveBeenCalledWith({ type: 'deleteNote' })
  })

  it('다이나믹 버튼 클릭 시 onEditBeat를 호출한다', async () => {
    const onEditBeat = vi.fn()
    const user = userEvent.setup()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={onEditBeat} onEditNote={vi.fn()} />)
    await user.click(screen.getByRole('button', { name: 'f' }))
    expect(onEditBeat).toHaveBeenCalledWith({ type: 'dynamic', value: 'f' })
  })

  it('이펙트 버튼 클릭 시 onEditNote를 호출한다', async () => {
    const onEditNote = vi.fn()
    const user = userEvent.setup()
    render(<EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={onEditNote} />)
    // 이펙트 섹션 내 '없음' 버튼 (스트럼 섹션에도 같은 이름 버튼이 있으므로 getAllByRole 사용)
    const noneButtons = screen.getAllByRole('button', { name: /없음/i })
    // 이펙트 섹션의 '없음' 버튼은 마지막 '없음' 버튼
    await user.click(noneButtons[noneButtons.length - 1])
    expect(onEditNote).toHaveBeenCalledWith({ type: 'effect', value: null })
  })

  it('fretInput이 currentNote.fret 변경 시 동기화된다', () => {
    const { rerender } = render(
      <EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={NOTE} onEditBeat={vi.fn()} onEditNote={vi.fn()} />
    )
    expect((screen.getByLabelText(/프렛/i) as HTMLInputElement).value).toBe('5')

    rerender(
      <EditPanel selectedPosition={POS} currentBeat={BEAT} currentNote={{ string: 1, fret: 12 }} onEditBeat={vi.fn()} onEditNote={vi.fn()} />
    )
    expect((screen.getByLabelText(/프렛/i) as HTMLInputElement).value).toBe('12')
  })
})
