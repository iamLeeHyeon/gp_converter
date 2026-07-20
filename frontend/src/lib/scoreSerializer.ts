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

export function getNoteEffect(note: Record<string, unknown>): Effect | undefined {
  if (note.isHammerPullOrigin) return 'hammer-on'
  if (note.isDead) return 'mute'
  if (note.isGhost) return 'ghost'
  if ((note.harmonicType as number) > 0) return 'harmonic'
  const slideOutType = note.slideOutType as number
  if (slideOutType > 0 && SLIDE_OUT_TYPE_MAP[slideOutType]) return SLIDE_OUT_TYPE_MAP[slideOutType]
  const slideInType = note.slideInType as number
  if (slideInType > 0 && SLIDE_IN_TYPE_MAP[slideInType]) return SLIDE_IN_TYPE_MAP[slideInType]
  // trillValue(대상음 MIDI값)가 0보다 크면 트릴이 설정된 것 — alphaTab은
  // 트릴 없는 음표엔 이 값을 0으로 둔다.
  if ((note.trillValue as number) > 0) return 'trill'
  // VibratoType.None = 0
  if ((note.vibrato as number) > 0) return 'vibrato'
  return undefined
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function serializeBeat(beat: any): SnapshotBeat {
  const pickStroke = beat.pickStroke as number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const notes: SnapshotNote[] = (beat.isRest ? [] : (beat.notes as any[])).map(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (note: any): SnapshotNote => {
      const effect = getNoteEffect(note)
      const rhFinger = note.rightHandFinger as number
      return {
        string: note.string as number,
        fret: note.fret as number,
        effect,
        trillFret: effect === 'trill' ? (note.trillFret as number) : undefined,
        // Fingers.NoOrDead=-1, Unknown=-2 — 실제 지정된 손가락(0~4)만 남긴다.
        rightHandFinger: rhFinger >= 0 ? rhFinger : undefined,
      }
    },
  )
  return {
    // alphaTab의 Beat.duration은 객체가 아니라 Duration enum 값 자체(Quarter=4 등)이고,
    // 점음표 개수는 별도 필드 dots(0=없음)로 관리된다 (실사용 중 "Cannot create
    // property 'value' on number '4'" 예외로 재현된 버그 — duration.value처럼
    // 중첩 프로퍼티가 있다고 잘못 가정했었다).
    duration: beat.duration as 1 | 2 | 4 | 8 | 16 | 32,
    dotted: (beat.dots as number) > 0,
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
    // pitchPosition.ts가 이미 staff.capo를 읽어 피치 추정에 쓰고 있음 —
    // alphaTab에 실존하는 필드인데 직렬화에서만 빠져있어서, 카포 있는
    // 곡을 열면 항상 0으로 보이고 구조 편집 한 번만 해도 영구 소실됐다.
    const capoVal = staff.capo as number | undefined
    const capo = capoVal ? capoVal : undefined
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
        // alphaTab의 MasterBar는 timeSignature란 중첩 객체가 아니라
        // timeSignatureNumerator/timeSignatureDenominator 평평한 필드를 쓴다
        // (실사용 중 TypeError로 재현된 버그 — commitEdit 안에서 이 예외가
        // try/catch 없이 그대로 새어나가 render()까지 못 가서, 음표 수정
        // 버튼을 눌러도 화면이 하나도 안 바뀌던 원인이었다).
        timeSignature: {
          num: mb.timeSignatureNumerator as number,
          den: mb.timeSignatureDenominator as number,
        },
        keySignature,
        sectionMarker,
        voices,
        beats: voices[0],
      }
    })

    return { name, tuning, capo, measures }
  })

  return { tracks }
}
