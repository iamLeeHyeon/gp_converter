import type { ScoreSnapshot, SnapshotTrack, SnapshotMeasure, SnapshotBeat } from './scoreTypes'

export type StructuralEdit =
  | { type: 'addMeasure'; afterIndex: number }
  | { type: 'deleteMeasure'; index: number }
  | { type: 'moveMeasure'; from: number; to: number }
  | { type: 'setTimeSignature'; measureIndex: number; num: number; den: number }
  | { type: 'setKeySignature'; measureIndex: number; key: number }
  | { type: 'setSectionMarker'; measureIndex: number; name: string | null }
  | { type: 'addTrack' }
  | { type: 'deleteTrack'; trackIndex: number }
  | { type: 'setTrackName'; trackIndex: number; name: string }
  | { type: 'setTuning'; trackIndex: number; tuning: number[] }
  | { type: 'setCapo'; trackIndex: number; capo: number }

const STANDARD_TUNING = [64, 59, 55, 50, 45, 40]

function emptyMeasure(ts: { num: number; den: number }): SnapshotMeasure {
  const rest: SnapshotBeat = { duration: 4, dotted: false, status: 'rest', notes: [] }
  return { timeSignature: { ...ts }, voices: [[{ ...rest }]], beats: [{ ...rest }] }
}

function emptyTrack(measureCount: number): SnapshotTrack {
  return {
    name: 'Guitar',
    capo: 0,
    tuning: [...STANDARD_TUNING],
    measures: Array.from({ length: measureCount }, () => emptyMeasure({ num: 4, den: 4 })),
  }
}

export function applyStructuralEdit(
  snapshot: ScoreSnapshot,
  edit: StructuralEdit,
): ScoreSnapshot {
  // 얕은 복사 — 수정된 트랙/마디만 새 객체
  const tracks = snapshot.tracks.map(t => ({ ...t, measures: [...t.measures] }))

  switch (edit.type) {
    case 'addMeasure': {
      const ref = tracks[0]?.measures[edit.afterIndex]
      const ts = ref?.timeSignature ?? { num: 4, den: 4 }
      tracks.forEach(t => t.measures.splice(edit.afterIndex + 1, 0, emptyMeasure(ts)))
      break
    }
    case 'deleteMeasure': {
      if ((tracks[0]?.measures.length ?? 0) <= 1) break
      tracks.forEach(t => t.measures.splice(edit.index, 1))
      break
    }
    case 'moveMeasure': {
      if (edit.from === edit.to) break
      tracks.forEach(t => {
        const [removed] = t.measures.splice(edit.from, 1)
        t.measures.splice(edit.to, 0, removed)
      })
      break
    }
    case 'setTimeSignature':
      tracks.forEach(t => {
        if (t.measures[edit.measureIndex])
          t.measures[edit.measureIndex] = {
            ...t.measures[edit.measureIndex],
            timeSignature: { num: edit.num, den: edit.den },
          }
      })
      break
    case 'setKeySignature':
      tracks.forEach(t => {
        if (t.measures[edit.measureIndex])
          t.measures[edit.measureIndex] = {
            ...t.measures[edit.measureIndex],
            keySignature: edit.key,
          }
      })
      break
    case 'setSectionMarker':
      tracks.forEach(t => {
        if (t.measures[edit.measureIndex])
          t.measures[edit.measureIndex] = {
            ...t.measures[edit.measureIndex],
            sectionMarker: edit.name ?? undefined,
          }
      })
      break
    case 'addTrack':
      tracks.push(emptyTrack(tracks[0]?.measures.length ?? 1))
      break
    case 'deleteTrack':
      if (tracks.length > 1) tracks.splice(edit.trackIndex, 1)
      break
    case 'setTrackName':
      if (tracks[edit.trackIndex])
        tracks[edit.trackIndex] = { ...tracks[edit.trackIndex], name: edit.name }
      break
    case 'setTuning':
      if (tracks[edit.trackIndex])
        tracks[edit.trackIndex] = { ...tracks[edit.trackIndex], tuning: [...edit.tuning] }
      break
    case 'setCapo':
      if (tracks[edit.trackIndex])
        tracks[edit.trackIndex] = {
          ...tracks[edit.trackIndex],
          capo: Math.max(0, Math.min(12, edit.capo)),
        }
      break
  }

  return { tracks }
}
