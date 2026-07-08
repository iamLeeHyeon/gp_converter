// 오선보 빈 자리를 클릭했을 때 "그 위치가 어떤 음(pitch)인지" 추정한다.
// alphaTab은 클릭 좌표를 음/기타 줄로 변환하는 공개 API를 제공하지 않으므로
// (조사 결과: 내부 비공개 렌더러 로직에만 존재), 같은 시스템(줄바꿈 단위)에
// 이미 렌더링된 노트들의 (실제 음높이, 노트머리 Y좌표) 표본을 선형 회귀해
// 근사한다 — 완전히 정확하진 않지만(오선 간격이 조표에 따라 미세하게 달라질
// 수 있음), 서로 다른 위치를 구분하기엔 충분하다.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function collectPitchYSamples(beatBounds: any): { pitch: number; y: number }[] {
  const samples: { pitch: number; y: number }[] = []
  const staffSystem = beatBounds?.barBounds?.masterBarBounds?.staffSystemBounds
  const masterBars = staffSystem ? staffSystem.bars : [beatBounds?.barBounds?.masterBarBounds].filter(Boolean)
  for (const mbb of masterBars ?? []) {
    for (const bb of mbb.bars ?? []) {
      for (const beat of bb.beats ?? []) {
        if (!beat.notes) continue
        for (const nb of beat.notes) {
          samples.push({ pitch: nb.note.realValue as number, y: nb.noteHeadBounds.y + nb.noteHeadBounds.h / 2 })
        }
      }
    }
  }
  return samples
}

// 표준악보 노트머리 Y 범위를 크게 벗어난 클릭(예: 탭보 영역)은 추정하지 않는다
// — 회귀식을 그 범위 밖으로 외삽하면 완전히 엉뚱한 음이 나올 수 있다.
const OUT_OF_RANGE_MARGIN = 30

export function estimatePitchFromY(samples: { pitch: number; y: number }[], y: number): number | null {
  if (samples.length === 0) return null

  const ys = samples.map((s) => s.y)
  const minY = Math.min(...ys)
  const maxY = Math.max(...ys)
  if (y < minY - OUT_OF_RANGE_MARGIN || y > maxY + OUT_OF_RANGE_MARGIN) return null

  if (samples.length === 1) return samples[0].pitch

  // 최소자승 선형회귀: y = a*pitch + b
  const n = samples.length
  const sumP = samples.reduce((s, v) => s + v.pitch, 0)
  const sumY = samples.reduce((s, v) => s + v.y, 0)
  const sumPY = samples.reduce((s, v) => s + v.pitch * v.y, 0)
  const sumPP = samples.reduce((s, v) => s + v.pitch * v.pitch, 0)
  const denom = n * sumPP - sumP * sumP
  if (Math.abs(denom) < 1e-6) return samples[0].pitch // 표본들의 음높이가 전부 같음 — 회귀 불가

  const a = (n * sumPY - sumP * sumY) / denom
  const b = (sumY - a * sumP) / n
  if (Math.abs(a) < 1e-6) return null
  return Math.round((y - b) / a)
}

// alphaTab Note.realValue = fret + capo + tuning[tuning.length - (string-1) - 1] 공식의 역산.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function findStringFretForPitch(
  staff: any,
  usedStrings: Set<number>,
  targetPitch: number,
): { string: number; fret: number } | null {
  const tuning = (staff?.tuning as number[]) ?? []
  const stringCount = tuning.length
  if (stringCount === 0) return null
  const capo = (staff.capo as number) ?? 0

  let best: { string: number; fret: number } | null = null
  for (let s = 1; s <= stringCount; s++) {
    if (usedStrings.has(s)) continue
    const openPitch = capo + tuning[stringCount - (s - 1) - 1]
    const fret = targetPitch - openPitch
    if (fret >= 0 && fret <= 24 && (!best || fret < best.fret)) {
      best = { string: s, fret }
    }
  }
  return best
}
