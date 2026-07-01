import { useEffect, useRef, useState } from 'react'
import { useEditorStore } from '../../store/editorStore'
import { applyStructuralEdit } from '../../lib/structuralEdit'
import { api } from '../../lib/api'
import type { ScoreSnapshot } from '../../lib/scoreTypes'

const NAME_SYNC_DEBOUNCE_MS = 500

const TUNING_PRESETS: Record<string, number[]> = {
  'Standard E': [64, 59, 55, 50, 45, 40],
  'Drop D':     [64, 59, 55, 50, 45, 38],
  'Open G':     [62, 59, 55, 50, 47, 38],
  'DADGAD':     [62, 57, 55, 50, 45, 38],
}

function detectPreset(tuning: number[] | undefined): string {
  if (!tuning) return 'Standard E'
  for (const [name, vals] of Object.entries(TUNING_PRESETS)) {
    if (vals.every((v, i) => v === tuning[i])) return name
  }
  return 'Custom'
}

export default function TrackPanel() {
  const { present, selectedTrackIndex, activeVoice, fileId, pushSnapshot, setGp5Buffer, setSaveStatus } =
    useEditorStore()
  const [busy, setBusy] = useState(false)
  const nameSyncTimer = useRef<ReturnType<typeof setTimeout>>(undefined)

  useEffect(() => () => clearTimeout(nameSyncTimer.current), [])

  if (!present) return null

  const tracks = present.tracks
  const track = tracks[selectedTrackIndex]

  async function syncSnapshot(snap: ScoreSnapshot) {
    if (!fileId) return
    setBusy(true)
    try {
      setSaveStatus('saving')
      await api.syncFile(fileId, snap)
      const buf = await api.getGP5Buffer(fileId)
      setGp5Buffer(buf)
      setSaveStatus('saved')
    } catch {
      setSaveStatus('error')
    } finally {
      setBusy(false)
    }
  }

  async function applyAndSync(edit: Parameters<typeof applyStructuralEdit>[1]) {
    if (!present || !fileId) return
    const next = applyStructuralEdit(present, edit)
    pushSnapshot(next)
    const newLen = next.tracks.length
    if (selectedTrackIndex > newLen - 1) {
      useEditorStore.setState({ selectedTrackIndex: Math.max(0, newLen - 1) })
    }
    await syncSnapshot(next)
  }

  // 이름 입력은 로컬 반영은 즉시, 백엔드 재동기화(+alphaTab 리로드)는 디바운스
  function handleNameChange(name: string) {
    if (!present) return
    const next = applyStructuralEdit(present, { type: 'setTrackName', trackIndex: selectedTrackIndex, name })
    pushSnapshot(next)
    clearTimeout(nameSyncTimer.current)
    nameSyncTimer.current = setTimeout(() => { syncSnapshot(next) }, NAME_SYNC_DEBOUNCE_MS)
  }

  const currentPreset = detectPreset(track?.tuning)

  return (
    <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <strong>트랙</strong>

      {/* 트랙 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {tracks.map((t, i) => (
          <div
            key={i}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: i === selectedTrackIndex ? '#ddf' : undefined,
              cursor: 'pointer', padding: '2px 4px',
            }}
            onClick={() => useEditorStore.setState({ selectedTrackIndex: i })}
          >
            <span style={{ flex: 1, fontSize: 12 }}>🎸 {t.name ?? `Track ${i + 1}`}</span>
            <button
              style={{ fontSize: 10, color: 'red' }}
              disabled={busy || tracks.length <= 1}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'deleteTrack', trackIndex: i }) }}
            >×</button>
          </div>
        ))}
      </div>

      <button disabled={busy} onClick={() => applyAndSync({ type: 'addTrack' })}>
        트랙 추가
      </button>

      {track && (
        <div style={{ borderTop: '1px solid #ddd', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <strong style={{ fontSize: 12 }}>트랙 {selectedTrackIndex + 1} 속성</strong>

          {/* 트랙 이름 */}
          <label style={{ fontSize: 12 }}>
            이름:
            <input
              type="text"
              style={{ marginLeft: 4, width: 100 }}
              value={track.name ?? ''}
              onChange={e => handleNameChange(e.target.value)}
            />
          </label>

          {/* 튜닝 프리셋 */}
          <label style={{ fontSize: 12 }}>
            튜닝:
            <select
              aria-label="튜닝"
              style={{ marginLeft: 4 }}
              value={currentPreset === 'Custom' ? 'Custom' : currentPreset}
              onChange={e => {
                const preset = TUNING_PRESETS[e.target.value]
                if (preset) applyAndSync({ type: 'setTuning', trackIndex: selectedTrackIndex, tuning: preset })
              }}
            >
              {Object.keys(TUNING_PRESETS).map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
              {currentPreset === 'Custom' && <option value="Custom">Custom</option>}
            </select>
          </label>

          {/* Capo */}
          <label style={{ fontSize: 12 }}>
            Capo:
            <input
              aria-label="Capo"
              type="number" min={0} max={12}
              style={{ width: 48, marginLeft: 4 }}
              value={track.capo ?? 0}
              onChange={e => applyAndSync({ type: 'setCapo', trackIndex: selectedTrackIndex, capo: Number(e.target.value) })}
            />
          </label>

          {/* Voice 토글 */}
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              style={{ fontWeight: activeVoice === 0 ? 'bold' : undefined }}
              onClick={() => useEditorStore.setState({ activeVoice: 0 })}
            >Voice 1</button>
            <button
              style={{ fontWeight: activeVoice === 1 ? 'bold' : undefined }}
              onClick={() => useEditorStore.setState({ activeVoice: 1 })}
            >Voice 2</button>
          </div>
        </div>
      )}
    </div>
  )
}
