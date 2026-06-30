import { create } from 'zustand'
import type { ScoreSnapshot, NotePosition, SaveStatus } from '../lib/scoreTypes'

const MAX_HISTORY = 100

interface EditorState {
  selected: NotePosition | null
  fileId: string | null
  past: ScoreSnapshot[]
  present: ScoreSnapshot | null
  future: ScoreSnapshot[]
  saveStatus: SaveStatus
  // v2 추가
  selectedTrackIndex: number
  selectedMeasureIndex: number
  activeVoice: 0 | 1
  gp5Buffer: ArrayBuffer | null

  setSelected: (pos: NotePosition | null) => void
  setFileId: (id: string | null) => void
  setSaveStatus: (status: SaveStatus) => void
  pushSnapshot: (snap: ScoreSnapshot) => void
  undo: () => ScoreSnapshot | null
  redo: () => ScoreSnapshot | null
  clearHistory: () => void
  // v2 추가 액션
  setGp5Buffer: (buf: ArrayBuffer | null) => void
}

export const useEditorStore = create<EditorState>((set, get) => ({
  selected: null,
  fileId: null,
  past: [],
  present: null,
  future: [],
  saveStatus: 'idle',
  // v2 추가
  selectedTrackIndex: 0,
  selectedMeasureIndex: 0,
  activeVoice: 0 as 0 | 1,
  gp5Buffer: null,

  setSelected: (pos) => set({ selected: pos }),
  setFileId: (id) => set({ fileId: id }),
  setSaveStatus: (status) => set({ saveStatus: status }),

  pushSnapshot: (snap) =>
    set((s) => {
      const past = s.present
        ? [...s.past.slice(-(MAX_HISTORY - 1)), s.present]
        : s.past
      return { past, present: snap, future: [] }
    }),

  undo: () => {
    const { past, present, future } = get()
    if (past.length === 0 || present === null) return null
    const prev = past[past.length - 1]
    set({
      past: past.slice(0, -1),
      present: prev,
      future: [present, ...future],
    })
    return prev
  },

  redo: () => {
    const { past, present, future } = get()
    if (future.length === 0 || present === null) return null
    const next = future[0]
    set({
      past: [...past, present],
      present: next,
      future: future.slice(1),
    })
    return next
  },

  clearHistory: () =>
    set({ past: [], present: null, future: [], selected: null, saveStatus: 'idle' }),

  setGp5Buffer: (buf) => set({ gp5Buffer: buf }),
}))
