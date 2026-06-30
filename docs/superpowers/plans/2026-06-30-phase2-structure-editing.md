# Phase 2 구조 편집기 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 마디 추가/삭제/이동, 박자표·조표·섹션마커 변경, 다중 트랙, 튜닝/Capo, 다성부 편집 지원

**Architecture:** 구조 편집은 Snapshot-first 방식. `applyStructuralEdit(snapshot, edit) → ScoreSnapshot` → `forceSync()` 즉시 POST /sync → 서버 GP5 재생성 → alphaTab 리로드. 음표 편집(scoreApplier)과 달리 alphaTab 모델 직접 수정 없음.

**Tech Stack:** FastAPI, PyGuitarPro (`guitarpro`), React, Zustand, alphaTab ^1.8.3, vitest, pytest

## Global Constraints

- alphaTab 버전: `^1.8.3`
- PyGuitarPro 모듈명: `guitarpro` (import as `import guitarpro as gpm`)
- 백엔드 테스트: pytest + TestClient, `SessionLocal()` 직접 사용, DB override 없음
- 프론트 테스트: vitest + @testing-library/react + userEvent
- 모든 엔드포인트: Bearer 인증 필수 (`get_current_user` dependency)
- capo: PyGuitarPro Track에 attribute 없음 → ScoreSnapshot에 보관만, GP5 생성 시 skip
- 다중 트랙 생성: `gpm.Track(song, number=N, strings=[gpm.GuitarString(i+1, v) for i, v in enumerate(tuning)])` 패턴 사용
- MeasureHeader는 트랙 간 공유: 조표/박자표/섹션마커는 tracks[0] 기준으로 설정

---

### Task 1: ScoreSnapshot v2 타입 + scoreSerializer v2

**Files:**
- Modify: `frontend/src/lib/scoreTypes.ts`
- Modify: `frontend/src/lib/scoreSerializer.ts`
- Test: `frontend/src/__tests__/scoreSerializer.v2.test.ts`

**Interfaces:**
- Produces:
  - `SnapshotTrack { name?, capo?, tuning?, measures: SnapshotMeasure[] }`
  - `SnapshotMeasure { timeSignature, keySignature?, sectionMarker?, voices: SnapshotBeat[][], beats?: SnapshotBeat[] }`
  - `ScoreSnapshot { tracks: SnapshotTrack[] }`
  - `serializeScore(score: any): ScoreSnapshot` — v2 출력

- [ ] **Step 1: 실패하는 테스트 작성**

새 파일 `frontend/src/__tests__/scoreSerializer.v2.test.ts`:

```typescript
import { describe, it, expect } from 'vitest'
import { serializeScore } from '../lib/scoreSerializer'

function mockBeat(isRest = false) {
  return {
    duration: { value: 4, isDotted: false },
    isRest,
    pickStroke: 0,
    notes: isRest ? [] : [{ string: 1, fret: 5, isHammerPullOrigin: false, isDead: false, isGhost: false, harmonicType: 0, slideOutType: 0, slideInType: 0 }],
    velocity: 95,
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
        bars: [{
          masterBar: {
            timeSignature: { numerator: 4, denominator: { value: 4 } },
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
    // capo는 alphaTab에 없으므로 score 객체에서 읽지 않고 기본값 0
    const snap = serializeScore(score)
    expect(snap.tracks[0].name).toBe('Bass')
    expect(snap.tracks[0].tuning).toEqual([64, 59, 55, 50, 45, 40])  // score.tuning 사용
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/scoreSerializer.v2.test.ts
```

Expected: FAIL (`snap.tracks[0].name` undefined, `voices` 없음)

- [ ] **Step 3: scoreTypes.ts 수정**

`frontend/src/lib/scoreTypes.ts` 전체 내용:

```typescript
export type Effect =
  | 'hammer-on' | 'pull-off'
  | 'slide-shift' | 'slide-legato'
  | 'slide-in-above' | 'slide-out-below'
  | 'mute' | 'ghost' | 'harmonic'

export type Dynamic = 'ppp' | 'pp' | 'p' | 'mp' | 'mf' | 'f' | 'ff' | 'fff'

export interface SnapshotNote {
  string: number      // 1-6, GP 컨벤션 (1=high E)
  fret: number        // 0-24
  effect?: Effect
}

export interface SnapshotBeat {
  duration: 1 | 2 | 4 | 8 | 16 | 32
  dotted: boolean
  status: 'normal' | 'rest'
  notes: SnapshotNote[]
  strumDown?: boolean
  dynamic?: Dynamic
}

export interface SnapshotMeasure {
  timeSignature: { num: number; den: number }
  keySignature?: number      // -7(플랫7)~7(샾7), 0=C장조; 0이면 생략
  sectionMarker?: string     // 섹션 이름
  voices: SnapshotBeat[][]   // voices[0]=Voice1, voices[1]=Voice2
  beats?: SnapshotBeat[]     // voices[0] alias (하위 호환)
}

export interface SnapshotTrack {
  name?: string
  capo?: number              // 0-12; 0이면 생략 (GP5 생성 시 미반영, 메타데이터용)
  tuning?: number[]          // 개방현 MIDI 값 6개 [string1..string6]
  measures: SnapshotMeasure[]
}

export interface ScoreSnapshot {
  tracks: SnapshotTrack[]
}

export interface NotePosition {
  trackIndex: number
  measureIndex: number    // 0-based bar index
  voiceIndex: number      // 0 or 1
  beatIndex: number       // 0-based beat index within voice
  noteIndex: number | null // null = beat selected (no specific note)
}

export type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'
```

- [ ] **Step 4: scoreSerializer.ts 수정**

`frontend/src/lib/scoreSerializer.ts` 전체 내용:

