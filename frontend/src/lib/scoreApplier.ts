import type { NotePosition, Effect, Dynamic, ScoreSnapshot } from './scoreTypes'

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

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function applyEdit(score: any, pos: NotePosition, edit: EditPayload): void {
  const beat = getBeat(score, pos)

  if (edit.type === 'duration') {
    beat.duration.value = edit.value
  } else if (edit.type === 'dotted') {
    beat.duration.isDotted = edit.value
  } else if (edit.type === 'dynamic') {
    beat.dynamics = DYNAMIC_INDICES[edit.value]
  } else if (edit.type === 'strumDown') {
    beat.pickStroke = edit.value === true ? 2 : edit.value === false ? 1 : 0
  } else if (edit.type === 'addNote') {
    beat.notes.push({ string: 1, fret: 0, isHammerPullOrigin: false, isGhost: false, isDead: false, slideInType: 0, slideOutType: 0, harmonicType: 0 })
  } else if (edit.type === 'deleteNote' && pos.noteIndex !== null) {
    beat.notes.splice(pos.noteIndex, 1)
    // beat.isRest는 getter 전용 — notes가 비면 alphaTab이 자동으로 true 반환
  } else if (edit.type === 'fret' && pos.noteIndex !== null) {
    beat.notes[pos.noteIndex].fret = edit.value
  } else if (edit.type === 'effect') {
    if (pos.noteIndex === null) return
    const note = beat.notes[pos.noteIndex]
    clearNoteEffects(note)
    if (edit.value === null) return
    if (edit.value === 'hammer-on' || edit.value === 'pull-off') {
      note.isHammerPullOrigin = true
    } else if (edit.value === 'ghost') {
      note.isGhost = true
    } else if (edit.value === 'mute') {
      note.isDead = true
    } else if (edit.value === 'harmonic') {
      note.harmonicType = 1
    } else if (EFFECT_SLIDE_MAP[edit.value] !== undefined) {
      const slideVal = EFFECT_SLIDE_MAP[edit.value]!
      if (slideVal.slideInType !== undefined) note.slideInType = slideVal.slideInType
      if (slideVal.slideOutType !== undefined) note.slideOutType = slideVal.slideOutType
    }
  }
}

// Undo/Redo: 스냅샷 전체를 Score에 반영
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function applySnapshot(score: any, snap: ScoreSnapshot): void {
  snap.tracks.forEach((tsnap, ti) => {
    const staff = score.tracks[ti]?.staves[0]
    if (!staff) return
    tsnap.measures.forEach((msnap, mi) => {
      const voice = staff.bars[mi]?.voices[0]
      if (!voice) return
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      voice.beats.forEach((beat: any, bi: number) => {
        const bsnap = msnap.beats[bi]
        if (!bsnap) return
        beat.duration.value = bsnap.duration
        beat.duration.isDotted = bsnap.dotted
        // beat.isRest는 getter 전용 — notes 배열로 alphaTab이 자동 결정
        beat.dynamics = DYNAMIC_INDICES[bsnap.dynamic ?? 'mf'] ?? 4
        beat.pickStroke = bsnap.strumDown === true ? 2 : bsnap.strumDown === false ? 1 : 0
        beat.notes = bsnap.notes.map((nsnap: { string: number; fret: number; effect?: Effect }) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const note: any = { string: nsnap.string, fret: nsnap.fret, isHammerPullOrigin: false, isGhost: false, isDead: false, slideInType: 0, slideOutType: 0, harmonicType: 0 }
          if (nsnap.effect === 'hammer-on' || nsnap.effect === 'pull-off') note.isHammerPullOrigin = true
          else if (nsnap.effect === 'ghost') note.isGhost = true
          else if (nsnap.effect === 'mute') note.isDead = true
          else if (nsnap.effect === 'harmonic') note.harmonicType = 1
          else if (nsnap.effect && EFFECT_SLIDE_MAP[nsnap.effect]) {
            const slideVal = EFFECT_SLIDE_MAP[nsnap.effect]!
            if (slideVal.slideInType !== undefined) note.slideInType = slideVal.slideInType
            if (slideVal.slideOutType !== undefined) note.slideOutType = slideVal.slideOutType
          }
          return note
        })
      })
    })
  })
}
