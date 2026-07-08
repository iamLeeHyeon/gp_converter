import { describe, expect, it } from 'vitest'
import { collectPitchYSamples, estimatePitchFromY, findStringFretForPitch } from '../lib/pitchPosition'

function makeNoteBounds(pitch: number, y: number) {
  return { note: { realValue: pitch }, noteHeadBounds: { x: 0, y, w: 10, h: 8 } }
}

describe('collectPitchYSamples', () => {
  it('같은 시스템의 모든 마디/박자에서 (음높이, Y) 표본을 모은다', () => {
    const beatBounds = {
      barBounds: {
        masterBarBounds: {
          staffSystemBounds: {
            bars: [
              { bars: [{ beats: [{ notes: [makeNoteBounds(60, 100)] }] }] },
              { bars: [{ beats: [{ notes: [makeNoteBounds(64, 90)] }, { notes: [makeNoteBounds(67, 80)] }] }] },
            ],
          },
        },
      },
    }
    const samples = collectPitchYSamples(beatBounds)
    expect(samples).toEqual([
      { pitch: 60, y: 104 },
      { pitch: 64, y: 94 },
      { pitch: 67, y: 84 },
    ])
  })

  it('staffSystemBounds가 없으면 현재 마디만 훑는다', () => {
    const beatBounds = {
      barBounds: {
        masterBarBounds: {
          staffSystemBounds: null,
          bars: [{ beats: [{ notes: [makeNoteBounds(60, 100)] }] }],
        },
      },
    }
    const samples = collectPitchYSamples(beatBounds)
    expect(samples).toEqual([{ pitch: 60, y: 104 }])
  })
})

describe('estimatePitchFromY', () => {
  it('표본이 없으면 null', () => {
    expect(estimatePitchFromY([], 100)).toBeNull()
  })

  it('표본이 하나뿐이면 그 음을 그대로 반환한다', () => {
    expect(estimatePitchFromY([{ pitch: 60, y: 100 }], 100)).toBe(60)
  })

  it('표본 범위를 크게 벗어난 Y(탭보 영역 등)는 추정하지 않는다', () => {
    const samples = [{ pitch: 60, y: 100 }, { pitch: 67, y: 80 }]
    expect(estimatePitchFromY(samples, 300)).toBeNull()
  })

  it('선형회귀로 두 표본 사이/근방의 음을 추정한다(Y가 작을수록 음이 높다)', () => {
    // y = -2*pitch + 220  → pitch=60→y=100, pitch=70→y=80
    const samples = [{ pitch: 60, y: 100 }, { pitch: 70, y: 80 }]
    expect(estimatePitchFromY(samples, 90)).toBe(65)
    expect(estimatePitchFromY(samples, 100)).toBe(60)
  })
})

describe('findStringFretForPitch', () => {
  // alphaTab tuning 배열은 [가장 높은 음 줄, ..., 가장 낮은 음 줄] 순서로 저장되고
  // note.string=1이 "가장 낮은 줄"(배열의 마지막 요소)에 대응한다(리서치로 확인).
  // 표준 튜닝: string6=64(E4,1번째 요소) ... string1=40(E2,마지막 요소)
  const staff = { tuning: [64, 59, 55, 50, 45, 40], capo: 0 }

  it('목표 음을 낼 수 있는 가장 작은 프렛의 줄을 고른다', () => {
    // string=6(open=64)에서 fret=0이면 정확히 64 — 가능한 모든 줄 중 프렛이 가장 작다
    const result = findStringFretForPitch(staff, new Set(), 64)
    expect(result).toEqual({ string: 6, fret: 0 })
  })

  it('이미 쓰인 줄은 피한다', () => {
    // string=6(가장 작은 프렛)이 이미 쓰였으면 다음으로 작은 프렛의 줄을 찾는다
    // (string=5, open=59, fret=5)
    const result = findStringFretForPitch(staff, new Set([6]), 64)
    expect(result).toEqual({ string: 5, fret: 5 })
  })

  it('capo를 반영한다(카포 2 걸린 상태에서 열린 음보다 낮은 프렛은 못 씀)', () => {
    const capoStaff = { tuning: [64, 59, 55, 50, 45, 40], capo: 2 }
    // string6 open = 2+64=66 → fret=64-66=-2(무효, 스킵), string5 open=2+59=61 → fret=64-61=3
    const result = findStringFretForPitch(capoStaff, new Set(), 64)
    expect(result).toEqual({ string: 5, fret: 3 })
  })

  it('어떤 줄로도 낼 수 없는 음(프렛 범위 밖)이면 null', () => {
    const result = findStringFretForPitch(staff, new Set(), 200)
    expect(result).toBeNull()
  })

  it('튜닝 정보가 없으면 null', () => {
    expect(findStringFretForPitch({ tuning: [], capo: 0 }, new Set(), 64)).toBeNull()
  })
})
