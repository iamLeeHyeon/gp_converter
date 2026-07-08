import { useEffect, useRef, useState, useCallback, type CSSProperties } from 'react'
import { initAlphaTab } from '../../lib/alphatab'
import type * as alphaTab from '@coderline/alphatab'
import { useEditorStore } from '../../store/editorStore'
import { serializeScore, serializeBeat, getNoteEffect } from '../../lib/scoreSerializer'
import { applyEdit, type EditPayload } from '../../lib/scoreApplier'
import { useSyncFile, syncAndReload as syncFileAndReload } from '../../lib/useSyncFile'
import EditPanel from './EditPanel'
import ExportMenu from './ExportMenu'
import StructurePanel from './StructurePanel'
import TrackPanel from './TrackPanel'
import type { NotePosition, ScoreSnapshot } from '../../lib/scoreTypes'

interface Props {
  gp5Buffer: ArrayBuffer | null
}

export default function ScoreViewer({ gp5Buffer }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const [playing, setPlaying] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [leftTab, setLeftTab] = useState<'files' | 'tracks'>('files')

  const { selected, fileId, present, saveStatus, setSelected, pushSnapshot, undo, redo } = useEditorStore()
  const storeGp5Buffer = useEditorStore(s => s.gp5Buffer)

  // 현재 선택된 beat/note 정보 추출 (scoreSerializer의 직렬화 로직 재사용)
  const currentBeat = (() => {
    if (!selected || !apiRef.current?.score) return null
    try {
      const beat = (apiRef.current.score as any).tracks[selected.trackIndex]
        ?.staves[0]?.bars[selected.measureIndex]
        ?.voices[selected.voiceIndex]?.beats[selected.beatIndex]
      if (!beat) return null
      return serializeBeat(beat)
    } catch { return null }
  })()

  const currentNote = (() => {
    if (!selected || selected.noteIndex === null || !apiRef.current?.score) return null
    try {
      const beat = (apiRef.current.score as any).tracks[selected.trackIndex]
        ?.staves[0]?.bars[selected.measureIndex]
        ?.voices[selected.voiceIndex]?.beats[selected.beatIndex]
      const note = beat?.notes[selected.noteIndex]
      if (!note) return null
      return { string: note.string, fret: note.fret, effect: getNoteEffect(note) }
    } catch { return null }
  })()

  const commitEdit = useCallback((edit: EditPayload) => {
    if (!apiRef.current?.score || !selected) return
    applyEdit(apiRef.current.score, selected, edit)
    const snap = serializeScore(apiRef.current.score)
    pushSnapshot(snap)
    apiRef.current.render()
  }, [selected, pushSnapshot])

  // undo/redo: 구조 편집(마디/트랙 추가삭제 등)은 alphaTab 인플레이스 반영 불가 → 백엔드 재동기화 후 리로드
  const syncAndReload = useCallback(async (snap: ScoreSnapshot) => {
    if (!fileId) return
    await syncFileAndReload(fileId, snap)
  }, [fileId])

  // 자동저장
  useSyncFile(fileId, present)

  // alphaTab 초기화
  useEffect(() => {
    if (!containerRef.current) return
    const api = initAlphaTab(containerRef.current)
    apiRef.current = api

    api.scoreLoaded.on(() => setLoaded(true))
    api.playerStateChanged.on((e: any) => setPlaying(e.state === 1))
    api.noteMouseDown.on((note: any) => {
      const pos: NotePosition = {
        trackIndex: 0,
        measureIndex: note.beat.voice.bar.index as number,
        voiceIndex: note.beat.voice.index as number,
        beatIndex: note.beat.index as number,
        noteIndex: note.index as number,
      }
      setSelected(pos)
    })

    return () => { api.destroy(); apiRef.current = null }
  }, [setSelected])

  // GP5 로드
  useEffect(() => {
    if (!apiRef.current || !gp5Buffer) return
    setLoaded(false)
    setSelected(null)
    apiRef.current.load(gp5Buffer)
  }, [gp5Buffer, setSelected])

  // 키보드 단축키
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey
      if (mod && !e.shiftKey && e.key === 'z') {
        e.preventDefault()
        const prev = undo()
        if (prev) syncAndReload(prev)
      } else if (mod && (e.shiftKey && e.key === 'z' || e.key === 'y')) {
        e.preventDefault()
        const next = redo()
        if (next) syncAndReload(next)
      } else if (e.key === 'Delete' && selected) {
        commitEdit({ type: 'deleteNote' })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo, selected, commitEdit, syncAndReload])

  // 구조 편집 후 store gp5Buffer 변경 시 alphaTab 리로드
  useEffect(() => {
    if (!storeGp5Buffer || !apiRef.current) return
    apiRef.current.load(storeGp5Buffer)
  }, [storeGp5Buffer])

  // 악보 영역(containerRef)은 gp5Buffer 유무와 무관하게 항상 마운트돼 있어야
  // 한다 — alphaTab 초기화 effect는 [setSelected]에만 의존해서 최초 마운트
  // 시 딱 한 번만 실행되는데, 예전엔 gp5Buffer가 null일 때 이 div 자체가
  // 렌더링되는 다른 분기(조건부 early return)로 빠져서 containerRef.current가
  // 그 시점에 계속 null이었다 — 이후 gp5Buffer가 생겨도 effect가 재실행되지
  // 않아 alphaTab이 영영 초기화되지 않는 버그가 있었다(실제 앱에서 재현 확인).
  const tabButtonStyle = (active: boolean): CSSProperties => ({
    flex: 1,
    padding: '10px 0',
    background: 'none',
    border: 'none',
    borderBottom: active ? '2px solid var(--color-primary)' : '2px solid transparent',
    color: active ? 'var(--color-primary)' : 'var(--color-muted)',
    fontWeight: active ? 700 : 500,
    fontSize: 13,
    cursor: 'pointer',
  })

  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--color-bg)' }}>
      {/* 좌측 탭 패널: 파일 | 트랙 */}
      {gp5Buffer && (
        <aside style={{ width: 200, background: 'var(--color-surface)', borderRight: '1px solid var(--color-border)', overflow: 'auto', flexShrink: 0 }}>
          <div style={{ display: 'flex', borderBottom: '1px solid var(--color-border)' }}>
            <button style={tabButtonStyle(leftTab === 'files')} onClick={() => setLeftTab('files')}>파일</button>
            <button style={tabButtonStyle(leftTab === 'tracks')} onClick={() => setLeftTab('tracks')}>트랙</button>
          </div>
          {leftTab === 'files'
            ? <div style={{ padding: 12, fontSize: 12, color: 'var(--color-muted)' }}>파일 목록은 왼쪽 사이드바를 이용하세요</div>
            : <TrackPanel />
          }
        </aside>
      )}

      {/* 악보 영역 */}
      <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        {!gp5Buffer ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', textAlign: 'center' }}>
            <div>
              <h2 style={{ fontSize: '1.25rem', color: 'var(--color-ink)' }}>악보를 불러오세요</h2>
              <p style={{ marginTop: 8, fontSize: 14, color: 'var(--color-muted)' }}>PDF를 업로드하거나 왼쪽 목록에서 파일을 선택하세요</p>
            </div>
          </div>
        ) : (
          <div style={{ padding: '12px 16px', display: 'flex', gap: 8, alignItems: 'center', borderBottom: '1px solid var(--color-border)', background: 'var(--color-surface)' }}>
            <button onClick={() => apiRef.current?.playPause()} disabled={!loaded} className="btn-primary" style={{ padding: '8px 20px' }}>
              {playing ? '일시정지' : '재생'}
            </button>
            <ExportMenu
              fileId={fileId}
              gp5Buffer={gp5Buffer}
              onPrint={() => apiRef.current?.print()}
            />
            <span style={{ fontSize: 12, color: 'var(--color-muted)', marginLeft: 8 }}>
              {saveStatus === 'saving' ? '저장 중…'
                : saveStatus === 'saved' ? '저장됨'
                : saveStatus === 'error' ? '저장 실패'
                : ''}
            </span>
          </div>
        )}
        <div ref={containerRef} style={{ width: '100%', flex: 1 }} />
      </div>

      {/* 우측 패널: StructurePanel + EditPanel */}
      {gp5Buffer && (
        <div style={{ width: 280, background: 'var(--color-surface)', borderLeft: '1px solid var(--color-border)', overflowY: 'auto', flexShrink: 0 }}>
          <StructurePanel />
          <hr style={{ margin: '4px 0', border: 'none', borderTop: '1px solid var(--color-border)' }} />
          <EditPanel
            selectedPosition={selected}
            currentBeat={currentBeat}
            currentNote={currentNote}
            onEditBeat={commitEdit}
            onEditNote={commitEdit}
          />
        </div>
      )}
    </div>
  )
}
