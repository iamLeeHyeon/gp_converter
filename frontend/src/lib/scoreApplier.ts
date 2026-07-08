import { model } from '@coderline/alphatab'
import type { NotePosition, Effect, Dynamic } from './scoreTypes'

export type EditPayload =
  | { type: 'fret'; value: number }
  | { type: 'duration'; value: 1 | 2 | 4 | 8 | 16 | 32 }
  | { type: 'dotted'; value: boolean }
  | { type: 'effect'; value: Effect | null }
  | { type: 'strumDown'; value: boolean | undefined }
  | { type: 'dynamic'; value: Dynamic }
  | { type: 'addNote' }
  | { type: 'deleteNote' }

const DYNAMIC_INDICES: Record<Dynamic, number> = {
  ppp: 0, pp: 1, p: 2, mp: 3, mf: 4, f: 5, ff: 6, fff: 7,
}

// alphaTab SlideOutType / SlideInType 숫자값 (Effect → {in, out})
const EFFECT_SLIDE_MAP: Partial<Record<Effect, { slideInType?: number; slideOutType?: number }>> = {
  'slide-shift':    { slideOutType: 1 },   // SlideOutType.Shift
  'slide-legato':   { slideOutType: 2 },   // SlideOutType.Legato
  'slide-in-above': { slideInType: 2 },    // SlideInType.IntoFromAbove
  'slide-out-below': { slideOutType: 4 },  // SlideOutType.OutDown
}

// 새 노트는 반드시 실제 alphaTab Note 클래스를 인스턴스화해서 만들어야 한다.
// {string, fret, ...} 같은 순수 객체 리터럴로 만들면 생성자에서 자동 할당되는
// note.id(Note.globalNoteId++)가 없어서 여러 새 노트가 전부 id=undefined로
// 겹치고, 렌더러의 _noteGlyphLookup(Map, key=note.id)에서 서로 덮어써
// "Cannot read properties of null (reading 'glyph')" 예외가 나던 버그가 있었다
// (화음 노트를 여러 개 추가했을 때 실사용 중 재현됨).
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function makeNote(string: number, fret: number): any {
  const note = new model.Note()
  note.string = string
  note.fret = fret
  return note
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function getBeat(score: any, pos: NotePosition) {
  return score.tracks[pos.trackIndex]
    .staves[0]
    .bars[pos.measureIndex]
    .voices[pos.voiceIndex]
    .beats[pos.beatIndex]
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function clearNoteEffects(note: any) {
  note.isHammerPullOrigin = false
  note.isGhost = false
  note.isDead = false
  note.harmonicType = 0
  note.slideInType = 0
  note.slideOutType = 0
}

// alphaTab은 GP 파일을 파싱할 때 각 Note.finish()에서 hammerPullDestination/
// slideTarget/hasEffectSlur 같은 파생 필드를 딱 한 번 계산해둔다. 편집으로
// isHammerPullOrigin이나 slideOutType(legato)을 나중에 켜면 이 파생 필드가
// 안 채워져서 플래그는 true인데 슬러(곡선)가 화면에 전혀 안 그려지는 문제가
// 있었다 — finish()의 관련 로직을 그대로 재현해 다시 계산한다.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function recomputeDerivedEffects(note: any) {
  if (note.hammerPullDestination) note.hammerPullDestination.hammerPullOrigin = null
  if (note.slideTarget) note.slideTarget.slideOrigin = null
  note.hammerPullDestination = null
  note.slideTarget = null
  note.hasEffectSlur = false
  note.effectSlurDestination = null

  if (note.isHammerPullOrigin) {
    // note.beat.nextBeat 등 score 그래프가 온전히 연결돼 있어야 하는 탐색이라
    // 예외가 나면 목적지를 확정할 수 없는 것과 같게 취급한다(안전하게 false)
    let dest = null
    try { dest = model.Note.findHammerPullDestination(note) } catch { /* 아래에서 처리 */ }
    if (!dest) {
      note.isHammerPullOrigin = false
    } else {
      note.hammerPullDestination = dest
      dest.hammerPullOrigin = note
      note.hasEffectSlur = true
      note.effectSlurDestination = dest
    }
  }
  if (note.slideOutType === 1 || note.slideOutType === 2) { // Shift | Legato
    let dest = null
    try { dest = model.Note.nextNoteOnSameLine(note) } catch { /* 아래에서 처리 */ }
    if (!dest) {
      note.slideOutType = 0
    } else {
      note.slideTarget = dest
      dest.slideOrigin = note
      if (note.slideOutType === 2 && !note.hasEffectSlur) {
        note.hasEffectSlur = true
        note.effectSlurDestination = dest
      }
    }
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function applyEdit(score: any, pos: NotePosition, edit: EditPayload): void {
  const beat = getBeat(score, pos)

  if (edit.type === 'duration') {
    // beat.duration은 Duration enum 값 자체(Quarter=4 등) — 객체가 아니다
    beat.duration = edit.value
  } else if (edit.type === 'dotted') {
    // 점음표 개수는 beat.dots(0=없음, 1=점음표 하나)로 관리된다
    beat.dots = edit.value ? 1 : 0
  } else if (edit.type === 'dynamic') {
    beat.dynamics = DYNAMIC_INDICES[edit.value]
  } else if (edit.type === 'strumDown') {
    beat.pickStroke = edit.value === true ? 2 : edit.value === false ? 1 : 0
  } else if (edit.type === 'addNote') {
    // 화음: 항상 string 1에만 추가하면 이미 그 줄에 노트가 있을 때 겹쳐버린다.
    // 아직 안 쓰인 줄 중 가장 낮은 번호(1=제일 아래 줄)를 골라 추가한다.
    const stringCount = (score.tracks[pos.trackIndex].staves[0]?.tuning?.length as number) ?? 6
    const usedStrings = new Set(beat.notes.map((n: any) => n.string))
    let newString = 1
    for (let s = 1; s <= stringCount; s++) {
      if (!usedStrings.has(s)) { newString = s; break }
    }
    // beat.notes.push(...)로 직접 밀어넣으면 alphaTab이 렌더링/재생 시 필요로
    // 하는 note.beat/note.index/noteStringLookup 백링크가 안 채워져 렌더러가
    // "Cannot read properties of undefined (reading 'voice')" 예외를 던진다
    // (실사용 중 재현된 버그) — 공개 메서드 Beat.addNote로 위임한다.
    beat.addNote(makeNote(newString, 0))
  } else if (edit.type === 'deleteNote' && pos.noteIndex !== null) {
    beat.removeNote(beat.notes[pos.noteIndex])
  } else if (edit.type === 'fret' && pos.noteIndex !== null) {
    beat.notes[pos.noteIndex].fret = edit.value
  } else if (edit.type === 'effect') {
    if (pos.noteIndex === null) return
    const note = beat.notes[pos.noteIndex]
    clearNoteEffects(note)
    if (edit.value === 'hammer-on') {
      note.isHammerPullOrigin = true
    } else if (edit.value === 'ghost') {
      note.isGhost = true
    } else if (edit.value === 'mute') {
      note.isDead = true
    } else if (edit.value === 'harmonic') {
      note.harmonicType = 1
    } else if (edit.value !== null && EFFECT_SLIDE_MAP[edit.value] !== undefined) {
      const slideVal = EFFECT_SLIDE_MAP[edit.value]!
      if (slideVal.slideInType !== undefined) note.slideInType = slideVal.slideInType
      if (slideVal.slideOutType !== undefined) note.slideOutType = slideVal.slideOutType
    }
    recomputeDerivedEffects(note)
  }
}
