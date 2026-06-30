import type { ScoreSnapshot, SnapshotBeat, SnapshotNote, Dynamic, Effect } from './scoreTypes'

const DYNAMIC_VALUES: Record<number, Dynamic> = {
  0: 'ppp', 1: 'pp', 2: 'p', 3: 'mp', 4: 'mf', 5: 'f', 6: 'ff', 7: 'fff',
}

// alphaTab SlideOutType 숫자값 → Effect 문자열
const SLIDE_OUT_TYPE_MAP: Record<number, Effect> = {
  1: 'slide-shift',    // SlideOutType.Shift
  2: 'slide-legato',   // SlideOutType.Legato
  4: 'slide-out-below', // SlideOutType.OutDown
}
// alphaTab SlideInType 숫자값 → Effect 문자열
const SLIDE_IN_TYPE_MAP: Record<number, Effect> = {
  2: 'slide-in-above', // SlideInType.IntoFromAbove
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
export function serializeScore(score: any): ScoreSnapshot {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tracks = score.tracks.map((track: any) => {
    const staff = track.staves[0]
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const measures = staff.bars.map((bar: any) => {
      const mb = bar.masterBar
      const voice = bar.voices[0]

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const beats: SnapshotBeat[] = (voice.beats as any[])
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .filter((b: any) => b.duration != null)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .map((beat: any): SnapshotBeat => {
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
            dynamic: DYNAMIC_VALUES[beat.dynamics as number] ?? 'mf',
            strumDown: pickStroke === 2 ? true : pickStroke === 1 ? false : undefined,
          }
        })

      return {
        timeSignature: {
          num: mb.timeSignatureNumerator as number,
          den: mb.timeSignatureDenominator as number,
        },
        beats,
      }
    })

    return { measures }
  })

  return { tracks }
}
