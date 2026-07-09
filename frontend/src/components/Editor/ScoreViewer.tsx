import { useEffect, useRef, useState, useCallback } from 'react'
import { initAlphaTab } from '../../lib/alphatab'
import type * as alphaTab from '@coderline/alphatab'
import { useEditorStore } from '../../store/editorStore'
import { serializeScore, serializeBeat, getNoteEffect } from '../../lib/scoreSerializer'
import { applyEdit, makeNote, type EditPayload } from '../../lib/scoreApplier'
import { collectPitchYSamples, estimatePitchFromY, findStringFretForPitch } from '../../lib/pitchPosition'
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
  const [selectionRect, setSelectionRect] = useState<{ x: number; y: number; w: number; h: number } | null>(null)

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
    // serializeScore 실패해도 실제 편집(applyEdit)은 이미 반영됐으니 render는 항상 실행한다
    // (예전엔 여기서 예외가 새어나가 render()까지 못 가서 편집 버튼이 안 먹는 것처럼 보였다)
    try {
      pushSnapshot(serializeScore(apiRef.current.score))
    } catch (e) {
      console.error('편집 스냅샷 생성 실패 — undo 히스토리에는 안 남지만 화면은 갱신됩니다', e)
    }
    apiRef.current.render()
  }, [selected, pushSnapshot])

  // undo/redo: 구조 편집(마디/트랙 추가삭제 등)은 alphaTab 인플레이스 반영 불가 → 백엔드 재동기화 후 리로드
  const syncAndReload = useCallback(async (snap: ScoreSnapshot) => {
    if (!fileId) return
    await syncFileAndReload(fileId, snap)
  }, [fileId])

  // 자동저장
  useSyncFile(fileId, present)

  // 선택된 음표머리 주위 점선 사각형 표시용 — alphaTab의 boundsLookup에서
  // 실제 렌더링된 위치를 읽어온다. includeNoteBounds(alphatab.ts)가 켜져
  // 있어야 notes 배열이 채워진다.
  const updateSelectionRectFromNote = useCallback((note: any) => {
    try {
      const lookup = (apiRef.current as any)?.renderer?.boundsLookup
      const beatBounds = lookup?.findBeat(note.beat)
      const noteBounds = beatBounds?.notes?.find((nb: any) => nb.note === note)
      if (noteBounds) {
        const b = noteBounds.noteHeadBounds
        setSelectionRect({ x: b.x, y: b.y, w: b.w, h: b.h })
        return
      }
    } catch { /* bounds 조회 실패 시 아래에서 선택 표시 제거 */ }
    setSelectionRect(null)
  }, [])

  // 음표 없는 박자(쉼표, 빈 자리)를 선택했을 때도 "선택됐다"는 시각 피드백이
  // 있어야 한다 — noteHeadBounds가 없으니 그 박자의 눈에 보이는 요소(쉼표
  // 기호 등) 전체를 감싸는 visualBounds를 대신 쓴다.
  const updateSelectionRectFromBeat = useCallback((beat: any) => {
    try {
      const lookup = (apiRef.current as any)?.renderer?.boundsLookup
      const beatBounds = lookup?.findBeat(beat)
      if (beatBounds?.visualBounds) {
        const b = beatBounds.visualBounds
        setSelectionRect({ x: b.x, y: b.y, w: b.w, h: b.h })
        return
      }
    } catch { /* bounds 조회 실패 시 아래에서 선택 표시 제거 */ }
    setSelectionRect(null)
  }, [])

  // alphaTab 초기화
  useEffect(() => {
    if (!containerRef.current) return
    const api = initAlphaTab(containerRef.current)
    apiRef.current = api

    api.scoreLoaded.on((score: any) => {
      setLoaded(true)
      // 최초 로드 시엔 present가 비어있어서(편집해야만 채워지던 문제) 트랙/구조
      // 패널이 항상 빈 화면으로 보였다 — 로드 직후 한 번만 채운다. present가
      // 이미 있으면(구조편집→재로드 케이스) 편집 액션이 이미 pushSnapshot을
      // 호출했으므로 여기서 또 넣으면 undo 히스토리가 중복된다.
      if (score && useEditorStore.getState().present === null) {
        // serializeScore는 실제 악보 데이터를 그대로 훑는 함수라 예외가 나면
        // 여기서 절대 삼키지 않고 위로 던지면 안 된다 — alphaTab의 scoreLoaded
        // 리스너 안에서 예외가 새면 그 뒤 실제 악보 렌더링 자체가 멈춰서
        // "변환은 됐는데 화면에 악보가 안 뜨는" 증상으로 이어진다(실사례로
        // 재현된 버그). present를 못 채우는 것보다 렌더링이 죽는 게 훨씬 나쁘다.
        try {
          pushSnapshot(serializeScore(score))
        } catch (e) {
          console.error('악보 초기 스냅샷 생성 실패 — 트랙/구조 패널이 비어있을 수 있음', e)
        }
      }
    })
    api.playerStateChanged.on((e: any) => setPlaying(e.state === 1))
    // 편집으로 인한 재렌더 후에도 선택 표시 위치를 다시 계산한다(레이아웃이
    // 바뀌어 음표 위치가 이동할 수 있으므로) — 선택이 없으면 표시를 지운다.
    api.postRenderFinished.on(() => {
      const sel = useEditorStore.getState().selected
      const score = apiRef.current?.score as any
      if (!sel || !score) { setSelectionRect(null); return }
      try {
        const beat = score.tracks[sel.trackIndex]?.staves[0]?.bars[sel.measureIndex]
          ?.voices[sel.voiceIndex]?.beats[sel.beatIndex]
        const note = sel.noteIndex !== null ? beat?.notes[sel.noteIndex] : null
        if (note) updateSelectionRectFromNote(note)
        else if (beat) updateSelectionRectFromBeat(beat)
        else setSelectionRect(null)
      } catch { setSelectionRect(null) }
    })
    // alphaTab의 기본 noteMouseDown은 noteHeadBounds 사각형에 정확히 들어와야만
    // 인식한다(패딩 없음, alphaTab 내부 고정 로직이라 설정으로 못 바꿈). 음표
    // 클릭이 너무 빡빡하다는 피드백이 있어 직접 컨테이너에 클릭 리스너를 달아
    // 노트헤드 주변을 살짝 넓힌 사각형으로도 히트되게 한다.
    const HIT_PAD = 6
    const handleMouseDown = (e: MouseEvent) => {
      const container = containerRef.current
      const lookup = (apiRef.current as any)?.renderer?.boundsLookup
      if (!container || !lookup) return
      const rect = container.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top

      const beat = lookup.getBeatAtPos(x, y)
      if (!beat) return
      let note = lookup.getNoteAtPos(beat, x, y)
      const beatBounds = lookup.findBeat(beat)
      if (!note) {
        const hit = beatBounds?.notes?.find((nb: any) => {
          const b = nb.noteHeadBounds
          return x >= b.x - HIT_PAD && x <= b.x + b.w + HIT_PAD
            && y >= b.y - HIT_PAD && y <= b.y + b.h + HIT_PAD
        })
        note = hit?.note ?? null
      }

      if (note) {
        const pos: NotePosition = {
          trackIndex: 0,
          measureIndex: note.beat.voice.bar.index as number,
          voiceIndex: note.beat.voice.index as number,
          beatIndex: note.beat.index as number,
          noteIndex: note.index as number,
        }
        setSelected(pos)
        updateSelectionRectFromNote(note)
        return
      }

      // 음표가 없는 빈 자리(쉼표, 마디 여백) 클릭 — 같은 시스템에 이미 렌더링된
      // 노트들의 (실제 음높이, 노트머리 Y좌표)를 선형회귀해서 클릭 위치가 어떤
      // 음인지 추정하고, 그 음을 낼 수 있는 (줄, 프렛)이 비어있으면 바로 그
      // 자리에 새 음표를 만들어 선택한다. 추정에 실패하면(탭보 영역 클릭 등)
      // 박자 전체만 선택해서 사이드바의 "+ 화음 음 추가"로 대신하게 한다.
      try {
        const staff = (apiRef.current?.score as any)?.tracks[0]?.staves[0]
        const samples = collectPitchYSamples(beatBounds)
        const targetPitch = estimatePitchFromY(samples, y)
        const usedStrings = new Set((beat.notes as any[]).map((n) => n.string))
        const target = targetPitch === null ? null : findStringFretForPitch(staff, usedStrings, targetPitch)
        if (target) {
          beat.addNote(makeNote(target.string, target.fret))
          const newNote = beat.notes[beat.notes.length - 1]
          const pos: NotePosition = {
            trackIndex: 0,
            measureIndex: beat.voice.bar.index as number,
            voiceIndex: beat.voice.index as number,
            beatIndex: beat.index as number,
            noteIndex: newNote.index as number,
          }
          setSelected(pos)
          try {
            pushSnapshot(serializeScore(apiRef.current!.score))
          } catch (e) {
            console.error('편집 스냅샷 생성 실패 — undo 히스토리에는 안 남지만 화면은 갱신됩니다', e)
          }
          apiRef.current!.render()
          updateSelectionRectFromNote(newNote)
          return
        }
      } catch { /* 추정 실패 시 아래에서 박자 전체 선택으로 폴백 */ }

      const pos: NotePosition = {
        trackIndex: 0,
        measureIndex: beat.voice.bar.index as number,
        voiceIndex: beat.voice.index as number,
        beatIndex: beat.index as number,
        noteIndex: null,
      }
      setSelected(pos)
      updateSelectionRectFromBeat(beat)
    }
    containerRef.current.addEventListener('mousedown', handleMouseDown)

    return () => {
      containerRef.current?.removeEventListener('mousedown', handleMouseDown)
      api.destroy()
      apiRef.current = null
    }
  }, [setSelected, updateSelectionRectFromNote, updateSelectionRectFromBeat, pushSnapshot])

  // GP5 로드
  useEffect(() => {
    if (!apiRef.current || !gp5Buffer) return
    setLoaded(false)
    setSelected(null)
    setSelectionRect(null)
    apiRef.current.load(gp5Buffer)
  }, [gp5Buffer, setSelected])

  // 키보드 단축키
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // 입력창(프렛 숫자칸 등)에 포커스가 있을 땐 그쪽 기본 동작(네이티브 숫자
      // 스피너, 텍스트 편집)에 맡기고 전역 단축키는 건너뛴다
      const target = e.target as HTMLElement | null
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
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
      } else if ((e.key === 'ArrowUp' || e.key === 'ArrowDown') && selected && selected.noteIndex !== null) {
        // 프렛 입력창 없이 화면에서 바로 음을 위아래로 옮긴다 — fret이 높을수록
        // 음이 높고(오선 위쪽) 낮을수록 음이 낮으므로(오선 아래쪽) ↑=fret+1, ↓=fret-1
        e.preventDefault()
        const score = apiRef.current?.score as any
        const note = score?.tracks[selected.trackIndex]?.staves[0]?.bars[selected.measureIndex]
          ?.voices[selected.voiceIndex]?.beats[selected.beatIndex]?.notes[selected.noteIndex]
        if (!note) return
        const delta = e.key === 'ArrowUp' ? 1 : -1
        const next = Math.min(24, Math.max(0, (note.fret as number) + delta))
        commitEdit({ type: 'fret', value: next })
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
  return (
    <div style={{ display: 'flex', height: '100%', background: 'var(--color-bg)' }}>
      {/* 좌측 패널: 트랙 */}
      {gp5Buffer && (
        <aside style={{ width: 200, background: 'var(--color-surface)', borderRight: '1px solid var(--color-border)', overflow: 'auto', flexShrink: 0 }}>
          <TrackPanel />
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
            <button
              onClick={() => {
                const api = apiRef.current
                if (!api) return
                // stop()만 호출하면 재생 범위가 선택돼 있을 때 그 범위의 시작으로만
                // 돌아간다 — 완전히 처음부터 재생하려면 범위 선택도 같이 지운다.
                api.playbackRange = null
                api.tickPosition = 0
                api.play()
              }}
              disabled={!loaded}
              className="btn-ghost"
              style={{ padding: '8px 16px' }}
            >
              ⏮ 처음부터
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
        <div style={{ position: 'relative', width: '100%', flex: 1 }}>
          <div ref={containerRef} style={{ width: '100%' }} />
          {selectionRect && (
            <div
              style={{
                position: 'absolute',
                left: selectionRect.x - 6,
                top: selectionRect.y - 4,
                width: selectionRect.w + 12,
                height: selectionRect.h + 8,
                border: '2px dashed var(--color-primary)',
                borderRadius: 6,
                pointerEvents: 'none',
              }}
            />
          )}
        </div>
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
