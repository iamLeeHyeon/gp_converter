# Phase 2 구조 편집기 설계 스펙

**날짜:** 2026-06-30
**연관 스펙:** `2026-06-29-web-editor-design.md` (Phase 2 섹션)

---

## 목표

Phase 1이 음표 레벨(fret, duration, effect)을 편집한다면, Phase 2는 악보 구조를 편집한다:

| 기능 | 설명 |
|------|------|
| 마디 추가/삭제/이동 | 선택한 마디 앞/뒤에 삽입, 삭제, 순서 이동 |
| 박자표 변경 | 마디별 time signature (3/4, 6/8 등) |
| 조표 변경 | 마디별 key signature (-7 ~ 7, 플랫/샾) |
| 섹션 마커 | 마디에 이름 태그 (Intro, Verse, Chorus 등) |
| 튜닝 변경 | 트랙별 개방현 MIDI 값 (Standard, Drop D, Open G 등) |
| Capo 설정 | 트랙별 카포 (0-12) |
| 트랙 추가/삭제 | 다중 트랙 (기타, 베이스 등) |
| 다성부(Voice 1/2) | 마디 내 2개 목소리 편집 |

---

## 아키텍처 결정

### 구조 편집 = Snapshot-first

Phase 1 음표 편집은 alphaTab 모델 인플레이스 수정 후 직렬화한다.
Phase 2 구조 편집은 순서를 뒤집는다:

```
[UI 액션] → ScoreSnapshot 직접 수정 → POST /sync → 서버 GP5 재생성 → alphaTab 리로드
```

이유: alphaTab의 마디 추가/삭제 API가 공개되지 않아 불안정. Snapshot을 조작 후 서버에서 재생성하는 것이 신뢰도 높다. 구조 변경은 빈도가 낮아 리로드 비용 허용 가능.

### 즉시 동기화

구조 편집은 3초 debounce를 건너뛰고 `forceSync()` 즉시 호출.
음표 편집 3초 debounce는 그대로 유지.

---

## ScoreSnapshot 스키마 v2

### 변경 전 (v1)

```typescript
interface ScoreSnapshot {
  tracks: Array<{ measures: SnapshotMeasure[] }>
}

interface SnapshotMeasure {
  timeSignature: { num: number; den: number }
  beats: SnapshotBeat[]
}
```

### 변경 후 (v2)

```typescript
interface ScoreSnapshot {
  tracks: SnapshotTrack[]
}

interface SnapshotTrack {
  name?: string              // 트랙 이름 (기본값: "Guitar")
  capo?: number              // 카포 프렛 (0-12, 기본값: 0)
  tuning?: number[]          // 개방현 MIDI 값 6개 [string1..string6]
                             // 기본: [64,59,55,50,45,40] (Standard E)
  measures: SnapshotMeasure[]
}

interface SnapshotMeasure {
  timeSignature: { num: number; den: number }
  keySignature?: number      // -7(7플랫)~7(7샾), 0=C장조 (기본값: 0)
  sectionMarker?: string     // 섹션 이름 ("Intro", "Verse" 등)
  voices: SnapshotBeat[][]   // voices[0]=Voice1, voices[1]=Voice2
  // beats는 voices[0]의 alias (하위 호환)
}
```

**하위 호환:** scoreSerializer가 `voices[0]`를 `beats`로도 출력한다. snapshot_to_gp5는 `voices` 없으면 `beats`를 fallback으로 읽는다.

---

## 백엔드 변경

### snapshot_to_gp5 확장

**파일:** `app/pipeline/token_to_gp.py` (함수 `snapshot_to_gp5`)

| 추가 기능 | 구현 방법 |
|-----------|-----------|
| 다중 트랙 | tracks 배열 루프 → Track 객체 생성 |
| 튜닝 | `track.strings[i].value = tuning[i]` |
| Capo | `track.capo = capo` |
| 조표 | `measureHeader.keySignature = keySignature` |
| 섹션 마커 | `measureHeader.marker = gpm.Marker(title=name, color=gpm.Color.red())` |
| 다성부 | voice[1] beats 추가 (`measure.voices[1]`) |

### 에러 처리

- 튜닝 배열 길이 != 6 → `ValueError("tuning must have 6 values")`
- capo out of range → clamp to 0-12 (경고 로그)
- keySignature out of range → clamp to -7~7

---

## 프론트엔드 변경

### 새 컴포넌트

#### `StructurePanel.tsx`
위치: `frontend/src/components/Editor/StructurePanel.tsx`

```
[마디 목록]
┌──────────────────────┐
│ Intro  [4/4] [×] [↑↓]│
│ Verse  [4/4] [×] [↑↓]│
│ [+ 마디 추가]          │
└──────────────────────┘
[선택된 마디 속성]
 박자표: [4] / [4]
 조표: [C장조 ▼]
 섹션: [Intro___________]
```

- 마디 선택: editorStore의 `selectedMeasureIndex` 사용
- 추가: 선택한 마디 다음에 빈 마디 삽입 (박자표 상속)
- 삭제: 선택한 마디 제거 (마디 1개 남을 때 비활성화)
- 이동: 드래그 대신 ↑↓ 버튼으로 단순화

#### `TrackPanel.tsx`
위치: `frontend/src/components/Editor/TrackPanel.tsx`

```
[트랙 목록]
┌──────────────────────┐
│ 🎸 Guitar  [×]       │
│ 🎸 Bass    [×]       │
│ [+ 트랙 추가]          │
└──────────────────────┘
[선택된 트랙 속성]
 이름: [Guitar__________]
 튜닝: [Standard E ▼]
 Capo:  [0 ▼]
```

