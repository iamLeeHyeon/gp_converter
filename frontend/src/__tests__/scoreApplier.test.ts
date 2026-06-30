import { describe, expect, it } from 'vitest'
import type { NotePosition } from '../lib/scoreTypes'

function makeNote(overrides: Record<string, unknown> = {}) {
  return { string: 1, fret: 5, isHammerPullOrigin: false, isGhost: false, isDead: false, slideInType: 0, slideOutType: 0, harmonicType: 0, ...overrides }
}

function makeBeat(overrides: Record<string, unknown> = {}) {
  return {
    duration: { value: 4, isDotted: false },
    isRest: false, dynamics: 4, pickStroke: 0,
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

const POS: NotePosition = { trackIndex: 0, measureIndex: 0, voiceIndex: 0, beatIndex: 0, noteIndex: 0 }

describe('applyEdit', () => {
  it('프렛을 변경한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'fret', value: 12 })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].fret).toBe(12)
  })

  it('지속시간을 변경한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'duration', value: 8 })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].duration.value).toBe(8)
  })

  it('점음표를 토글한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'dotted', value: true })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].duration.isDotted).toBe(true)
  })

  it('hammer-on 이펙트를 적용한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'effect', value: 'hammer-on' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].isHammerPullOrigin).toBe(true)
  })

  it('이펙트를 null로 초기화한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore([makeBeat({ notes: [makeNote({ isHammerPullOrigin: true })] })])
    applyEdit(score, POS, { type: 'effect', value: null })
    const note = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0]
    expect(note.isHammerPullOrigin).toBe(false)
  })

  it('다이나믹을 변경한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'dynamic', value: 'ff' })
    // 6 = ff
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].dynamics).toBe(6)
  })

  it('strumDown을 설정한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'strumDown', value: true })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].pickStroke).toBe(2)
  })

  it('음표를 추가한다 (string=1, fret=0)', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    const before = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'addNote' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length).toBe(before + 1)
    const added = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.at(-1)!
    expect(added).toMatchObject({ string: 1, fret: 0 })
  })

  it('음표를 삭제한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'deleteNote' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length).toBe(0)
  })
})
