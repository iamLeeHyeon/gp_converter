import { useState, useEffect } from 'react'
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

export default function EditPanel({ selectedPosition, currentBeat, currentNote, onEditBeat, onEditNote }: Props) {
  const [fretInput, setFretInput] = useState<string>(String(currentNote?.fret ?? ''))

  useEffect(() => {
    setFretInput(String(currentNote?.fret ?? ''))
  }, [currentNote?.fret])

  if (!selectedPosition || !currentBeat) {
    return (
      <div style={{ padding: 16, color: '#888', fontSize: 13 }}>
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
        <div style={{ fontWeight: 600, marginBottom: 4 }}>지속시간</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DURATIONS.map((d) => (
            <button
              key={d}
              onClick={() => onEditBeat({ type: 'duration', value: d })}
              style={{ fontWeight: currentBeat.duration === d ? 700 : 400 }}
            >
              {d}
            </button>
          ))}
          <button
            onClick={() => onEditBeat({ type: 'dotted', value: !currentBeat.dotted })}
            style={{ fontWeight: currentBeat.dotted ? 700 : 400 }}
          >
            점음표
          </button>
        </div>
      </section>

      {/* 다이나믹 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>다이나믹</div>
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
          {DYNAMICS.map((d) => (
            <button
              key={d}
              onClick={() => onEditBeat({ type: 'dynamic', value: d })}
              style={{ fontWeight: currentBeat.dynamic === d ? 700 : 400 }}
            >
              {d}
            </button>
          ))}
        </div>
      </section>

      {/* 스트럼 */}
      <section>
        <div style={{ fontWeight: 600, marginBottom: 4 }}>스트럼</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <button
            onClick={() => onEditBeat({ type: 'strumDown', value: true })}
            style={{ fontWeight: currentBeat.strumDown === true ? 700 : 400 }}
          >
            ▼
          </button>
          <button
            onClick={() => onEditBeat({ type: 'strumDown', value: false })}
            style={{ fontWeight: currentBeat.strumDown === false ? 700 : 400 }}
          >
            ▲
          </button>
          <button onClick={() => onEditBeat({ type: 'strumDown', value: undefined })}>없음</button>
        </div>
      </section>

      {/* 음표 추가 */}
      <section>
        <button onClick={() => onEditBeat({ type: 'addNote' })}>+ 음표 추가</button>
      </section>

      {/* 음표 편집 (음표가 선택된 경우) */}
      {currentNote && selectedPosition.noteIndex !== null && (
        <>
          <hr style={{ margin: '4px 0' }} />

          <section>
            <label htmlFor="fret-input" style={{ fontWeight: 600 }}>프렛</label>
            <input
              id="fret-input"
              type="number"
              min={0}
              max={24}
              value={fretInput}
              onChange={(e) => setFretInput(e.target.value)}
              onBlur={handleFretCommit}
              onKeyDown={(e) => { if (e.key === 'Enter') handleFretCommit() }}
              style={{ width: 56, marginLeft: 8 }}
            />
          </section>

          <section>
            <div style={{ fontWeight: 600, marginBottom: 4 }}>이펙트</div>
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
              <button
                onClick={() => onEditNote({ type: 'effect', value: null })}
                style={{ fontWeight: !currentNote.effect ? 700 : 400 }}
              >
                없음
              </button>
              {EFFECTS.map(({ value, label }) => (
                <button
                  key={value}
                  onClick={() => onEditNote({ type: 'effect', value })}
                  style={{ fontWeight: currentNote.effect === value ? 700 : 400 }}
                >
                  {label}
                </button>
              ))}
            </div>
          </section>

          <section>
            <button onClick={() => onEditNote({ type: 'deleteNote' })}>× 음표 삭제</button>
          </section>
        </>
      )}
    </div>
  )
}
