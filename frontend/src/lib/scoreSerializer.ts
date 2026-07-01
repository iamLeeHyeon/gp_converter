import type { ScoreSnapshot, SnapshotTrack, SnapshotMeasure, SnapshotBeat, SnapshotNote, Dynamic, Effect } from './scoreTypes'

const DYNAMIC_VALUES: Record<number, Dynamic> = {
  0: 'ppp', 1: 'pp', 2: 'p', 3: 'mp', 4: 'mf', 5: 'f', 6: 'ff', 7: 'fff',
}

const SLIDE_OUT_TYPE_MAP: Record<number, Effect> = {
  1: 'slide-shift',
  2: 'slide-legato',
  4: 'slide-out-below',
}
const SLIDE_IN_TYPE_MAP: Record<number, Effect> = {
  2: 'slide-in-above',
}

function getNoteEffect(note: Record<string, unknown>): Effect | undefined {
  if (note.isHammerPullOrigin) return 'hammer-on'
  if (note.isDead) return 'mute'
  if (note.isGhost) return 'ghost'
  if ((note.harmonicType as number) > 0) return 'harmonic'
  const slideOutType = note.slideOutType as number
  if (slideOutType > 0 && SLIDE_OUT_TYPE_MAP[slideOutType]) return SLIDE_OUT_TYPE_MAP[slideOutType]
  const slideInType = note.slideInType as number
  if (slideInType > 0 && SLIDE_IN_TYPE_MAP[slideInType]) return SLIDE_IN_TYPE_MAP[slideInType]
  return undefined
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function serializeBeat(beat: any): SnapshotBeat {
  const pickStroke = beat.pickStroke as number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const notes: SnapshotNote[] = (beat.isRest ? [] : (beat.notes as any[])).map(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (note: any): SnapshotNote => ({
      string: note.string as number,
      fret: note.fret as number,
      effect: getNoteEffect(note),
    }),
  )
  return {
    duration: beat.duration.value as 1 | 2 | 4 | 8 | 16 | 32,
    dotted: beat.duration.isDotted as boolean,
    status: beat.isRest ? 'rest' : 'normal',
    notes,
    strumDown: pickStroke === 2 ? true : pickStroke === 1 ? false : undefined,
    dynamic: DYNAMIC_VALUES[(beat.dynamics as number) ?? 4] ?? 'mf',
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function serializeScore(score: any): ScoreSnapshot {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tracks: SnapshotTrack[] = score.tracks.map((track: any) => {
    const name = (track.name as string) || undefined
    const tuning = Array.isArray(track.tuning) ? (track.tuning as number[]) : undefined

    const staff = track.staves[0]
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const measures: SnapshotMeasure[] = staff.bars.map((bar: any) => {
      const mb = bar.masterBar
      const keySignatureVal = mb.keySignature as number
      const keySignature = keySignatureVal !== 0 ? keySignatureVal : undefined
      const sectionMarker = mb.section ? ((mb.section.text as string) || undefined) : undefined

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const voices: SnapshotBeat[][] = (bar.voices as any[]).map((voice: any) =>
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (voice.beats as any[])
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .filter((b: any) => b.duration != null)
          .map(serializeBeat),
      )

      return {
        timeSignature: {
          num: mb.timeSignature.numerator as number,
          den: mb.timeSignature.denominator.value as number,
        },
        keySignature,
        sectionMarker,
        voices,
        beats: voices[0],
      }
    })

    return { name, tuning, measures }
  })

  return { tracks }
}