```typescript
import type { ScoreSnapshot, SnapshotTrack, SnapshotMeasure, SnapshotBeat, SnapshotNote, Dynamic, Effect } from './scoreTypes'

const DYNAMIC_VALUES: Record<number, Dynamic> = {
  0: 'ppp', 1: 'pp', 2: 'p', 3: 'mp', 4: 'mf', 5: 'f', 6: 'ff', 7: 'fff',
}

const SLIDE_OUT_TYPE_MAP: Record<number, Effect> = {
  1: 'slide-shift',
  2: 'slide-legato',
  4: 'slide-out-below',
}
const SLIDE_IN_TYPE_MAP: Record<number, Effect> = {
  2: 'slide-in-above',
}

function getNoteEffect(note: Record<string, unknown>): Effect | undefined {
  if (note.isHammerPullOrigin) return 'hammer-on'
  if (note.isDead) return 'mute'
  if (note.isGhost) return 'ghost'
  if ((note.harmonicType as number) > 0) return 'harmonic'
  const slideOutType = note.slideOutType as number
  if (slideOutType > 0 && SLIDE_OUT_TYPE_MAP[slideOutType]) return SLIDE_OUT_TYPE_MAP[slideOutType]
  const slideInType = note.slideInType as number
  if (slideInType > 0 && SLIDE_IN_TYPE_MAP[slideInType]) return SLIDE_IN_TYPE_MAP[slideInType]
  return undefined
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function serializeBeat(beat: any): SnapshotBeat {
  const pickStroke = beat.pickStroke as number
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const notes: SnapshotNote[] = (beat.isRest ? [] : (beat.notes as any[])).map(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (note: any): SnapshotNote => ({
      string: note.string as number,
      fret: note.fret as number,
      effect: getNoteEffect(note),
    }),
  )
  return {
    duration: beat.duration.value as 1 | 2 | 4 | 8 | 16 | 32,
    dotted: beat.duration.isDotted as boolean,
    status: beat.isRest ? 'rest' : 'normal',
    notes,
    strumDown: pickStroke === 1 ? true : pickStroke === 2 ? false : undefined,
    dynamic: DYNAMIC_VALUES[beat.velocity as number],
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function serializeScore(score: any): ScoreSnapshot {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const tracks: SnapshotTrack[] = score.tracks.map((track: any) => {
    const name = (track.name as string) || undefined
    const tuning = Array.isArray(track.tuning) ? (track.tuning as number[]) : undefined

    const staff = track.staves[0]
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const measures: SnapshotMeasure[] = staff.bars.map((bar: any) => {
      const mb = bar.masterBar
      const keySignatureVal = mb.keySignature as number
      const keySignature = keySignatureVal !== 0 ? keySignatureVal : undefined
      const sectionMarker = mb.section ? ((mb.section.text as string) || undefined) : undefined

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const voices: SnapshotBeat[][] = (bar.voices as any[]).map((voice: any) =>
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (voice.beats as any[])
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          .filter((b: any) => b.duration != null)
          .map(serializeBeat),
      )

      return {
        timeSignature: {
          num: mb.timeSignature.numerator as number,
          den: mb.timeSignature.denominator.value as number,
        },
        keySignature,
        sectionMarker,
        voices,
        beats: voices[0],
      }
    })

    return { name, tuning, measures }
  })

  return { tracks }
}
```

- [ ] **Step 5: 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/scoreSerializer.v2.test.ts
```

Expected: 모두 PASS

- [ ] **Step 6: 기존 테스트 통과 확인**

```
cd frontend && npx vitest run
```

Expected: 모두 PASS (scoreSerializer 관련 기존 테스트 포함)

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/lib/scoreTypes.ts \
        frontend/src/lib/scoreSerializer.ts \
        frontend/src/__tests__/scoreSerializer.v2.test.ts
git commit -m "feat: ScoreSnapshot v2 — SnapshotTrack + voices + keySignature + sectionMarker"
```

---

### Task 2: applyStructuralEdit 함수

**Files:**
- Create: `frontend/src/lib/structuralEdit.ts`
- Test: `frontend/src/__tests__/structuralEdit.test.ts`

**Interfaces:**
- Consumes: `ScoreSnapshot`, `SnapshotTrack`, `SnapshotMeasure`, `SnapshotBeat` (from Task 1)
- Produces:
  - `StructuralEdit` (union type)
  - `applyStructuralEdit(snapshot: ScoreSnapshot, edit: StructuralEdit): ScoreSnapshot`

- [ ] **Step 1: 실패하는 테스트 작성**

새 파일 `frontend/src/__tests__/structuralEdit.test.ts`:

```typescript
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
```

- [ ] **Step 2: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/structuralEdit.test.ts
```

Expected: FAIL (Cannot find module `../lib/structuralEdit`)

- [ ] **Step 3: `frontend/src/lib/structuralEdit.ts` 구현**

```typescript
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
        tracks[edit.trackIndex] = { ...tracks[edit.trackIndex], tuning: edit.tuning }
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
```

- [ ] **Step 4: 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/structuralEdit.test.ts
```

Expected: 모두 PASS

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/lib/structuralEdit.ts \
        frontend/src/__tests__/structuralEdit.test.ts
git commit -m "feat: applyStructuralEdit — 마디/트랙/박자표/조표/마커 구조 편집"
```

---

### Task 3: snapshot_to_gp5 v2 — 마디 속성 (keySignature, sectionMarker, voices)

**Files:**
- Modify: `app/pipeline/token_to_gp.py` (함수 `snapshot_to_gp5`)
- Test: `tests/test_structure_edit.py` (새 파일)

**Interfaces:**
- Consumes: `ScoreSnapshot` v2 dict (`voices`, `keySignature`, `sectionMarker`)
- Produces: `snapshot_to_gp5(snapshot, out_path)` — v2 필드 반영한 GP5 파일

- [ ] **Step 1: 실패하는 테스트 작성**

새 파일 `tests/test_structure_edit.py`:

```python
import os
import pytest
import guitarpro as gpm

from app.pipeline.token_to_gp import snapshot_to_gp5


def _snap_1track_1measure(**measure_kwargs):
    """단일 트랙, 단일 마디 스냅샷 생성 헬퍼."""
    base = {
        "timeSignature": {"num": 4, "den": 4},
        "voices": [[
            {"duration": 4, "dotted": False, "status": "normal",
             "dynamic": "mf", "notes": [{"string": 1, "fret": 0}]},
        ]],
    }
    base.update(measure_kwargs)
    return {"tracks": [{"measures": [base]}]}


