import { describe, expect, it } from 'vitest'
import type { NotePosition } from '../lib/scoreTypes'

function makeNote(overrides: Record<string, unknown> = {}) {
  return { string: 1, fret: 5, isHammerPullOrigin: false, isGhost: false, isDead: false, slideInType: 0, slideOutType: 0, harmonicType: 0, ...overrides }
}

// alphaTab의 Note.findHammerPullDestination/nextNoteOnSameLine은 note.beat.nextBeat를
// 타고 다음 박자에서 같은 줄의 노트를 찾는다 — 이 최소 체인을 갖춰야 hammer-on/
// legato 슬라이드가 목적지를 실제로 찾아내는지 검증할 수 있다.
function makeBeat(overrides: Record<string, unknown> = {}) {
  const notes = (overrides.notes as Record<string, unknown>[] | undefined) ?? [makeNote()]
  const beat: Record<string, unknown> = {
    duration: 4, dots: 0,
    isRest: false, dynamics: 4, pickStroke: 0,
    notes,
    nextBeat: null,
    voice: { bar: { index: 0 } },
    getNoteOnString: (str: number) => notes.find((n) => n.string === str) ?? null,
    // 실제 alphaTab의 Beat.addNote/removeNote와 동일하게 note.beat/note.index
    // 백링크를 채운다 — applyEdit이 이 메서드에 위임하므로 mock도 맞춰야 한다.
    addNote(note: Record<string, unknown>) {
      note.beat = beat
      note.index = notes.length
      notes.push(note)
    },
    removeNote(note: Record<string, unknown>) {
      const i = notes.indexOf(note)
      if (i >= 0) notes.splice(i, 1)
    },
    ...overrides,
  }
  notes.forEach((n) => { n.beat = beat })
  return beat
}

function makeScore(beats = [makeBeat()]) {
  for (let i = 0; i < beats.length - 1; i++) {
    (beats[i] as Record<string, unknown>).nextBeat = beats[i + 1]
  }
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
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].duration).toBe(8)
  })

  it('점음표를 토글한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'dotted', value: true })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].dots).toBe(1)
  })

  it('hammer-on 이펙트를 적용하면 다음 박자의 같은 줄 음표를 목적지로 찾아 슬러를 그린다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const originNote = makeNote({ string: 1, fret: 5 })
    const destNote = makeNote({ string: 1, fret: 7 })
    const score = makeScore([makeBeat({ notes: [originNote] }), makeBeat({ notes: [destNote] })])

    applyEdit(score, POS, { type: 'effect', value: 'hammer-on' })

    expect(originNote.isHammerPullOrigin).toBe(true)
    expect(originNote.hammerPullDestination).toBe(destNote)
    expect(originNote.hasEffectSlur).toBe(true)
  })

  it('hammer-on 목적지를 찾을 수 없으면(다음 박자 없음) isHammerPullOrigin을 다시 끈다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'effect', value: 'hammer-on' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes[0].isHammerPullOrigin).toBe(false)
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

  it('노트가 없는 박자(rest)에 처음 음표를 추가하면 string=1을 쓴다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore([makeBeat({ notes: [] })])
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'addNote' })
    const beat = score.tracks[0].staves[0].bars[0].voices[0].beats[0]
    expect(beat.notes).toMatchObject([{ string: 1, fret: 0 }])
  })

  it('음표를 추가하면 화음이 되도록 이미 쓰인 줄(string)은 피해서 추가한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore() // 기본 노트: string=1
    const before = score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length
    applyEdit(score, { ...POS, noteIndex: null }, { type: 'addNote' })
    const beat = score.tracks[0].staves[0].bars[0].voices[0].beats[0]
    expect(beat.notes.length).toBe(before + 1)
    expect(beat.notes.at(-1)).toMatchObject({ string: 2, fret: 0 })
  })

  it('음표를 삭제한다', async () => {
    const { applyEdit } = await import('../lib/scoreApplier')
    const score = makeScore()
    applyEdit(score, POS, { type: 'deleteNote' })
    expect(score.tracks[0].staves[0].bars[0].voices[0].beats[0].notes.length).toBe(0)
  })
})
