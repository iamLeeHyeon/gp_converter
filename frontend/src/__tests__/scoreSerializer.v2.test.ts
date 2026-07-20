import { describe, it, expect } from 'vitest'
import { serializeScore } from '../lib/scoreSerializer'

function mockBeat(isRest = false) {
  return {
    duration: 4, dots: 0,
    isRest,
    pickStroke: 0,
    notes: isRest ? [] : [{ string: 1, fret: 5, isHammerPullOrigin: false, isDead: false, isGhost: false, harmonicType: 0, slideOutType: 0, slideInType: 0 }],
    dynamics: 4,
  }
}

function mockScore(opts: {
  trackName?: string
  tuning?: number[]
  capo?: number
  keySignature?: number
  sectionMarker?: string
  voices?: any[][]
} = {}) {
  const voice0 = opts.voices?.[0] ?? [mockBeat()]
  const voice1 = opts.voices?.[1] ?? []
  return {
    tracks: [{
      name: opts.trackName ?? 'Guitar',
      tuning: opts.tuning ?? [64, 59, 55, 50, 45, 40],
      staves: [{
        capo: opts.capo ?? 0,
        bars: [{
          masterBar: {
            timeSignatureNumerator: 4,
            timeSignatureDenominator: 4,
            keySignature: opts.keySignature ?? 0,
            section: opts.sectionMarker ? { text: opts.sectionMarker } : null,
          },
          voices: [
            { beats: voice0 },
            { beats: voice1 },
          ],
        }],
      }],
    }],
  }
}

describe('serializeScore v2', () => {
  it('tracks에 name, tuning, capo 포함', () => {
    const score = mockScore({ trackName: 'Bass', tuning: [43, 38, 33, 28], capo: 2 })
    const snap = serializeScore(score)
    expect(snap.tracks[0].name).toBe('Bass')
    expect(snap.tracks[0].tuning).toEqual([43, 38, 33, 28])  // score.tuning 사용
    expect(snap.tracks[0].capo).toBe(2)  // staff.capo 사용 (pitchPosition.ts도 이미 읽는 실존 필드)
  })

  it('capo 없으면(0) 생략된다', () => {
    const score = mockScore({ capo: 0 })
    const snap = serializeScore(score)
    expect(snap.tracks[0].capo).toBeUndefined()
  })

  it('measures에 voices 배열 포함', () => {
    const score = mockScore()
    const snap = serializeScore(score)
    expect(Array.isArray(snap.tracks[0].measures[0].voices)).toBe(true)
    expect(snap.tracks[0].measures[0].voices.length).toBeGreaterThanOrEqual(1)
  })

  it('beats는 voices[0]과 동일 (하위 호환)', () => {
    const score = mockScore()
    const snap = serializeScore(score)
    const m = snap.tracks[0].measures[0]
    expect(m.beats).toEqual(m.voices[0])
  })

  it('keySignature != 0 이면 포함', () => {
    const score = mockScore({ keySignature: 2 })
    const snap = serializeScore(score)
    expect(snap.tracks[0].measures[0].keySignature).toBe(2)
  })

  it('keySignature == 0 이면 undefined', () => {
    const score = mockScore({ keySignature: 0 })
    const snap = serializeScore(score)
    expect(snap.tracks[0].measures[0].keySignature).toBeUndefined()
  })

  it('sectionMarker 포함', () => {
    const score = mockScore({ sectionMarker: 'Intro' })
    const snap = serializeScore(score)
    expect(snap.tracks[0].measures[0].sectionMarker).toBe('Intro')
  })

  it('section null이면 sectionMarker undefined', () => {
    const score = mockScore()
    const snap = serializeScore(score)
    expect(snap.tracks[0].measures[0].sectionMarker).toBeUndefined()
  })
})