class TestSnapshotV2MeasureAttrs:
    def test_keySignature_1_written(self, tmp_path):
        """keySignature=1 → GP5 MeasureHeader.keySignature=1."""
        snap = _snap_1track_1measure(keySignature=1)
        path = str(tmp_path / "key1.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].keySignature == 1

    def test_keySignature_default_0(self, tmp_path):
        """keySignature 없으면 0(C장조)."""
        snap = _snap_1track_1measure()
        path = str(tmp_path / "key0.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].keySignature == 0

    def test_sectionMarker_written(self, tmp_path):
        """sectionMarker='Intro' → GP5 MeasureHeader.marker.title='Intro'."""
        snap = _snap_1track_1measure(sectionMarker="Intro")
        path = str(tmp_path / "marker.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].marker is not None
        assert song.measureHeaders[0].marker.title == "Intro"

    def test_no_sectionMarker_no_marker(self, tmp_path):
        """sectionMarker 없으면 marker=None."""
        snap = _snap_1track_1measure()
        path = str(tmp_path / "nomarker.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].marker is None

    def test_voices_fallback_to_beats(self, tmp_path):
        """v1 호환: voices 없고 beats 있으면 정상 변환."""
        snap = {"tracks": [{"measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "beats": [
                {"duration": 4, "dotted": False, "status": "normal",
                 "dynamic": "mf", "notes": [{"string": 1, "fret": 5}]},
            ],
        }]}]}
        path = str(tmp_path / "v1compat.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        note_ons = [n for t in song.tracks for m in t.measures
                    for v in m.voices for b in v.beats
                    for n in b.notes if n.type == gpm.NoteType.normal]
        assert len(note_ons) >= 1
```

- [ ] **Step 2: 테스트 실패 확인**

```
pytest tests/test_structure_edit.py -v
```

Expected: FAIL (keySignature 미반영, sectionMarker 미반영)

- [ ] **Step 3: snapshot_to_gp5 수정**

`app/pipeline/token_to_gp.py`의 `snapshot_to_gp5` 함수에서:

1. 내부 헬퍼 `_fill_snap` 상단에 `voices` fallback 처리 추가:

```python
def _fill_snap(measure, mdata):
    voice = measure.voices[0]
    voice.beats = []
    # v2: voices[0] 우선, 없으면 beats fallback (v1 호환)
    voices_data = mdata.get("voices")
    beats_data = (voices_data[0] if voices_data else None) or mdata.get("beats", [])
    # ... (이하 기존 로직, beats_data 변수 사용)
```

기존 `beats_data = mdata.get("beats", [])` 한 줄을 위 두 줄로 교체.

2. 첫 번째 MeasureHeader 설정 블록 뒤에 추가:

```python
    # keySignature (v2)
    first_mh.keySignature = ts0.get("keySignature", 0)
    # sectionMarker (v2)
    marker_name = measures_data[0].get("sectionMarker")
    if marker_name:
        first_mh.marker = gpm.Marker(title=marker_name)
```

3. 루프 내 각 추가 마디 설정 블록에도 동일하게 추가:

```python
        # keySignature / sectionMarker (v2)
        ts = mdata.get("timeSignature", {})
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        mh.timeSignature.numerator = ts.get("num", 4)
        mh.timeSignature.denominator.value = ts.get("den", 4)
        mh.keySignature = mdata.get("keySignature", 0)          # 추가
        marker_name = mdata.get("sectionMarker")                # 추가
        if marker_name:                                          # 추가
            mh.marker = gpm.Marker(title=marker_name)           # 추가
        song.measureHeaders.append(mh)
```

실제 수정할 라인 위치는 아래와 같음. `snapshot_to_gp5` 함수 전체 최신 버전:

```python
def snapshot_to_gp5(snapshot: dict, out_path: str) -> str:
    """ScoreSnapshot JSON dict → .gp5 파일 저장."""
    _DYN_STR_MAP = {"ppp": 15, "pp": 31, "p": 47, "mp": 63,
                    "mf": 79, "f": 95, "ff": 111, "fff": 127}
    _SLIDE_MAP = {
        "slide-shift": SlideType.shiftSlideTo,
        "slide-legato": SlideType.legatoSlideTo,
        "slide-in-above": SlideType.intoFromAbove,
        "slide-out-below": SlideType.outUpwards,
    }

    tracks_data = snapshot.get("tracks", [])
    if not tracks_data:
        raise ValueError("snapshot에 트랙 없음")
    # MeasureHeader는 tracks[0] 기준으로 공유
    measures_data = tracks_data[0].get("measures", [])
    if not measures_data:
        raise ValueError("snapshot에 마디 없음")

    def _get_beats(mdata: dict) -> list:
        """v2: voices[0], v1 fallback: beats."""
        voices = mdata.get("voices")
        if voices and len(voices) > 0:
            return voices[0] or []
        return mdata.get("beats", [])

    def _get_voice1_beats(mdata: dict) -> list:
        """v2: voices[1] 반환. 없으면 빈 리스트."""
        voices = mdata.get("voices")
        if voices and len(voices) > 1:
            return voices[1] or []
        return []

    def _fill_voice(voice, beats_data: list):
        """beat 데이터로 voice 채우기."""
        voice.beats = []
        expected = 64.0  # 임시 — _fill_snap에서 계산
        accumulated = 0.0

        for bdata in beats_data:
            dur_val = bdata.get("duration", 4)
            units = _DUR_UNITS.get(dur_val, 16)
            if bdata.get("dotted"):
                units *= 1.5

            beat = Beat(voice)
            beat.duration = gpm.Duration()
            beat.duration.value = dur_val
            if bdata.get("dotted"):
                beat.duration.isDotted = True

            notes_data = bdata.get("notes", [])
            if bdata.get("status") == "rest" or not notes_data:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                dyn_str = bdata.get("dynamic", "mf")
                vel = _DYN_STR_MAP.get(dyn_str, 79)
                for nd in notes_data:
                    gnote = Note(beat)
                    gnote.value = nd.get("fret", 0)
                    gnote.string = nd.get("string", 1)
                    gnote.velocity = vel
                    gnote.type = NoteType.normal
                    effect = nd.get("effect")
                    if effect == "hammer-on":
                        gnote.effect.hammer = True
                    elif effect == "mute":
                        gnote.type = NoteType.dead
                    elif effect == "ghost":
                        gnote.effect.ghostNote = True
                    elif effect == "harmonic":
                        gnote.effect.harmonic = gpm.NaturalHarmonic()
                    elif effect in _SLIDE_MAP:
                        gnote.effect.slides = [_SLIDE_MAP[effect]]
                    beat.notes.append(gnote)

            strum = bdata.get("strumDown")
            if strum is True:
                beat.effect.pickStroke = BeatStrokeDirection.down
                beat.effect.stroke.direction = BeatStrokeDirection.down
                beat.effect.stroke.value = dur_val
            elif strum is False:
                beat.effect.pickStroke = BeatStrokeDirection.up
                beat.effect.stroke.direction = BeatStrokeDirection.up
                beat.effect.stroke.value = dur_val

            voice.beats.append(beat)

    def _fill_snap(measure, mdata):
        """마디 데이터로 measure 채우기 (voice[0], voice[1])."""
        ts = mdata.get("timeSignature", {})
        num = ts.get("num", 4)
        den = ts.get("den", 4)
        expected = (num / den) * 64

        voice0 = measure.voices[0]
        voice0.beats = []
        accumulated = 0.0
        beats_data = _get_beats(mdata)

        for bdata in beats_data:
            dur_val = bdata.get("duration", 4)
            units = _DUR_UNITS.get(dur_val, 16)
            if bdata.get("dotted"):
                units *= 1.5
            if accumulated + units > expected + 0.01:
                break
            accumulated += units

            beat = Beat(voice0)
            beat.duration = gpm.Duration()
            beat.duration.value = dur_val
            if bdata.get("dotted"):
                beat.duration.isDotted = True

            notes_data = bdata.get("notes", [])
            if bdata.get("status") == "rest" or not notes_data:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                dyn_str = bdata.get("dynamic", "mf")
                vel = _DYN_STR_MAP.get(dyn_str, 79)
                for nd in notes_data:
                    gnote = Note(beat)
                    gnote.value = nd.get("fret", 0)
                    gnote.string = nd.get("string", 1)
                    gnote.velocity = vel
                    gnote.type = NoteType.normal
                    effect = nd.get("effect")
                    if effect == "hammer-on":
                        gnote.effect.hammer = True
                    elif effect == "mute":
                        gnote.type = NoteType.dead
                    elif effect == "ghost":
                        gnote.effect.ghostNote = True
                    elif effect == "harmonic":
                        gnote.effect.harmonic = gpm.NaturalHarmonic()
                    elif effect in _SLIDE_MAP:
                        gnote.effect.slides = [_SLIDE_MAP[effect]]
                    beat.notes.append(gnote)

            strum = bdata.get("strumDown")
            if strum is True:
                beat.effect.pickStroke = BeatStrokeDirection.down
                beat.effect.stroke.direction = BeatStrokeDirection.down
                beat.effect.stroke.value = dur_val
            elif strum is False:
                beat.effect.pickStroke = BeatStrokeDirection.up
                beat.effect.stroke.direction = BeatStrokeDirection.up
                beat.effect.stroke.value = dur_val

            voice0.beats.append(beat)

        # 남은 공간 쉼표 채움
        remaining = expected - accumulated
        if remaining > 0.01:
            for dv in _DUR_FILL_ORDER:
                fu = _DUR_UNITS[dv]
                while remaining >= fu - 0.01:
                    rest = Beat(voice0)
                    rest.status = BeatStatus.rest
                    rest.duration = gpm.Duration()
                    rest.duration.value = dv
                    rest.notes = []
                    voice0.beats.append(rest)
                    remaining -= fu

        if not voice0.beats:
            rest = Beat(voice0)
            rest.status = BeatStatus.rest
            rest.duration = gpm.Duration()
            rest.duration.value = 4
            rest.notes = []
            voice0.beats.append(rest)

        # Voice 1 (v2)
        v1_beats = _get_voice1_beats(mdata)
        if v1_beats:
            voice1 = measure.voices[1]
            voice1.beats = []
            for bdata in v1_beats:
                dur_val = bdata.get("duration", 4)
                beat = Beat(voice1)
                beat.duration = gpm.Duration()
                beat.duration.value = dur_val
                if bdata.get("dotted"):
                    beat.duration.isDotted = True
                notes_data = bdata.get("notes", [])
                if bdata.get("status") == "rest" or not notes_data:
                    beat.status = BeatStatus.rest
                    beat.notes = []
                else:
                    beat.status = BeatStatus.normal
                    dyn_str = bdata.get("dynamic", "mf")
                    vel = _DYN_STR_MAP.get(dyn_str, 79)
                    for nd in notes_data:
                        gnote = Note(beat)
                        gnote.value = nd.get("fret", 0)
                        gnote.string = nd.get("string", 1)
                        gnote.velocity = vel
                        gnote.type = NoteType.normal
                        beat.notes.append(gnote)
                voice1.beats.append(beat)

    song = gpm.Song()
    track = song.tracks[0]
    track.name = tracks_data[0].get("name", "Guitar")

    # 첫 번째 마디 헤더 설정
    ts0 = measures_data[0].get("timeSignature", {})
    first_mh = song.measureHeaders[0]
    first_mh.number = 1
    first_mh.timeSignature.numerator = ts0.get("num", 4)
    first_mh.timeSignature.denominator.value = ts0.get("den", 4)
    first_mh.keySignature = measures_data[0].get("keySignature", 0)
    marker_name = measures_data[0].get("sectionMarker")
    if marker_name:
        first_mh.marker = gpm.Marker(title=marker_name)
    _fill_snap(track.measures[0], measures_data[0])

    start = first_mh.start + first_mh.length
    for i, mdata in enumerate(measures_data[1:], start=2):
        ts = mdata.get("timeSignature", {})
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        mh.timeSignature.numerator = ts.get("num", 4)
        mh.timeSignature.denominator.value = ts.get("den", 4)
        mh.keySignature = mdata.get("keySignature", 0)
        marker_name = mdata.get("sectionMarker")
        if marker_name:
            mh.marker = gpm.Marker(title=marker_name)
        song.measureHeaders.append(mh)

        m = gpm.Measure(track, mh)
        _fill_snap(m, mdata)
        track.measures.append(m)
        start += mh.length

    guitarpro.write(song, out_path)
    return out_path
```

**주의:** 위 코드는 기존 `snapshot_to_gp5` 전체를 교체한다. 기존 함수에서 `_DUR_UNITS`, `_DUR_FILL_ORDER`, `_fill_snap` 등 내부 변수/함수 참조를 맞게 유지해야 한다.

- [ ] **Step 4: 테스트 통과 확인**

```
pytest tests/test_structure_edit.py -v
```

Expected: 모두 PASS

- [ ] **Step 5: 기존 테스트 전체 통과 확인**

```
pytest tests/ -q
```

Expected: 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/token_to_gp.py tests/test_structure_edit.py
git commit -m "feat: snapshot_to_gp5 v2 — keySignature, sectionMarker, voices fallback"
```

---

### Task 4: snapshot_to_gp5 v2 — 다중 트랙 + 튜닝

**Files:**
- Modify: `app/pipeline/token_to_gp.py` (함수 `snapshot_to_gp5`)
- Modify: `tests/test_structure_edit.py` (클래스 추가)

**Interfaces:**
- Consumes: `ScoreSnapshot.tracks` 배열 (1개 이상)
- Produces: GP5 파일에 여러 트랙, 각 트랙의 tuning 적용

- [ ] **Step 1: 실패하는 테스트 추가**

`tests/test_structure_edit.py`에 클래스 추가:

```python
class TestSnapshotV2MultiTrack:
    def test_two_tracks_written(self, tmp_path):
        """2개 트랙 스냅샷 → GP5에 2개 트랙."""
        snap = {
            "tracks": [
                {"name": "Guitar", "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "voices": [[{"duration": 4, "dotted": False, "status": "normal",
                                  "dynamic": "mf", "notes": [{"string": 1, "fret": 0}]}]],
                }]},
                {"name": "Bass", "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "voices": [[{"duration": 4, "dotted": False, "status": "normal",
                                  "dynamic": "mf", "notes": [{"string": 1, "fret": 3}]}]],
                }]},
            ]
        }
        path = str(tmp_path / "two_tracks.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert len(song.tracks) == 2
        assert song.tracks[1].name == "Bass"

    def test_drop_d_tuning_applied(self, tmp_path):
        """Drop D 튜닝 → 6번현 38(D2) 저장."""
        snap = {"tracks": [{
            "name": "Guitar",
            "tuning": [64, 59, 55, 50, 45, 38],
            "measures": [{"timeSignature": {"num": 4, "den": 4},
                          "voices": [[{"duration": 4, "dotted": False, "status": "rest",
                                        "dynamic": "mf", "notes": []}]]}],
        }]}
        path = str(tmp_path / "dropd.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        # GuitarString.value: string 1=index0(high E=64), string 6=index5(low=38)
        assert song.tracks[0].strings[5].value == 38

    def test_voice1_beats_written(self, tmp_path):
        """voices[1] beats → GP5 measure voice[1]에 음표 존재."""
        snap = {"tracks": [{"measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "voices": [
                [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf", "notes": [{"string": 1, "fret": 0}]}],
                [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf", "notes": [{"string": 2, "fret": 3}]}],
            ],
        }]}]}
        path = str(tmp_path / "voice1.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        # voice[1]에 음표 확인
        v1_notes = [n for b in song.tracks[0].measures[0].voices[1].beats
                    for n in b.notes if b.status == gpm.BeatStatus.normal]
        assert len(v1_notes) >= 1
```

- [ ] **Step 2: 테스트 실패 확인**

```
pytest tests/test_structure_edit.py::TestSnapshotV2MultiTrack -v
```

Expected: FAIL (다중 트랙, 튜닝 미반영)

- [ ] **Step 3: snapshot_to_gp5에 다중 트랙 지원 추가**

Task 3에서 작성한 `snapshot_to_gp5` 함수 끝에서 `guitarpro.write` 호출 직전에 추가 트랙 생성 로직을 넣는다.

`guitarpro.write(song, out_path)` 바로 앞, 기존 단일 트랙 설정 블록 뒤에:

```python
    # 첫 번째 트랙 튜닝 설정
    tuning_0 = tracks_data[0].get("tuning")
    if tuning_0 and len(tuning_0) == 6:
        for i, val in enumerate(tuning_0[:6]):
            track.strings[i].value = val

    # 추가 트랙 (tracks[1:])
    for ti, track_data in enumerate(tracks_data[1:], start=1):
        # 기본 Standard E 튜닝 적용
        default_tuning = [64, 59, 55, 50, 45, 40]
        tuning = track_data.get("tuning", default_tuning)
        if len(tuning) < 6:
            tuning = tuning + default_tuning[len(tuning):]
        new_strings = [gpm.GuitarString(number=j + 1, value=tuning[j]) for j in range(6)]

        new_track = gpm.Track(song, number=ti + 1, strings=new_strings)
        new_track.name = track_data.get("name", f"Track {ti + 1}")

        # 각 마디 헤더에 대해 Measure 생성 및 채우기
        track_measures_data = track_data.get("measures", [])
        for mi, mh in enumerate(song.measureHeaders):
            mdata = track_measures_data[mi] if mi < len(track_measures_data) else {}
            m = gpm.Measure(new_track, mh)
            _fill_snap(m, mdata)
            new_track.measures.append(m)

        song.tracks.append(new_track)

    guitarpro.write(song, out_path)
```

- [ ] **Step 4: 테스트 통과 확인**

```
pytest tests/test_structure_edit.py -v
```

Expected: 모두 PASS

- [ ] **Step 5: 전체 테스트 통과 확인**

```
pytest tests/ -q
```

Expected: 모두 PASS

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/token_to_gp.py tests/test_structure_edit.py
git commit -m "feat: snapshot_to_gp5 v2 — 다중 트랙 + 튜닝 설정"
```

---

### Task 5: editorStore 확장 + useSyncFile forceSync + api.getGP5Buffer

**Files:**
- Modify: `frontend/src/store/editorStore.ts`
- Modify: `frontend/src/lib/useSyncFile.ts`
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/__tests__/editorStore.v2.test.ts`

**Interfaces:**
- Consumes: `api.downloadGP5(fileId, filename)` (기존)
- Produces:
  - `editorStore`: `selectedTrackIndex`, `selectedMeasureIndex`, `activeVoice`, `gp5Buffer`, `setGp5Buffer`
  - `api.getGP5Buffer(fileId: string): Promise<ArrayBuffer>` — GP5 바이너리 fetch
  - `useSyncFile`: `forceSync()` — 즉시 POST /sync → GP5 재fetch → store.setGp5Buffer

- [ ] **Step 1: 실패하는 테스트 작성**

새 파일 `frontend/src/__tests__/editorStore.v2.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from 'vitest'
import { useEditorStore } from '../store/editorStore'

describe('editorStore v2 상태', () => {
  beforeEach(() => {
    useEditorStore.setState({
      selectedTrackIndex: 0,
      selectedMeasureIndex: 0,
      activeVoice: 0,
      gp5Buffer: null,
    })
  })

  it('selectedTrackIndex 초기값 0', () => {
    expect(useEditorStore.getState().selectedTrackIndex).toBe(0)
  })

  it('selectedMeasureIndex 초기값 0', () => {
    expect(useEditorStore.getState().selectedMeasureIndex).toBe(0)
  })

  it('activeVoice 초기값 0', () => {
    expect(useEditorStore.getState().activeVoice).toBe(0)
  })

  it('setGp5Buffer로 gp5Buffer 업데이트', () => {
    const buf = new ArrayBuffer(8)
    useEditorStore.getState().setGp5Buffer(buf)
    expect(useEditorStore.getState().gp5Buffer).toBe(buf)
  })

  it('selectedTrackIndex 변경', () => {
    useEditorStore.setState({ selectedTrackIndex: 2 })
    expect(useEditorStore.getState().selectedTrackIndex).toBe(2)
  })

  it('activeVoice 토글 0↔1', () => {
    useEditorStore.setState({ activeVoice: 1 })
    expect(useEditorStore.getState().activeVoice).toBe(1)
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/editorStore.v2.test.ts
```

Expected: FAIL (`selectedTrackIndex` 없음, `setGp5Buffer` 없음)

- [ ] **Step 3: editorStore.ts 수정**

기존 `frontend/src/store/editorStore.ts`에 상태와 액션 추가:

```typescript
// 기존 import 유지, 타입에 추가
import type { ScoreSnapshot, NotePosition, SaveStatus } from '../lib/scoreTypes'

interface EditorState {
  // 기존 필드들
  present: ScoreSnapshot | null
  past: ScoreSnapshot[]
  future: ScoreSnapshot[]
  selected: NotePosition | null
  fileId: string | null
  saveStatus: SaveStatus
  // v2 추가
  selectedTrackIndex: number
  selectedMeasureIndex: number
  activeVoice: 0 | 1
  gp5Buffer: ArrayBuffer | null

  // 기존 액션들
  pushSnapshot: (s: ScoreSnapshot) => void
  undo: () => ScoreSnapshot | null
  redo: () => ScoreSnapshot | null
  setSelected: (pos: NotePosition | null) => void
  setFileId: (id: string | null) => void
  setSaveStatus: (s: SaveStatus) => void
  // v2 추가 액션
  setGp5Buffer: (buf: ArrayBuffer | null) => void
}
```

`create()` 콜 내 초기값에 추가:

```typescript
  selectedTrackIndex: 0,
  selectedMeasureIndex: 0,
  activeVoice: 0 as 0 | 1,
  gp5Buffer: null,
```

액션 추가:

```typescript
  setGp5Buffer: (buf) => set({ gp5Buffer: buf }),
```

- [ ] **Step 4: api.ts에 getGP5Buffer 추가**

`frontend/src/lib/api.ts`의 `api` 객체에 추가:

```typescript
  async getGP5Buffer(fileId: string): Promise<ArrayBuffer> {
    const res = await fetch(`/files/${fileId}/download`, { headers: authHeaders() })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.arrayBuffer()
  },
```

- [ ] **Step 5: useSyncFile.ts에 forceSync 추가**

`frontend/src/lib/useSyncFile.ts` 수정:

```typescript
import { api } from './api'
import { useEditorStore } from '../store/editorStore'
// ... 기존 import 유지

export function useSyncFile(fileId: string | null, snapshot: ScoreSnapshot | null) {
  // 기존 debounce 로직 유지
  // ...

  const forceSync = useCallback(async () => {
    if (!fileId || !snapshot) return
    try {
      useEditorStore.getState().setSaveStatus('saving')
      await api.syncFile(fileId, snapshot)
      const buf = await api.getGP5Buffer(fileId)
      useEditorStore.getState().setGp5Buffer(buf)
      useEditorStore.getState().setSaveStatus('saved')
    } catch {
      useEditorStore.getState().setSaveStatus('error')
    }
  }, [fileId, snapshot])

  return { syncNow, forceSync, saveStatus }
}
```

- [ ] **Step 6: 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/editorStore.v2.test.ts
```

Expected: 모두 PASS

- [ ] **Step 7: 전체 프론트 테스트 통과 확인**

```
cd frontend && npx vitest run
```

Expected: 모두 PASS

- [ ] **Step 8: 커밋**

```bash
git add frontend/src/store/editorStore.ts \
        frontend/src/lib/useSyncFile.ts \
        frontend/src/lib/api.ts \
        frontend/src/__tests__/editorStore.v2.test.ts
git commit -m "feat: editorStore v2 + useSyncFile forceSync + api.getGP5Buffer"
```

---

### Task 6: StructurePanel UI

**Files:**
- Create: `frontend/src/components/Editor/StructurePanel.tsx`
- Modify: `frontend/src/components/Editor/ScoreViewer.tsx`
- Test: `frontend/src/__tests__/StructurePanel.test.tsx`

**Interfaces:**
- Consumes:
  - `applyStructuralEdit(snapshot, edit): ScoreSnapshot` (Task 2)
  - `useEditorStore`: `present`, `selectedMeasureIndex`, `pushSnapshot`, `setGp5Buffer`
  - `useSyncFile`: `forceSync` (Task 5)
- Produces: `<StructurePanel />` — 마디 목록, 추가/삭제/이동/박자표/조표/섹션마커 UI

- [ ] **Step 1: 실패하는 테스트 작성**

새 파일 `frontend/src/__tests__/StructurePanel.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from '../lib/scoreTypes'

vi.mock('../lib/api', () => ({
  api: {
    syncFile: vi.fn().mockResolvedValue({ ok: true }),
    getGP5Buffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
  },
}))

const REST = { duration: 4 as const, dotted: false, status: 'rest' as const, notes: [] }
const snap2: ScoreSnapshot = {
  tracks: [{
    measures: [
      { timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] },
      { timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] },
    ],
  }],
}

