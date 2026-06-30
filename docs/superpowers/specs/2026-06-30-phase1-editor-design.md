# GP Converter Phase 1 — 기본 편집기 설계

## 개요

alphaTab으로 렌더링된 악보에서 음표를 클릭해 선택하고, 사이드 패널에서 프렛·지속시간·이펙트·다이나믹을 수정한다. 편집 내용은 Undo/Redo 히스토리에 쌓이고, 3초 debounce 후 서버에 자동저장된다.

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 악보 편집 | alphaTab 1.x `api.score` 직접 수정 + `api.render()` 재호출 |
| 상태 관리 | Zustand — editorStore (선택 상태 + 스냅샷 히스토리) |
| 서버 동기화 | 자체 ScoreSnapshot JSON → POST /files/{id}/sync |
| GP5 재생성 | PyGuitarPro (기존 token_to_gp.py 확장) |

---

## 레이아웃

```
┌─ 사이드바(260px) ─┬─ 악보 영역 (flex:1) ─┬─ EditPanel(280px) ─┐
│ GP Converter      │ alphaTab 렌더링       │ 음표 선택 없음:     │
│ UploadButton      │ [재생] [←][→]         │  "음표를 클릭하세요" │
│ ─────────────     │                       │                     │
│ 내 파일           │  ♩ ♪ ♫ ♩ ♪ ♫        │ 음표 선택 시:       │
│ FileList          │  1─2─3─4─5─6          │  프렛: [5]          │
└───────────────────┴───────────────────────┴─────────────────────┘
```

EditPanel은 `width` prop으로 추후 하단 드로어 전환 가능하도록 CSS 분리.

---

## 데이터 흐름

```
클릭 → api.noteMouseDown → editorStore.selectedBeat/Note
  ↓
EditPanel 값 변경
  ↓
scoreApplier.applyEdit(api.score, edit) → api.score 직접 수정
  ↓
editorStore.pushSnapshot(serializeScore(api.score))  ← Undo 스택
  ↓
api.render()  ← 즉각 렌더링
  ↓
debounce 3초 → api.syncFile(fileId, snapshot)
  ↓
서버 JSON → PyGuitarPro → GP5 덮어씀
```

---

## ScoreSnapshot JSON 포맷

```typescript
interface ScoreSnapshot {
  tracks: {
    measures: {
      timeSignature: { num: number; den: number }
      beats: {
        duration: 1 | 2 | 4 | 8 | 16 | 32
        dotted: boolean
        status: 'normal' | 'rest'
        notes: {
          string: number    // 1-6
          fret: number      // 0-24
          effect?: 'hammer-on' | 'pull-off'
                  | 'slide-shift' | 'slide-legato'
                  | 'slide-in-above' | 'slide-out-below'
                  | 'mute' | 'ghost' | 'harmonic'
          velocity?: number // 15-127
        }[]
        strumDown?: boolean
        dynamic?: 'ppp' | 'pp' | 'p' | 'mp' | 'mf' | 'f' | 'ff' | 'fff'
      }[]
    }[]
  }[]
}
```

---

## Undo/Redo

- 방식: **스냅샷** — 편집마다 ScoreSnapshot 전체 복사 → Zustand 히스토리 스택 (최대 100단계)
- `editorStore` 구조: `{ past: ScoreSnapshot[], present: ScoreSnapshot, future: ScoreSnapshot[] }`
- `pushSnapshot(snap)` → `past.push(present)`, `present = snap`, `future = []`
- `undo()` → `future.push(present)`, `present = past.pop()`, Score 적용 + 렌더링
- `redo()` → `past.push(present)`, `present = future.pop()`, Score 적용 + 렌더링

---

## 키보드 단축키

| 단축키 | 동작 |
|--------|------|
| Cmd/Ctrl+Z | Undo |
| Cmd/Ctrl+Shift+Z / Cmd/Ctrl+Y | Redo |
| Delete | 선택 음표 삭제 |
| ←/→ | 이전/다음 비트로 이동 |

---

## EditPanel 편집 기능

| 항목 | UI | 값 범위 |
|------|-----|---------|
| 프렛 | 숫자 입력 | 0-24 |
| 지속시간 | 버튼 그룹 | 1/2/4/8/16/32 |
| 점음표 | 토글 버튼 | on/off |
| 이펙트 | 드롭다운 또는 버튼 | hammer-on, pull-off, slide-shift, slide-legato, slide-in-above, slide-out-below, mute, ghost, harmonic |
| 스트럼 | ▼▲ 버튼 | down/up/none |
| 다이나믹 | 버튼 그룹 | ppp~fff |
| 음표 추가 | [+] 버튼 | 빈 비트에 기본 음표 삽입 |
| 음표 삭제 | [×] 버튼 | 선택 음표 제거 |

---

## 서버 sync 엔드포인트

```
POST /files/{file_id}/sync
Authorization: Bearer <access_token>
Content-Type: application/json
Body: ScoreSnapshot

응답:
  200 OK
  403 타인 파일
  404 파일 없음
  422 JSON 파싱 실패
```

서버 처리: `ScoreSnapshot → snapshot_to_gp5() → File.gp5_path 덮어씀`

---

## 파일 목록

### Frontend (신규)

| 파일 | 역할 |
|------|------|
| `src/components/Editor/EditPanel.tsx` | 프렛/duration/이펙트/다이나믹/스트럼 편집 UI |
| `src/store/editorStore.ts` | 선택 상태 + 스냅샷 히스토리 (100단계) |
| `src/lib/scoreSerializer.ts` | alphaTab Score → ScoreSnapshot 변환 |
| `src/lib/scoreApplier.ts` | ScoreSnapshot 편집값 → alphaTab Score 모델 적용 |

### Frontend (수정)

| 파일 | 변경 내용 |
|------|-----------|
| `src/components/Editor/ScoreViewer.tsx` | noteMouseDown 이벤트, EditPanel 렌더링 |
| `src/App.tsx` | 3컬럼 레이아웃 |
| `src/lib/api.ts` | `syncFile(fileId, snapshot)` 추가 |

### Backend (신규)

| 파일 | 역할 |
|------|------|
| `app/routers/edit.py` | `POST /files/{id}/sync` |

### Backend (수정)

| 파일 | 변경 내용 |
|------|-----------|
| `app/pipeline/token_to_gp.py` | `snapshot_to_gp5(snapshot, out_path)` 추가 |
| `app/main.py` | edit 라우터 등록 |

---

## 자동저장

- 트리거: `editorStore.present` 변경 후 3초 debounce
- 조건: `fileId` 있을 때만 (비로그인 = 로컬 편집만, sync 안 함)
- 저장 상태 표시: UI 상단에 "저장 중…" / "저장됨" 표시
