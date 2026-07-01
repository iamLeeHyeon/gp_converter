# 공유 링크 설계 스펙

**날짜:** 2026-07-01
**연관:** Phase 3 후보 B (`docs/session-summary-2026-07-01.md`)

---

## 목표

로그인하지 않은 사람도 URL 하나로 특정 파일의 악보를 보고 재생할 수 있게 한다.
편집·다운로드는 불가 — 순수 읽기전용 공유.

| 항목 | 결정 |
|------|------|
| 권한 범위 | 보기 + 재생만 (편집/다운로드 불가) |
| 만료 정책 | 생성 시 선택 (7일 / 30일 / 무기한), 기본값 7일 |
| 링크 개수 | 파일당 1개 (재생성 시 기존 토큰 자동 무효화) |

---

## DB 스키마

`File` 모델에 컬럼 2개 추가 (별도 테이블 대신 — 파일당 링크 1개라 정규화 불필요):

```python
shared_token = Column(String, nullable=True, unique=True, index=True)
shared_expires_at = Column(DateTime(timezone=True), nullable=True)  # None = 무기한
```

### 마이그레이션

이 프로젝트는 Alembic 없이 `Base.metadata.create_all()`만 사용 (앱 시작 시 없는 테이블만 생성, 기존 테이블 컬럼 변경은 안 됨).
`shared_token`/`shared_expires_at`은 기존 `files` 테이블에 추가되는 컬럼이라 `create_all()`로는 반영 안 됨.

**해결**: 앱 시작 시(`app/database.py` 또는 `main.py`) SQLite `PRAGMA table_info(files)`로 컬럼 존재 확인 후, 없으면 `ALTER TABLE files ADD COLUMN ...` 실행하는 가벼운 가드 추가.
기존 업로드 파일·유저 데이터는 그대로 보존됨 (DB 삭제 후 재생성 방식 사용 안 함).

---

## 백엔드 API (`app/routers/share.py`, 신규)

| 엔드포인트 | 인증 | 설명 |
|-----------|------|------|
| `POST /files/{file_id}/share` | 필요 | body `{ expires_in_days: 7\|30\|null }` (기본 7). `secrets.token_urlsafe(24)` 토큰 생성, 기존 토큰 덮어씀. 응답 `{ token, expires_at }` |
| `GET /files/{file_id}/share` | 필요 | 현재 공유 상태 조회. 있으면 `{ token, expires_at }`, 없으면 `{ token: null }` |
| `DELETE /files/{file_id}/share` | 필요 | `shared_token`/`shared_expires_at`을 `None`으로 리셋 (공유 중단) |
| `GET /share/{token}` | **불필요 (공개)** | 토큰으로 `File` 조회. 없거나 만료됐으면 404. GP5 바이너리를 `FileResponse`로 반환 |

만료 판정: `shared_expires_at is not None and now() > shared_expires_at` → 404 `"링크가 만료되었습니다"`.
소유자 검증: 공유 생성/조회/삭제 3개 엔드포인트는 기존 패턴대로 `f.user_id != user.id` 체크 (403).

---

## 프론트엔드

### 링크 생성/관리 UI

`ShareModal.tsx` (신규) — `ExportMenu` 옆에 "공유" 버튼 추가, 클릭 시 모달 오픈:

- 기존 링크 있음: 링크 텍스트 + 복사 버튼, 만료일 표시(무기한이면 "무기한"), "공유 중단" 버튼
- 기존 링크 없음: 만료기간 select(7일/30일/무기한, 기본 7일) + "링크 생성" 버튼

링크 URL은 `${window.location.origin}/share/${token}` — 백엔드에 base URL 설정 불필요, 프론트에서 조립.

`api.ts`에 추가: `getShareStatus`, `createShareLink`, `revokeShareLink`.

스타일링은 기존 컴포넌트(`ExportMenu.tsx` 등)와 동일하게 최소 인라인 스타일만 사용 — 디자인은 사용자가 추후 별도로 다듬을 예정.

### 공개 뷰어

- `App.tsx`에 라우트 추가: `/share/:token` — `RequireAuth` 래핑 없이 공개 접근
- 신규 컴포넌트 `SharedScoreViewer.tsx`:
  - 기존 `ScoreViewer.tsx`는 재사용하지 않음 — editorStore(undo/redo·구조편집·자동저장)에 강하게 결합돼 있어 재사용 시 편집 관련 부작용 위험. 대신 `initAlphaTab`을 직접 호출하는 독립 컴포넌트로 격리
  - 마운트 시 `GET /share/{token}`으로 GP5 ArrayBuffer fetch (인증 헤더 없음) → alphaTab에 로드
  - UI: 악보 렌더링 + 재생/일시정지 버튼만. 사이드 패널(트랙/구조/편집) 전부 없음
  - 404/만료 시: 안내 문구만 표시 (예: "링크가 만료되었거나 존재하지 않습니다")

---

## 테스트 전략

- 백엔드 (pytest): 토큰 생성/재생성(구토큰 무효화)/조회/삭제/만료 판정/소유자 아닌 유저 403/공개 엔드포인트 인증 없이 200
- 프론트 (vitest): `ShareModal` 렌더링·생성 버튼 클릭 시 api 호출·기존 링크 표시·복사·중단 버튼, `SharedScoreViewer` 정상 로드 시 재생 버튼 노출 + 404/만료 시 안내문구
- 기존 163+119 테스트 그대로 통과 유지 (회귀 없음)

---

## 범위 제외 (YAGNI)

- 링크별 접근 로그/통계
- 비밀번호 보호 공유 링크
- 파일당 다중 링크
- 공유받은 사람의 댓글/피드백 기능
