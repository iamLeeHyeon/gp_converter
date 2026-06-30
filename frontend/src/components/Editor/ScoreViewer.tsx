import { useEffect, useRef, useState, useCallback } from 'react'
import { initAlphaTab } from '../../lib/alphatab'
import type * as alphaTab from '@coderline/alphatab'
import { useEditorStore } from '../../store/editorStore'
import { serializeScore } from '../../lib/scoreSerializer'
import { applyEdit, applySnapshot, type EditPayload } from '../../lib/scoreApplier'
import { useSyncFile } from '../../lib/useSyncFile'
import EditPanel from './EditPanel'
import ExportMenu from './ExportMenu'
import StructurePanel from './StructurePanel'
import TrackPanel from './TrackPanel'
import type { NotePosition, Dynamic, Effect } from '../../lib/scoreTypes'

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

  // 현재 선택된 beat/note 정보 추출
  const currentBeat = (() => {
    if (!selected || !apiRef.current?.score) return null
    const api = apiRef.current
    try {
      const beat = (api.score as any).tracks[selected.trackIndex]
        ?.staves[0]?.bars[selected.measureIndex]
        ?.voices[selected.voiceIndex]?.beats[selected.beatIndex]
      if (!beat) return null
      const DYNAMIC_VALUES: Record<number, Dynamic> = { 0:'ppp',1:'pp',2:'p',3:'mp',4:'mf',5:'f',6:'ff',7:'fff' }
      return {
        duration: beat.duration.value,
        dotted: beat.duration.isDotted,
        status: beat.isRest ? 'rest' : 'normal',
        dynamic: DYNAMIC_VALUES[beat.dynamics] ?? 'mf',
        strumDown: beat.pickStroke === 2 ? true : beat.pickStroke === 1 ? false : undefined,
      }
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
      const EFFECT_MAP: Record<number, Effect> = { 1:'slide-shift',2:'slide-legato',4:'slide-in-above',8:'slide-out-below' }
      let effect: Effect | undefined
      if (note.hammerOrPull) effect = 'hammer-on'
      else if (note.isMuted) effect = 'mute'
      else if (note.isGhost) effect = 'ghost'
      else if (note.harmonicType > 0) effect = 'harmonic'
      else if (note.slideType > 0) effect = EFFECT_MAP[note.slideType]
      return { string: note.string, fret: note.fret, effect }
    } catch { return null }
  })()

  const commitEdit = useCallback((edit: EditPayload) => {
    if (!apiRef.current?.score || !selected) return
    applyEdit(apiRef.current.score, selected, edit)
    const snap = serializeScore(apiRef.current.score)
    pushSnapshot(snap)
    apiRef.current.render()
  }, [selected, pushSnapshot])

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
        if (prev && apiRef.current?.score) {
          applySnapshot(apiRef.current.score, prev)
          apiRef.current.render()
        }
      } else if (mod && (e.shiftKey && e.key === 'z' || e.key === 'y')) {
        e.preventDefault()
        const next = redo()
        if (next && apiRef.current?.score) {
          applySnapshot(apiRef.current.score, next)
          apiRef.current.render()
        }
      } else if (e.key === 'Delete' && selected) {
        commitEdit({ type: 'deleteNote' })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [undo, redo, selected, commitEdit])

  // 구조 편집 후 store gp5Buffer 변경 시 alphaTab 리로드
  useEffect(() => {
    if (!storeGp5Buffer || !apiRef.current) return
    apiRef.current.load(storeGp5Buffer)
  }, [storeGp5Buffer])

  if (!gp5Buffer) {
    return (
      <div style={{ padding: 32, textAlign: 'center', color: '#666' }}>
        악보를 불러오세요 — PDF를 업로드하거나 파일 목록에서 선택하세요
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100%' }}>
      {/* 좌측 탭 패널: 파일 | 트랙 */}
      <aside style={{ width: 200, borderRight: '1px solid #ddd', overflow: 'auto', flexShrink: 0 }}>
        <div style={{ display: 'flex', borderBottom: '1px solid #ddd' }}>
          <button
            style={{ flex: 1, fontWeight: leftTab === 'files' ? 'bold' : undefined }}
            onClick={() => setLeftTab('files')}
          >파일</button>
          <button
            style={{ flex: 1, fontWeight: leftTab === 'tracks' ? 'bold' : undefined }}
            onClick={() => setLeftTab('tracks')}
          >트랙</button>
        </div>
        {leftTab === 'files'
          ? <div style={{ padding: 8, fontSize: 12, color: '#666' }}>파일 목록은 왼쪽 사이드바를 이용하세요</div>
          : <TrackPanel />
        }
      </aside>

      {/* 악보 영역 */}
      <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '8px 0', display: 'flex', gap: 8, alignItems: 'center' }}>
          <button onClick={() => apiRef.current?.playPause()} disabled={!loaded}>
            {playing ? '일시정지' : '재생'}
          </button>
          <ExportMenu
            fileId={fileId}
            onPrint={() => apiRef.current?.print()}
          />
          <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>
            {saveStatus === 'saving' ? '저장 중…'
              : saveStatus === 'saved' ? '저장됨'
              : saveStatus === 'error' ? '저장 실패'
              : ''}
          </span>
        </div>
        <div ref={containerRef} style={{ width: '100%', flex: 1 }} />
      </div>

      {/* 우측 패널: StructurePanel + EditPanel */}
      <div style={{ width: 280, borderLeft: '1px solid #ddd', overflowY: 'auto', flexShrink: 0 }}>
        <StructurePanel />
        <hr style={{ margin: '4px 0' }} />
        <EditPanel
          selectedPosition={selected}
          currentBeat={currentBeat}
          currentNote={currentNote}
          onEditBeat={commitEdit}
          onEditNote={commitEdit}
        />
      </div>
    </div>
  )
}
