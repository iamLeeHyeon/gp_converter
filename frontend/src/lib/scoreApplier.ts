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

// alphaTab SlideType 숫자값 (Effect → 숫자)
const EFFECT_SLIDE_MAP: Partial<Record<Effect, number>> = {
  'slide-shift': 1,
  'slide-legato': 2,
  'slide-in-above': 4,
  'slide-out-below': 8,
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
  note.hammerOrPull = false
  note.isGhost = false
  note.isMuted = false
  note.harmonicType = 0
  note.slideType = 0
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
    beat.notes.push({ string: 1, fret: 0, hammerOrPull: false, isGhost: false, isMuted: false, slideType: 0, harmonicType: 0 })
    beat.isRest = false
  } else if (edit.type === 'deleteNote' && pos.noteIndex !== null) {
    beat.notes.splice(pos.noteIndex, 1)
    if (beat.notes.length === 0) beat.isRest = true
  } else if (edit.type === 'fret' && pos.noteIndex !== null) {
    beat.notes[pos.noteIndex].fret = edit.value
  } else if (edit.type === 'effect') {
    if (pos.noteIndex === null) return
    const note = beat.notes[pos.noteIndex]
    clearNoteEffects(note)
    if (edit.value === null) return
    if (edit.value === 'hammer-on' || edit.value === 'pull-off') {
      note.hammerOrPull = true
    } else if (edit.value === 'ghost') {
      note.isGhost = true
    } else if (edit.value === 'mute') {
      note.isMuted = true
    } else if (edit.value === 'harmonic') {
      note.harmonicType = 1
    } else if (EFFECT_SLIDE_MAP[edit.value] !== undefined) {
      note.slideType = EFFECT_SLIDE_MAP[edit.value]!
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
        beat.isRest = bsnap.status === 'rest'
        beat.dynamics = DYNAMIC_INDICES[bsnap.dynamic ?? 'mf'] ?? 4
        beat.pickStroke = bsnap.strumDown === true ? 2 : bsnap.strumDown === false ? 1 : 0
        beat.notes = bsnap.notes.map((nsnap: { string: number; fret: number; effect?: Effect }) => {
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const note: any = { string: nsnap.string, fret: nsnap.fret, hammerOrPull: false, isGhost: false, isMuted: false, slideType: 0, harmonicType: 0 }
          if (nsnap.effect === 'hammer-on' || nsnap.effect === 'pull-off') note.hammerOrPull = true
          else if (nsnap.effect === 'ghost') note.isGhost = true
          else if (nsnap.effect === 'mute') note.isMuted = true
          else if (nsnap.effect === 'harmonic') note.harmonicType = 1
          else if (nsnap.effect && EFFECT_SLIDE_MAP[nsnap.effect]) note.slideType = EFFECT_SLIDE_MAP[nsnap.effect]!
          return note
        })
      })
    })
  })
}