import StructurePanel from '../components/Editor/StructurePanel'

describe('StructurePanel', () => {
  beforeEach(() => {
    useEditorStore.setState({
      present: snap2,
      selectedMeasureIndex: 0,
      fileId: 'f1',
    } as any)
  })

  it('마디 목록 렌더링', () => {
    render(<StructurePanel />)
    expect(screen.getByText(/마디 1/)).toBeInTheDocument()
    expect(screen.getByText(/마디 2/)).toBeInTheDocument()
  })

  it('마디 추가 버튼 존재', () => {
    render(<StructurePanel />)
    expect(screen.getByRole('button', { name: /마디 추가/i })).toBeInTheDocument()
  })

  it('마디 삭제 버튼 존재', () => {
    render(<StructurePanel />)
    expect(screen.getAllByRole('button', { name: /삭제/i }).length).toBeGreaterThan(0)
  })

  it('섹션 마커 입력 필드 존재', () => {
    render(<StructurePanel />)
    expect(screen.getByPlaceholderText(/섹션/i)).toBeInTheDocument()
  })

  it('박자표 num/den 입력 존재', () => {
    render(<StructurePanel />)
    // 박자 numerator input
    const inputs = screen.getAllByRole('spinbutton')
    expect(inputs.length).toBeGreaterThanOrEqual(2)
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/StructurePanel.test.tsx
```

Expected: FAIL (StructurePanel not found)

- [ ] **Step 3: StructurePanel.tsx 구현**

```tsx
// frontend/src/components/Editor/StructurePanel.tsx
import { useState } from 'react'
import { useEditorStore } from '../../store/editorStore'
import { applyStructuralEdit } from '../../lib/structuralEdit'
import { api } from '../../lib/api'

const KEY_SIG_LABELS: Record<number, string> = {
  '-7': 'Cb', '-6': 'Gb', '-5': 'Db', '-4': 'Ab',
  '-3': 'Eb', '-2': 'Bb', '-1': 'F',
  '0': 'C', '1': 'G', '2': 'D', '3': 'A',
  '4': 'E', '5': 'B', '6': 'F#', '7': 'C#',
}

export default function StructurePanel() {
  const { present, selectedMeasureIndex, fileId, pushSnapshot, setGp5Buffer, setSaveStatus } =
    useEditorStore()
  const [busy, setBusy] = useState(false)

  if (!present) return null

  const measures = present.tracks[0]?.measures ?? []
  const selected = measures[selectedMeasureIndex]

  async function applyAndSync(edit: Parameters<typeof applyStructuralEdit>[1]) {
    if (!present || !fileId) return
    const next = applyStructuralEdit(present, edit)
    pushSnapshot(next)
    setBusy(true)
    try {
      setSaveStatus('saving')
      await api.syncFile(fileId, next)
      const buf = await api.getGP5Buffer(fileId)
      setGp5Buffer(buf)
      setSaveStatus('saved')
    } catch {
      setSaveStatus('error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <strong>마디 구조</strong>

      {/* 마디 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
        {measures.map((m, i) => (
          <div
            key={i}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: i === selectedMeasureIndex ? '#ddf' : undefined,
              cursor: 'pointer', padding: '2px 4px',
            }}
            onClick={() => useEditorStore.setState({ selectedMeasureIndex: i })}
          >
            <span style={{ flex: 1, fontSize: 12 }}>
              마디 {i + 1}
              {m.sectionMarker ? ` [${m.sectionMarker}]` : ''}
            </span>
            <button
              style={{ fontSize: 10 }}
              disabled={busy}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'moveMeasure', from: i, to: i - 1 }) }}
            >↑</button>
            <button
              style={{ fontSize: 10 }}
              disabled={busy}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'moveMeasure', from: i, to: i + 1 }) }}
            >↓</button>
            <button
              style={{ fontSize: 10, color: 'red' }}
              disabled={busy || measures.length <= 1}
              aria-label={`마디 ${i + 1} 삭제`}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'deleteMeasure', index: i }) }}
            >삭제</button>
          </div>
        ))}
      </div>

      <button
        disabled={busy}
        onClick={() => applyAndSync({ type: 'addMeasure', afterIndex: selectedMeasureIndex })}
      >
        마디 추가
      </button>

      {selected && (
        <div style={{ borderTop: '1px solid #ddd', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <strong style={{ fontSize: 12 }}>마디 {selectedMeasureIndex + 1} 속성</strong>

          {/* 박자표 */}
          <label style={{ fontSize: 12 }}>
            박자표:
            <input
              type="number" min={1} max={16} style={{ width: 40, marginLeft: 4 }}
              value={selected.timeSignature.num}
              onChange={e => applyAndSync({
                type: 'setTimeSignature',
                measureIndex: selectedMeasureIndex,
                num: Number(e.target.value),
                den: selected.timeSignature.den,
              })}
            /> /
            <select
              style={{ marginLeft: 4 }}
              value={selected.timeSignature.den}
              onChange={e => applyAndSync({
                type: 'setTimeSignature',
                measureIndex: selectedMeasureIndex,
                num: selected.timeSignature.num,
                den: Number(e.target.value),
              })}
            >
              {[2, 4, 8, 16].map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </label>

          {/* 조표 */}
          <label style={{ fontSize: 12 }}>
            조표:
            <select
              style={{ marginLeft: 4 }}
              value={selected.keySignature ?? 0}
              onChange={e => applyAndSync({
                type: 'setKeySignature',
                measureIndex: selectedMeasureIndex,
                key: Number(e.target.value),
              })}
            >
              {Object.entries(KEY_SIG_LABELS).map(([v, label]) => (
                <option key={v} value={v}>{label}</option>
              ))}
            </select>
          </label>

          {/* 섹션 마커 */}
          <label style={{ fontSize: 12 }}>
            섹션:
            <input
              type="text"
              placeholder="섹션 이름 (예: Intro)"
              style={{ marginLeft: 4, width: 120 }}
              value={selected.sectionMarker ?? ''}
              onChange={e => applyAndSync({
                type: 'setSectionMarker',
                measureIndex: selectedMeasureIndex,
                name: e.target.value || null,
              })}
            />
          </label>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: ScoreViewer.tsx에 StructurePanel 통합**

`ScoreViewer.tsx` import에 추가:
```typescript
import StructurePanel from './StructurePanel'
```

기존 3컬럼 레이아웃 우측 패널(EditPanel이 있는 쪽)에 StructurePanel 추가:

```tsx
{/* 기존 우측 패널 */}
<aside style={{ width: 220, borderLeft: '1px solid #ddd', overflow: 'auto' }}>
  <StructurePanel />
  <hr />
  <EditPanel /* 기존 props */ />
</aside>
```

- [ ] **Step 5: 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/StructurePanel.test.tsx
```

Expected: 모두 PASS

- [ ] **Step 6: 전체 테스트 통과 확인**

```
cd frontend && npx vitest run
```

Expected: 모두 PASS

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/components/Editor/StructurePanel.tsx \
        frontend/src/components/Editor/ScoreViewer.tsx \
        frontend/src/__tests__/StructurePanel.test.tsx
git commit -m "feat: StructurePanel — 마디 추가/삭제/이동/박자표/조표/섹션마커 UI"
```

---

### Task 7: TrackPanel UI + ScoreViewer Voice 토글

**Files:**
- Create: `frontend/src/components/Editor/TrackPanel.tsx`
- Modify: `frontend/src/components/Editor/ScoreViewer.tsx`
- Test: `frontend/src/__tests__/TrackPanel.test.tsx`

**Interfaces:**
- Consumes:
  - `applyStructuralEdit` (Task 2): `addTrack`, `deleteTrack`, `setTrackName`, `setTuning`, `setCapo`
  - `useEditorStore`: `present`, `selectedTrackIndex`, `activeVoice`
- Produces: `<TrackPanel />` — 트랙 목록, 이름/튜닝/Capo 편집, Voice 토글

- [ ] **Step 1: 실패하는 테스트 작성**

새 파일 `frontend/src/__tests__/TrackPanel.test.tsx`:

```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { useEditorStore } from '../store/editorStore'
import type { ScoreSnapshot } from '../lib/scoreTypes'

vi.mock('../lib/api', () => ({
  api: {
    syncFile: vi.fn().mockResolvedValue({ ok: true }),
    getGP5Buffer: vi.fn().mockResolvedValue(new ArrayBuffer(8)),
  },
}))

const REST = { duration: 4 as const, dotted: false, status: 'rest' as const, notes: [] }
const snap1: ScoreSnapshot = {
  tracks: [{
    name: 'Guitar',
    tuning: [64, 59, 55, 50, 45, 40],
    capo: 0,
    measures: [{ timeSignature: { num: 4, den: 4 }, voices: [[{ ...REST }]], beats: [{ ...REST }] }],
  }],
}

import TrackPanel from '../components/Editor/TrackPanel'

describe('TrackPanel', () => {
  beforeEach(() => {
    useEditorStore.setState({ present: snap1, selectedTrackIndex: 0, activeVoice: 0, fileId: 'f1' } as any)
  })

  it('트랙 목록 렌더링', () => {
    render(<TrackPanel />)
    expect(screen.getByText(/Guitar/)).toBeInTheDocument()
  })

  it('트랙 추가 버튼 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByRole('button', { name: /트랙 추가/i })).toBeInTheDocument()
  })

  it('튜닝 프리셋 셀렉트 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByRole('combobox', { name: /튜닝/i })).toBeInTheDocument()
  })

  it('Capo 입력 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByLabelText(/Capo/i)).toBeInTheDocument()
  })

  it('Voice 1/2 토글 버튼 존재', () => {
    render(<TrackPanel />)
    expect(screen.getByRole('button', { name: /Voice 1/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Voice 2/i })).toBeInTheDocument()
  })

  it('Voice 2 클릭 → activeVoice=1 설정', async () => {
    render(<TrackPanel />)
    await userEvent.click(screen.getByRole('button', { name: /Voice 2/i }))
    expect(useEditorStore.getState().activeVoice).toBe(1)
  })
})
```

- [ ] **Step 2: 테스트 실패 확인**

```
cd frontend && npx vitest run src/__tests__/TrackPanel.test.tsx
```

Expected: FAIL (TrackPanel not found)

- [ ] **Step 3: TrackPanel.tsx 구현**

```tsx
// frontend/src/components/Editor/TrackPanel.tsx
import { useState } from 'react'
import { useEditorStore } from '../../store/editorStore'
import { applyStructuralEdit } from '../../lib/structuralEdit'
import { api } from '../../lib/api'

const TUNING_PRESETS: Record<string, number[]> = {
  'Standard E': [64, 59, 55, 50, 45, 40],
  'Drop D':     [64, 59, 55, 50, 45, 38],
  'Open G':     [62, 59, 55, 50, 47, 38],
  'DADGAD':     [62, 57, 55, 50, 45, 38],
}

function detectPreset(tuning: number[] | undefined): string {
  if (!tuning) return 'Standard E'
  for (const [name, vals] of Object.entries(TUNING_PRESETS)) {
    if (vals.every((v, i) => v === tuning[i])) return name
  }
  return 'Custom'
}

export default function TrackPanel() {
  const { present, selectedTrackIndex, activeVoice, fileId, pushSnapshot, setGp5Buffer, setSaveStatus } =
    useEditorStore()
  const [busy, setBusy] = useState(false)

  if (!present) return null

  const tracks = present.tracks
  const track = tracks[selectedTrackIndex]

  async function applyAndSync(edit: Parameters<typeof applyStructuralEdit>[1]) {
    if (!present || !fileId) return
    const next = applyStructuralEdit(present, edit)
    pushSnapshot(next)
    setBusy(true)
    try {
      setSaveStatus('saving')
      await api.syncFile(fileId, next)
      const buf = await api.getGP5Buffer(fileId)
      setGp5Buffer(buf)
      setSaveStatus('saved')
    } catch {
      setSaveStatus('error')
    } finally {
      setBusy(false)
    }
  }

  const currentPreset = detectPreset(track?.tuning)

  return (
    <div style={{ padding: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
      <strong>트랙</strong>

      {/* 트랙 목록 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        {tracks.map((t, i) => (
          <div
            key={i}
            style={{
              display: 'flex', alignItems: 'center', gap: 4,
              background: i === selectedTrackIndex ? '#ddf' : undefined,
              cursor: 'pointer', padding: '2px 4px',
            }}
            onClick={() => useEditorStore.setState({ selectedTrackIndex: i })}
          >
            <span style={{ flex: 1, fontSize: 12 }}>🎸 {t.name ?? `Track ${i + 1}`}</span>
            <button
              style={{ fontSize: 10, color: 'red' }}
              disabled={busy || tracks.length <= 1}
              onClick={(e) => { e.stopPropagation(); applyAndSync({ type: 'deleteTrack', trackIndex: i }) }}
            >×</button>
          </div>
        ))}
      </div>

      <button disabled={busy} onClick={() => applyAndSync({ type: 'addTrack' })}>
        트랙 추가
      </button>

      {track && (
        <div style={{ borderTop: '1px solid #ddd', paddingTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <strong style={{ fontSize: 12 }}>트랙 {selectedTrackIndex + 1} 속성</strong>

          {/* 트랙 이름 */}
          <label style={{ fontSize: 12 }}>
            이름:
            <input
              type="text"
              style={{ marginLeft: 4, width: 100 }}
              value={track.name ?? ''}
              onChange={e => applyAndSync({ type: 'setTrackName', trackIndex: selectedTrackIndex, name: e.target.value })}
            />
          </label>

          {/* 튜닝 프리셋 */}
          <label aria-label="튜닝" style={{ fontSize: 12 }}>
            튜닝:
            <select
              aria-label="튜닝"
              style={{ marginLeft: 4 }}
              value={currentPreset === 'Custom' ? 'Custom' : currentPreset}
              onChange={e => {
                const preset = TUNING_PRESETS[e.target.value]
                if (preset) applyAndSync({ type: 'setTuning', trackIndex: selectedTrackIndex, tuning: preset })
              }}
            >
              {Object.keys(TUNING_PRESETS).map(name => (
                <option key={name} value={name}>{name}</option>
              ))}
              {currentPreset === 'Custom' && <option value="Custom">Custom</option>}
            </select>
          </label>

          {/* Capo */}
          <label aria-label="Capo" style={{ fontSize: 12 }}>
            Capo:
            <input
              aria-label="Capo"
              type="number" min={0} max={12}
              style={{ width: 48, marginLeft: 4 }}
              value={track.capo ?? 0}
              onChange={e => applyAndSync({ type: 'setCapo', trackIndex: selectedTrackIndex, capo: Number(e.target.value) })}
            />
          </label>

          {/* Voice 토글 */}
          <div style={{ display: 'flex', gap: 4 }}>
            <button
              style={{ fontWeight: activeVoice === 0 ? 'bold' : undefined }}
              onClick={() => useEditorStore.setState({ activeVoice: 0 })}
            >Voice 1</button>
            <button
              style={{ fontWeight: activeVoice === 1 ? 'bold' : undefined }}
              onClick={() => useEditorStore.setState({ activeVoice: 1 })}
            >Voice 2</button>
          </div>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: ScoreViewer.tsx에 TrackPanel 통합**

`ScoreViewer.tsx` import에 추가:
```typescript
import TrackPanel from './TrackPanel'
```

기존 좌측 사이드바에 TrackPanel 탭 추가 (FileList와 탭 전환):

```tsx
const [leftTab, setLeftTab] = useState<'files' | 'tracks'>('files')

// 좌측 패널:
<aside style={{ width: 200, borderRight: '1px solid #ddd', overflow: 'auto' }}>
  <div style={{ display: 'flex', borderBottom: '1px solid #ddd' }}>
    <button
      style={{ flex: 1, fontWeight: leftTab === 'files' ? 'bold' : undefined }}
      onClick={() => setLeftTab('files')}
    >파일</button>
    <button
      style={{ flex: 1, fontWeight: leftTab === 'tracks' ? 'bold' : undefined }}
      onClick={() => setLeftTab('tracks')}
    >트랙</button>
  </div>
  {leftTab === 'files' ? <FileList /> : <TrackPanel />}
</aside>
```

또한 gp5Buffer가 변경될 때 alphaTab 리로드하는 useEffect 추가:

```typescript
const gp5Buffer = useEditorStore(s => s.gp5Buffer)

useEffect(() => {
  if (!gp5Buffer || !apiRef.current) return
  apiRef.current.load(gp5Buffer)
}, [gp5Buffer])
```

- [ ] **Step 5: 테스트 통과 확인**

```
cd frontend && npx vitest run src/__tests__/TrackPanel.test.tsx
```

Expected: 모두 PASS

- [ ] **Step 6: 전체 테스트 통과 확인**

```
cd frontend && npx vitest run && python -m pytest tests/ -q
```

Expected: 모두 PASS

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/components/Editor/TrackPanel.tsx \
        frontend/src/components/Editor/ScoreViewer.tsx \
        frontend/src/__tests__/TrackPanel.test.tsx
git commit -m "feat: TrackPanel — 트랙/튜닝/Capo/Voice 편집 UI + gp5Buffer 리로드"
```

---

## 범위 외 (Phase 3 이후)

- capo GP5 바이너리 직접 패치 (PyGuitarPro 미지원)
- Voice 3/4 (GP5 4성부)
- 드래그앤드롭 마디 이동
- 박자표 변경 시 기존 비트 자동 재배치
