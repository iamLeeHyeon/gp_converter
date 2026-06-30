export type Effect =
  | 'hammer-on' | 'pull-off'
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
  beats: SnapshotBeat[]
}

export interface ScoreSnapshot {
  tracks: Array<{ measures: SnapshotMeasure[] }>
}

export interface NotePosition {
  trackIndex: number
  measureIndex: number    // 0-based bar index
  voiceIndex: number      // usually 0
  beatIndex: number       // 0-based beat index within voice
  noteIndex: number | null // null = beat selected (no specific note)
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
