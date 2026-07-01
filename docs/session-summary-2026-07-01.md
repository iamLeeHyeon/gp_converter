# gp_converter 세션 요약 — 2026-07-01

**HEAD:** `4cf28f0` | **브랜치:** main (origin/main 동기화 완료)  
**테스트:** 백엔드 163 passed, 프론트 115 passed (21 files)

---

## 완료된 작업 (이번 세션)

### Phase 2 구조 편집기 — 7 Tasks (TDD, subagent-driven)

| Task | 내용 | 커밋 |
|------|------|------|
| Task 1 | ScoreSnapshot v2 타입 + scoreSerializer v2 | `919fe71` |
| Task 2 | applyStructuralEdit 순수 함수 (11종 편집) | `8606558` → `759b309` |
| Task 3 | snapshot_to_gp5 v2 (keySignature/sectionMarker/voices) | `aa489f2` → `d61a2b7` |
| Task 4 | snapshot_to_gp5 다중 트랙 + 튜닝 | `5aff950` |
| Task 5 | editorStore v2 + api.getGP5Buffer + forceSync | `f6fe48a` |
| Task 6 | StructurePanel UI (마디 추가/삭제/이동/박자표/조표/섹션마커) | `5282466` → `3f7417d` |
| Task 7 | TrackPanel UI (트랙 추가/삭제/이름/튜닝/Capo/Voice) | `69ca93d` |

### 최종 리뷰에서 발견 + 수정된 버그 (`4cf28f0`)

| 심각도 | 버그 | 수정 |
|--------|------|------|
| Critical | `beat.velocity` → 항상 undefined (alphaTab Beat에 없는 필드) | `beat.dynamics ?? 4` |
| Critical | 스트럼 방향 반전: PickStroke Up=1, Down=2 혼동 | `pickStroke === 2 ? true : pickStroke === 1 ? false` |
| Important | 첫 트랙 이름 하드코딩 "Guitar" → 사용자 이름 유실 | `tracks_data[0].get("name", "Guitar")` |

---

## 핵심 아키텍처

### 데이터 흐름

**음표 편집 (Phase 1):**
```
alphaTab 이벤트 → applySnapshot(score, beat, edit) → serializeScore(score)
→ editorStore.pushSnapshot() → useSyncFile debounce 3초
→ POST /files/{id}/sync (ScoreSnapshot JSON) → snapshot_to_gp5() → GP5 저장
```

**구조 편집 (Phase 2):**
```
StructurePanel/TrackPanel 클릭 → applyStructuralEdit(snapshot, edit)
→ pushSnapshot() → forceSync() (즉시)
→ POST /sync → GET /download → ArrayBuffer
→ editorStore.setGp5Buffer() → ScoreViewer useEffect
→ apiRef.current.load(gp5Buffer) [alphaTab 완전 리로드]
```

### 주요 파일

```
frontend/src/
├── lib/
│   ├── scoreTypes.ts          # ScoreSnapshot, SnapshotTrack, SnapshotMeasure, SnapshotBeat
│   ├── scoreSerializer.ts     # alphaTab score → ScoreSnapshot (serializeScore)
│   ├── scoreApplier.ts        # ScoreSnapshot → alphaTab 인플레이스 수정
│   ├── structuralEdit.ts      # applyStructuralEdit (11종 편집, 순수 함수)
│   ├── api.ts                 # syncFile, getGP5Buffer, exportMidi...
│   └── useSyncFile.ts         # debounce autosave + forceSync
└── components/Editor/
    ├── ScoreViewer.tsx         # alphaTab 렌더링, StructurePanel/TrackPanel 포함
    ├── EditPanel.tsx           # 음표 편집 패널
    ├── StructurePanel.tsx      # 마디 구조 편집 패널
    ├── TrackPanel.tsx          # 트랙 편집 패널
    └── ExportMenu.tsx          # GP5/PDF/MIDI 내보내기

app/pipeline/
└── token_to_gp.py             # snapshot_to_gp5() — ScoreSnapshot → GP5
```

### PyGuitarPro 핵심 주의사항

- `KeySignature((n, 0))` — 튜플로 전달 (두 인수 전달 시 `TypeError: Cannot extend enumerations`)
- `gpm.Track(song, number=N, strings=[...])` — `strings` 반드시 키워드 인수
- `Track`에 `capo` 속성 없음 — ScoreSnapshot에만 보관

---

## 알려진 미해결 이슈

| 심각도 | 이슈 |
|--------|------|
| Important | 구조 편집 Undo/Redo 미작동: Ctrl+Z 시 store 되돌리지만 alphaTab 표시 그대로 (재sync 없음) |
| Important | setTrackName 디바운스 없음: 글자마다 fullsync + alphaTab 리로드 |
| Minor | capo GP5 미기록: PyGuitarPro Track에 capo 속성 없음 |
| Minor | selectedIndex 클램프 없음: 마지막 마디/트랙 삭제 시 패널 이상 |
| Minor | useSyncFile forceSync 데드코드 (패널들이 자체 applyAndSync 구현) |
| Minor | JWT 15분 만료 후 조용히 실패 |

---

## 다음 할 것 (Phase 3 후보)

### A. Phase 2 이연 버그 정리 (먼저 처리 권장)
1. 구조 편집 Undo/Redo: undo 시 `forceSync()` 호출 (구조 변경 감지)
2. setTrackName 500ms 디바운스
3. selectedIndex 클램프: `Math.min(idx, newLength-1)`

### B. 공유 링크
- 읽기 전용 URL (로그인 불필요, 만료 옵션)
- DB `shared_token` 컬럼 추가

### C. Stripe 결제
- Free: 월 3회 변환, 저장 5개
- Pro: 무제한
- `stripe` SDK + Webhook

### D. 작업 큐 강화
- Celery + Redis (현재 FastAPI BackgroundTask 인메모리)

### E. 인프라
- 파일 저장 S3 호환
- SoundFont CDN (CloudFront)
- Docker Compose 프로덕션 설정

---

## 기술 스택

| 레이어 | 기술 |
|--------|------|
| 백엔드 | FastAPI, SQLAlchemy (SQLite), PyGuitarPro, mido, Audiveris |
| 프론트 | React 18, TypeScript, Zustand, alphaTab ^1.8.3, Vite |
| 테스트 | pytest (163), vitest + @testing-library/react (115) |
| 인증 | Google OAuth 2.0, JWT (HS256, 15분 만료) |
| 배포 | 미정, Docker 이식성 유지 |

---

## 개발 워크플로

```
새 기능: /brainstorming → 스펙 → /writing-plans → /subagent-driven-development
버그:    /systematic-debugging → TDD fix
브랜치:  main 직접 커밋
플랜:    docs/superpowers/plans/YYYY-MM-DD-*.md
SDD 레저: .superpowers/sdd/progress.md
```