튜닝 프리셋:
```typescript
const TUNING_PRESETS = {
  'Standard E':  [64, 59, 55, 50, 45, 40],
  'Drop D':      [64, 59, 55, 50, 45, 38],
  'Open G':      [62, 59, 55, 50, 47, 38],
  'DADGAD':      [62, 57, 55, 50, 45, 38],
  'Custom':      null,  // 직접 입력
}
```

### scoreApplier 확장

`EditPayload`에 구조 편집 타입 추가:

```typescript
type StructuralEdit =
  | { type: 'addMeasure'; afterIndex: number }
  | { type: 'deleteMeasure'; index: number }
  | { type: 'moveMeasure'; from: number; to: number }
  | { type: 'setTimeSignature'; measureIndex: number; num: number; den: number }
  | { type: 'setKeySignature'; measureIndex: number; key: number }
  | { type: 'setSectionMarker'; measureIndex: number; name: string | null }
  | { type: 'setVoice'; voiceIndex: 0 | 1 }
  | { type: 'addTrack' }
  | { type: 'deleteTrack'; trackIndex: number }
  | { type: 'setTrackName'; trackIndex: number; name: string }
  | { type: 'setTuning'; trackIndex: number; tuning: number[] }
  | { type: 'setCapo'; trackIndex: number; capo: number }
```

구조 편집은 alphaTab Score가 아닌 ScoreSnapshot에 직접 적용한다.
함수 시그니처: `applyStructuralEdit(snapshot: ScoreSnapshot, edit: StructuralEdit): ScoreSnapshot`

### scoreSerializer 확장

`serializeScore()`가 v2 schema 출력:
- `track.capo`, `track.strings` → `capo`, `tuning`
- `bar.masterBar.keySignature` → `keySignature`
- `bar.masterBar.section` → `sectionMarker`
- `bar.voices` 배열 → `voices`

### editorStore 확장

```typescript
// 추가 상태 (초기값)
selectedTrackIndex: number       // 현재 선택 트랙 (초기값: 0)
selectedMeasureIndex: number     // 구조 패널 선택 마디 (초기값: 0)
activeVoice: 0 | 1               // 현재 편집 목소리 (초기값: 0)
gp5Buffer: ArrayBuffer | null    // forceSync 후 리로드용 (초기값: null)
```

### useSyncFile 확장

```typescript
// 기존
const { syncNow, saveStatus } = useSyncFile(fileId, snapshot)

// 추가
const { syncNow, forceSync, saveStatus } = useSyncFile(fileId, snapshot)
// forceSync(): debounce 없이 즉시 POST /sync → 완료 후 api.getGP5Buffer(fileId) 재호출
//              → ScoreViewer에 새 gp5Buffer prop 전달 → alphaTab.load() 재실행
```

**alphaTab 리로드 흐름:**
```
forceSync() 호출
  → POST /sync 완료 (서버 GP5 재생성)
  → GET /files/{id}/download 로 새 GP5 바이너리 fetch
  → editorStore.setGp5Buffer(newBuffer)
  → ScoreViewer useEffect [gp5Buffer] 재실행
  → api.load(newBuffer) 호출
```

### App.tsx / ScoreViewer 레이아웃

```
┌─────────────────────────────────────────────────┐
│ [FileList] [UploadButton]          [내보내기 메뉴] │  ← 상단바
├──────────┬──────────────────────┬───────────────┤
│ Track    │                      │ Structure     │
│ Panel    │    ScoreViewer       │ Panel         │
│          │    (alphaTab)        │               │
│          │                      │ Edit Panel    │
└──────────┴──────────────────────┴───────────────┘
```

TrackPanel은 기존 좌측 FileList와 탭 전환 방식으로 공존.

---

## API 변경 없음

`POST /files/{id}/sync`는 ScoreSnapshot v2를 그대로 수용한다.
백엔드 `snapshot_to_gp5`가 v2 필드를 읽도록 확장하기만 하면 됨.

---

## 테스트 전략

### 백엔드 (pytest)
- `snapshot_to_gp5` 단위 테스트: 각 새 필드 (튜닝, capo, keySignature, sectionMarker, 다중 트랙, 다성부)
- `test_edit.py`에 구조 편집 시나리오 추가 (POST /sync with v2 snapshot)

### 프론트엔드 (vitest)
- `applyStructuralEdit` 단위 테스트 (각 StructuralEdit 타입)
- `serializeScore` v2 출력 검증
- `StructurePanel`, `TrackPanel` 컴포넌트 테스트 (버튼 클릭 → edit 발생)
- `editorStore` 새 상태 (selectedTrackIndex, activeVoice) 테스트

---

## 구현 순서 (Task 우선순위)

1. **ScoreSnapshot v2 타입 + serializer** (프론트, 하위 호환)
2. **applyStructuralEdit 함수** (프론트, 스냅샷 조작)
3. **snapshot_to_gp5 v2 지원** (백엔드: 마디 구조, 박자표, 조표, 마커)
4. **snapshot_to_gp5 트랙/튜닝/Capo/다성부** (백엔드: 트랙 레벨)
5. **StructurePanel UI** (프론트)
6. **TrackPanel UI + editorStore 확장** (프론트)
7. **ScoreViewer forceSync + 리로드** (프론트)

---

## 범위 외 (Phase 3 이후)

- 드래그앤드롭 마디 이동 (↑↓ 버튼으로 대체)
- Capo 0 이외 실제 음높이 변환 (alphaTab 렌더링 의존)
- Voice 3/4 (GP5 4성부 전체 지원)
- 조표별 임시표 자동 처리 (alphaTab 렌더링이 처리)
