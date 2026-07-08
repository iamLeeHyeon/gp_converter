import { useState } from 'react'
import { useEditorStore } from '../../store/editorStore'
import { applyStructuralEdit } from '../../lib/structuralEdit'
import { syncAndReload } from '../../lib/useSyncFile'

const KEY_SIG_LABELS: Record<string, string> = {
  '-7': 'Cb', '-6': 'Gb', '-5': 'Db', '-4': 'Ab',
  '-3': 'Eb', '-2': 'Bb', '-1': 'F',
  '0': 'C', '1': 'G', '2': 'D', '3': 'A',
  '4': 'E', '5': 'B', '6': 'F#', '7': 'C#',
}

export default function StructurePanel() {
  const { present, selectedMeasureIndex, fileId, pushSnapshot } =
    useEditorStore()
  const [busy, setBusy] = useState(false)

  if (!present) return null

  const measures = present.tracks[0]?.measures ?? []
  const selected = measures[selectedMeasureIndex]

  async function applyAndSync(edit: Parameters<typeof applyStructuralEdit>[1]) {
    if (!present || !fileId) return
    setBusy(true)
    const next = applyStructuralEdit(present, edit)
    pushSnapshot(next)
    const newLen = next.tracks[0]?.measures.length ?? 0
    if (selectedMeasureIndex > newLen - 1) {
      useEditorStore.setState({ selectedMeasureIndex: Math.max(0, newLen - 1) })
    }
    await syncAndReload(fileId, next)
    setBusy(false)
  }

  return (
    <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <strong style={{ fontSize: 13, color: 'var(--color-ink)' }}>마디 구조</strong>

      {/* 마디 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
        {measures.map((m, i) => (
          <div
            key={i}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: i === selectedMeasureIndex ? 'var(--color-primary-light)' : undefined,
              borderRadius: 6,
              cursor: 'pointer', padding: '4px 6px',
            }}
            onClick={() => useEditorStore.setState({ selectedMeasureIndex: i })}
          >
            <span style={{ flex: 1, fontSize: 12, color: i === selectedMeasureIndex ? 'var(--color-ink)' : 'var(--color-muted)' }}>
              마디 {i + 1}
              {m.sectionMarker ? ` [${m.sectionMarker}]` : ''}
            </span>
            <button
              style={{ fontSize: 10 }}
              className="btn-ghost"
              disabled={busy}
              aria-label={`마디 ${i + 1} 위로`}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'moveMeasure', from: i, to: i - 1 }) }}
            >↑</button>
            <button
              style={{ fontSize: 10 }}
              className="btn-ghost"
              disabled={busy}
              aria-label={`마디 ${i + 1} 아래로`}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'moveMeasure', from: i, to: i + 1 }) }}
            >↓</button>
            <button
              style={{ fontSize: 10, color: 'var(--color-danger)', background: 'none', border: 'none', cursor: 'pointer' }}
              disabled={busy || measures.length <= 1}
              aria-label={`마디 ${i + 1} 삭제`}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'deleteMeasure', index: i }) }}
            >삭제</button>
          </div>
        ))}
      </div>

      <button
        disabled={busy}
        className="btn-ghost"
        onClick={() => applyAndSync({ type: 'addMeasure', afterIndex: selectedMeasureIndex })}
      >
        마디 추가
      </button>

      {selected && (
        <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <strong style={{ fontSize: 12, color: 'var(--color-ink)' }}>선택 마디 속성</strong>

          {/* 박자표 — num/den 모두 spinbutton */}
          <label style={{ fontSize: 12 }}>
            박자표:
            <input
              type="number"
              min={1}
              max={16}
              style={{ width: 40, marginLeft: 4 }}
              value={selected.timeSignature.num}
              onChange={e => applyAndSync({
                type: 'setTimeSignature',
                measureIndex: selectedMeasureIndex,
                num: Number(e.target.value),
                den: selected.timeSignature.den,
              })}
            />
            {' / '}
            <select
              style={{ marginLeft: 4 }}
              value={selected.timeSignature.den}
              onChange={e => applyAndSync({
                type: 'setTimeSignature',
                measureIndex: selectedMeasureIndex,
                num: selected.timeSignature.num,
                den: Number(e.target.value),
              })}
            >
              {[2, 4, 8, 16].map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>

          {/* 조표 */}
          <label style={{ fontSize: 12 }}>
            조표:
            <select
              style={{ marginLeft: 4 }}
              value={selected.keySignature ?? 0}
              onChange={e => applyAndSync({
                type: 'setKeySignature',
                measureIndex: selectedMeasureIndex,
                key: Number(e.target.value),
              })}
            >
              {Object.entries(KEY_SIG_LABELS).map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
          </label>

          {/* 섹션 마커 */}
          <label style={{ fontSize: 12 }}>
            섹션:
            <input
              type="text"
              placeholder="섹션 이름 (예: Intro)"
              style={{ marginLeft: 4, width: 120 }}
              value={selected.sectionMarker ?? ''}
              onChange={e => applyAndSync({
                type: 'setSectionMarker',
                measureIndex: selectedMeasureIndex,
                name: e.target.value || null,
              })}
            />
          </label>
        </div>
      )}
    </div>
  )
}
