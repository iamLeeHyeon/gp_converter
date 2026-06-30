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
    duration: { value: 4, isDotted: false },
    isRest: false,
    dynamics: 4,      // 4 = mf
    pickStroke: 0,    // 0 = None
    notes: [makeNote()],
    ...overrides,
  }
}

function makeScore(beats = [makeBeat()]) {
  return {
    tracks: [{
      staves: [{
        bars: [{
          masterBar: { timeSignatureNumerator: 4, timeSignatureDenominator: 4 },
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
    const snap = serializeScore(makeScore([makeBeat({ duration: { value: 4, isDotted: true } })]))
    expect(snap.tracks[0].measures[0].beats[0].dotted).toBe(true)
  })

  it('strumDown=true를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ pickStroke: 2 })]))  // 2 = Down
    expect(snap.tracks[0].measures[0].beats[0].strumDown).toBe(true)
  })

  it('strumUp=false를 직렬화한다', async () => {
    const { serializeScore } = await import('../lib/scoreSerializer')
    const snap = serializeScore(makeScore([makeBeat({ pickStroke: 1 })]))  // 1 = Up
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
