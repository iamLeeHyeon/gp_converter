import { describe, it, expect } from 'vitest'
import { applyStructuralEdit } from '../lib/structuralEdit'
import type { ScoreSnapshot } from '../lib/scoreTypes'

const REST_BEAT = { duration: 4 as const, dotted: false, status: 'rest' as const, notes: [] }

function makeSnap(measureCount = 2, trackCount = 1): ScoreSnapshot {
  const makeMeasure = (i: number) => ({
    timeSignature: { num: 4, den: 4 },
    voices: [[{ ...REST_BEAT }]],
    beats: [{ ...REST_BEAT }],
  })
  const makeTrack = () => ({
    name: 'Guitar',
    measures: Array.from({ length: measureCount }, (_, i) => makeMeasure(i)),
  })
  return { tracks: Array.from({ length: trackCount }, makeTrack) }
}

describe('applyStructuralEdit', () => {
  describe('addMeasure', () => {
    it('선택 마디 다음에 마디 삽입', () => {
      const snap = makeSnap(2)
      const result = applyStructuralEdit(snap, { type: 'addMeasure', afterIndex: 0 })
      expect(result.tracks[0].measures).toHaveLength(3)
    })

    it('추가된 마디는 이전 마디의 박자표 상속', () => {
      const snap = makeSnap(1)
      snap.tracks[0].measures[0].timeSignature = { num: 3, den: 4 }
      const result = applyStructuralEdit(snap, { type: 'addMeasure', afterIndex: 0 })
      expect(result.tracks[0].measures[1].timeSignature).toEqual({ num: 3, den: 4 })
    })

    it('다중 트랙에 동시 마디 추가', () => {
      const snap = makeSnap(2, 2)
      const result = applyStructuralEdit(snap, { type: 'addMeasure', afterIndex: 0 })
      expect(result.tracks[0].measures).toHaveLength(3)
      expect(result.tracks[1].measures).toHaveLength(3)
    })
  })

  describe('deleteMeasure', () => {
    it('선택 마디 삭제', () => {
      const snap = makeSnap(3)
      const result = applyStructuralEdit(snap, { type: 'deleteMeasure', index: 1 })
      expect(result.tracks[0].measures).toHaveLength(2)
    })

    it('마디 1개 남으면 삭제 불가', () => {
      const snap = makeSnap(1)
      const result = applyStructuralEdit(snap, { type: 'deleteMeasure', index: 0 })
      expect(result.tracks[0].measures).toHaveLength(1)
    })
  })

  describe('moveMeasure', () => {
    it('마디 위로 이동', () => {
      const snap = makeSnap(3)
      snap.tracks[0].measures[0].sectionMarker = 'A'
      snap.tracks[0].measures[1].sectionMarker = 'B'
      snap.tracks[0].measures[2].sectionMarker = 'C'
      const result = applyStructuralEdit(snap, { type: 'moveMeasure', from: 2, to: 0 })
      expect(result.tracks[0].measures.map(m => m.sectionMarker)).toEqual(['C', 'A', 'B'])
    })
  })

  describe('setTimeSignature', () => {
    it('마디 박자표 변경', () => {
      const snap = makeSnap(2)
      const result = applyStructuralEdit(snap, { type: 'setTimeSignature', measureIndex: 1, num: 3, den: 4 })
      expect(result.tracks[0].measures[1].timeSignature).toEqual({ num: 3, den: 4 })
      expect(result.tracks[0].measures[0].timeSignature).toEqual({ num: 4, den: 4 })
    })
  })

  describe('setKeySignature', () => {
    it('마디 조표 변경', () => {
      const snap = makeSnap(1)
      const result = applyStructuralEdit(snap, { type: 'setKeySignature', measureIndex: 0, key: 2 })
      expect(result.tracks[0].measures[0].keySignature).toBe(2)
    })
  })

  describe('setSectionMarker', () => {
    it('섹션 마커 설정', () => {
      const snap = makeSnap(1)
      const result = applyStructuralEdit(snap, { type: 'setSectionMarker', measureIndex: 0, name: 'Chorus' })
      expect(result.tracks[0].measures[0].sectionMarker).toBe('Chorus')
    })

    it('null로 섹션 마커 제거', () => {
      const snap = makeSnap(1)
      snap.tracks[0].measures[0].sectionMarker = 'Intro'
      const result = applyStructuralEdit(snap, { type: 'setSectionMarker', measureIndex: 0, name: null })
      expect(result.tracks[0].measures[0].sectionMarker).toBeUndefined()
    })
  })

  describe('addTrack', () => {
    it('트랙 추가', () => {
      const snap = makeSnap(2)
      const result = applyStructuralEdit(snap, { type: 'addTrack' })
      expect(result.tracks).toHaveLength(2)
      expect(result.tracks[1].measures).toHaveLength(2)
    })

    it('추가 트랙은 Standard E 튜닝 기본값', () => {
      const snap = makeSnap(1)
      const result = applyStructuralEdit(snap, { type: 'addTrack' })
      expect(result.tracks[1].tuning).toEqual([64, 59, 55, 50, 45, 40])
    })
  })

  describe('deleteTrack', () => {
    it('트랙 삭제', () => {
      const snap = makeSnap(1, 2)
      const result = applyStructuralEdit(snap, { type: 'deleteTrack', trackIndex: 1 })
      expect(result.tracks).toHaveLength(1)
    })

    it('트랙 1개 남으면 삭제 불가', () => {
      const snap = makeSnap(1, 1)
      const result = applyStructuralEdit(snap, { type: 'deleteTrack', trackIndex: 0 })
      expect(result.tracks).toHaveLength(1)
    })
  })

  describe('setTrackName', () => {
    it('트랙 이름 변경', () => {
      const snap = makeSnap(1)
      const result = applyStructuralEdit(snap, { type: 'setTrackName', trackIndex: 0, name: 'Bass' })
      expect(result.tracks[0].name).toBe('Bass')
    })
  })

  describe('setTuning', () => {
    it('튜닝 변경', () => {
      const snap = makeSnap(1)
      const dropD = [64, 59, 55, 50, 45, 38]
      const result = applyStructuralEdit(snap, { type: 'setTuning', trackIndex: 0, tuning: dropD })
      expect(result.tracks[0].tuning).toEqual(dropD)
    })
  })

  describe('setCapo', () => {
    it('카포 설정', () => {
      const snap = makeSnap(1)
      const result = applyStructuralEdit(snap, { type: 'setCapo', trackIndex: 0, capo: 3 })
      expect(result.tracks[0].capo).toBe(3)
    })

    it('카포 0-12 범위 클램프', () => {
      const snap = makeSnap(1)
      expect(applyStructuralEdit(snap, { type: 'setCapo', trackIndex: 0, capo: 15 }).tracks[0].capo).toBe(12)
      expect(applyStructuralEdit(snap, { type: 'setCapo', trackIndex: 0, capo: -1 }).tracks[0].capo).toBe(0)
    })
  })

  it('원본 snapshot 불변', () => {
    const snap = makeSnap(2)
    const result = applyStructuralEdit(snap, { type: 'addMeasure', afterIndex: 0 })
    expect(snap.tracks[0].measures).toHaveLength(2)  // 원본 그대로
    expect(result.tracks[0].measures).toHaveLength(3)  // 새 객체
  })
})
