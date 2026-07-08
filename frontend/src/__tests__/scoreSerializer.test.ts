import { describe, expect, it } from 'vitest'

function makeNote(overrides: Record<string, unknown> = {}) {
  return {
    string: 1, fret: 5,
    isHammerPullOrigin: false, isGhost: false, isDead: false,
    slideInType: 0,   // 0 = None
    slideOutType: 0,  // 0 = None
    harmonicType: 0,  // 0 = None
    ...overrides,
  }
}

function makeBeat(overrides: Record<string, unknown> = {}) {
  return {
    duration: 4, dots: 0,
    isRest: false,
    dynamics: 4,      // 4 = mf (alphaTab DynamicValue enum)
    pickStroke: 0,    // 0 = None
    notes: [makeNote()],
    ...overrides,
  }
}

function makeScore(beats = [makeBeat()]) {
  return {
    tracks: [{
      name: 'Guitar',
      tuning: [64, 59, 55, 50, 45, 40],
      staves: [{
        bars: [{
          masterBar: {
            // alphaTab의 실제 MasterBar 모양: 중첩 timeSignature 객체가 아니라
            // 평평한 timeSignatureNumerator/timeSignatureDenominator 필드다.
            // (예전엔 여기가 중첩 모양으로 잘못 목킹돼있어서 구현의 같은 실수를
            // 테스트가 못 잡았다 — 실사용 중 발견된 버그)
            timeSignatureNumerator: 4,
            timeSignatureDenominator: 4,
            keySignature: 0,
            section: null,
          },
          voices: [{ beats }],
        }],
      }],
    }],
  }
}

describe('serializeScore', () => {
  it('기본 beat를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore())
    expect(snap.tracks).toHaveLength(1)
    expect(snap.tracks[0].measures).toHaveLength(1)
    const beat = snap.tracks[0].measures[0].beats[0]
    expect(beat.duration).toBe(4)
    expect(beat.dotted).toBe(false)
    expect(beat.status).toBe('normal')
    expect(beat.dynamic).toBe('mf')
    expect(beat.notes[0]).toMatchObject({ string: 1, fret: 5 })
  })

  it('rest beat를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ isRest: true, notes: [] })]))
    expect(snap.tracks[0].measures[0].beats[0].status).toBe('rest')
  })

  it('점음표를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ dots: 1 })]))
    expect(snap.tracks[0].measures[0].beats[0].dotted).toBe(true)
  })

  it('strumDown=true를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ pickStroke: 2 })]))  // 2 = Down (strumDown=true)
    expect(snap.tracks[0].measures[0].beats[0].strumDown).toBe(true)
  })

  it('strumUp=false를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ pickStroke: 1 })]))  // 1 = Up (strumDown=false)
    expect(snap.tracks[0].measures[0].beats[0].strumDown).toBe(false)
  })

  it('hammer-on 이펙트를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ notes: [makeNote({ isHammerPullOrigin: true })] })]))
    expect(snap.tracks[0].measures[0].beats[0].notes[0].effect).toBe('hammer-on')
  })

  it('ghost 이펙트를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ notes: [makeNote({ isGhost: true })] })]))
    expect(snap.tracks[0].measures[0].beats[0].notes[0].effect).toBe('ghost')
  })

  it('mute 이펙트를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ notes: [makeNote({ isDead: true })] })]))
    expect(snap.tracks[0].measures[0].beats[0].notes[0].effect).toBe('mute')
  })

  it('박자표를 직렬화한다', async () => {
    const score = makeScore()
    score.tracks[0].staves[0].bars[0].masterBar.timeSignatureNumerator = 3
    score.tracks[0].staves[0].bars[0].masterBar.timeSignatureDenominator = 4
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(score)
    expect(snap.tracks[0].measures[0].timeSignature).toEqual({ num: 3, den: 4 })
  })
})
