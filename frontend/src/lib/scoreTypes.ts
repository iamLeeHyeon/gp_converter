export type Effect =
  | 'hammer-on'
  | 'slide-shift' | 'slide-legato'
  | 'slide-in-above' | 'slide-out-below'
  | 'mute' | 'ghost' | 'harmonic'

export type Dynamic = 'ppp' | 'pp' | 'p' | 'mp' | 'mf' | 'f' | 'ff' | 'fff'

export interface SnapshotNote {
  string: number      // 1-6, GP 컨벤션 (1=high E)
  fret: number        // 0-24
  effect?: Effect
}

export interface SnapshotBeat {
  duration: 1 | 2 | 4 | 8 | 16 | 32
  dotted: boolean
  status: 'normal' | 'rest'
  notes: SnapshotNote[]
  strumDown?: boolean
  dynamic?: Dynamic
}

export interface SnapshotMeasure {
  timeSignature: { num: number; den: number }
  keySignature?: number      // -7(플랫7)~7(샾7), 0=C장조; 0이면 생략
  sectionMarker?: string     // 섹션 이름
  voices: SnapshotBeat[][]   // voices[0]=Voice1, voices[1]=Voice2
  beats?: SnapshotBeat[]     // voices[0] alias (하위 호환)
}

export interface SnapshotTrack {
  name?: string
  capo?: number              // 0-12; 0이면 생략 (GP5 생성 시 미반영, 메타데이터용)
  tuning?: number[]          // 개방현 MIDI 값 6개 [string1..string6]
  measures: SnapshotMeasure[]
}

export interface ScoreSnapshot {
  tracks: SnapshotTrack[]
}

export interface NotePosition {
  trackIndex: number
  measureIndex: number    // 0-based bar index
  voiceIndex: number      // 0 or 1
  beatIndex: number       // 0-based beat index within voice
  noteIndex: number | null // null = beat selected (no specific note)
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
