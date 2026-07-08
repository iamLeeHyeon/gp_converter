import { useState, useEffect, type ReactNode } from 'react'
import type { NotePosition, Dynamic, Effect } from '../../lib/scoreTypes'
import type { EditPayload } from '../../lib/scoreApplier'

interface Props {
  selectedPosition: NotePosition | null
  currentBeat: {
    duration: number
    dotted: boolean
    status: string
    dynamic?: Dynamic
    strumDown?: boolean
  } | null
  currentNote: { string: number; fret: number; effect?: Effect } | null
  onEditBeat: (edit: EditPayload) => void
  onEditNote: (edit: EditPayload) => void
}

const DURATIONS: Array<1 | 2 | 4 | 8 | 16 | 32> = [1, 2, 4, 8, 16, 32]
const DYNAMICS: Dynamic[] = ['ppp', 'pp', 'p', 'mp', 'mf', 'f', 'ff', 'fff']
const EFFECTS: Array<{ value: Effect; label: string }> = [
  { value: 'hammer-on', label: 'H' },
  { value: 'slide-shift', label: 'SS' },
  { value: 'slide-legato', label: 'SL' },
  { value: 'slide-in-above', label: 'Si↑' },
  { value: 'slide-out-below', label: 'So↓' },
  { value: 'mute', label: 'X' },
  { value: 'ghost', label: '( )' },
  { value: 'harmonic', label: '⬦' },
]

function Chip({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      style={{
        border: active ? 'none' : '1px solid var(--color-border)',
        background: active ? 'var(--color-primary)' : 'var(--color-surface)',
        color: active ? '#ffffff' : 'var(--color-ink)',
        borderRadius: 6,
        padding: '4px 10px',
        fontSize: 12,
        fontWeight: active ? 700 : 500,
        cursor: 'pointer',
      }}
    >
      {children}
    </button>
  )
}

export default function EditPanel({ selectedPosition, currentBeat, currentNote, onEditBeat, onEditNote }: Props) {
  const [fretInput, setFretInput] = useState<string>(String(currentNote?.fret ?? ''))

  useEffect(() => {
    setFretInput(String(currentNote?.fret ?? ''))
  }, [currentNote?.fret])

  if (!selectedPosition || !currentBeat) {
    return (
      <div style={{ padding: 16, color: 'var(--color-muted)', fontSize: 13 }}>
        음표를 클릭하면 편집할 수 있습니다
      </div>
    )
  }

  const handleFretCommit = () => {
    const val = parseInt(fretInput, 10)
    if (!isNaN(val) && val >= 0 && val <= 24) {
      onEditNote({ type: 'fret', value: val })
    }
  }

  return (
    <div style={{ padding: 12, fontSize: 13, display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* 지속시간 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink)' }}>지속시간</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DURATIONS.map((d) => (
            <Chip key={d} active={currentBeat.duration === d} onClick={() => onEditBeat({ type: 'duration', value: d })}>
              {d}
            </Chip>
          ))}
          <Chip active={currentBeat.dotted} onClick={() => onEditBeat({ type: 'dotted', value: !currentBeat.dotted })}>
            점음표
          </Chip>
        </div>
      </section>

      {/* 다이나믹 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink)' }}>다이나믹</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DYNAMICS.map((d) => (
            <Chip key={d} active={currentBeat.dynamic === d} onClick={() => onEditBeat({ type: 'dynamic', value: d })}>
              {d}
            </Chip>
          ))}
        </div>
      </section>

      {/* 스트럼 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink)' }}>스트럼</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <Chip active={currentBeat.strumDown === true} onClick={() => onEditBeat({ type: 'strumDown', value: true })}>▼</Chip>
          <Chip active={currentBeat.strumDown === false} onClick={() => onEditBeat({ type: 'strumDown', value: false })}>▲</Chip>
          <Chip active={currentBeat.strumDown === undefined} onClick={() => onEditBeat({ type: 'strumDown', value: undefined })}>없음</Chip>
        </div>
      </section>

      {/* 음표 추가 */}
      <section>
        <button onClick={() => onEditBeat({ type: 'addNote' })} className="btn-ghost">+ 음표 추가</button>
      </section>

      {/* 음표 편집 (음표가 선택된 경우) */}
      {currentNote && selectedPosition.noteIndex !== null && (
        <>
          <hr style={{ margin: '4px 0', border: 'none', borderTop: '1px solid var(--color-border)' }} />

          <section>
            <label htmlFor="fret-input" style={{ fontWeight: 600, color: 'var(--color-ink)' }}>프렛</label>
            <input
              id="fret-input"
              type="number"
              min={0}
              max={24}
              value={fretInput}
              onChange={(e) => setFretInput(e.target.value)}
              onBlur={handleFretCommit}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFretCommit() }}
              className="field"
              style={{ width: 56, marginLeft: 8, padding: '4px 8px' }}
            />
          </section>

          <section>
            <div style={{ fontWeight: 600, marginBottom: 6, color: 'var(--color-ink)' }}>이펙트</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              <Chip active={!currentNote.effect} onClick={() => onEditNote({ type: 'effect', value: null })}>없음</Chip>
              {EFFECTS.map(({ value, label }) => (
                <Chip key={value} active={currentNote.effect === value} onClick={() => onEditNote({ type: 'effect', value })}>
                  {label}
                </Chip>
              ))}
            </div>
          </section>

          <section>
            <button onClick={() => onEditNote({ type: 'deleteNote' })} style={{ color: 'var(--color-danger)', background: 'none', border: '1px solid var(--color-danger)', borderRadius: 6, padding: '6px 12px', fontSize: 12, cursor: 'pointer' }}>× 음표 삭제</button>
          </section>
        </>
      )}
    </div>
  )
}
