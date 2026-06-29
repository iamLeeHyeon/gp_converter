# GP Converter — Guitar Pro 수준 웹 에디터 설계

## 개요

PDF 악보를 업로드하면 GP5로 변환하고, 브라우저에서 바로 편집·재생·내보내기까지 할 수 있는 SaaS 웹 에디터. React + TypeScript 프론트엔드, FastAPI 백엔드, alphaTab 렌더링 엔진.

---

## 기술 스택

| 레이어 | 기술 |
|---|---|
| 프론트엔드 | React 18 + TypeScript + Vite |
| 악보 렌더링/재생 | alphaTab 1.x (MIT) |
| 상태 관리 | Zustand (경량, alphaTab 모델과 통합 쉬움) |
| 백엔드 | FastAPI (기존 유지) |
| DB | SQLite (개발) → PostgreSQL (운영) via SQLAlchemy |
| 파일 저장 | 로컬 (개발) → S3 호환 (운영, 배포 환경 미정) |
| 인증 | OAuth2 (Google / GitHub) + JWT (access/refresh token) |
| 결제 | Stripe (구독 플랜) |
| 작업 큐 | Celery + Redis (PDF 변환 비동기 처리) |
| CDN | CloudFront 또는 동급 (alphaTab SoundFont 수십 MB 서빙) |

---

## 페이즈 구성

### Phase 0 — 뷰어 + 재생 + 인증 + 파일 관리 + 변환 진행률

**목표:** PDF 올리면 변환 진행률 실시간 표시 → GP5 렌더링 → 재생 → 파일 저장/목록

**기능 목록:**
- OAuth 로그인 (Google, GitHub)
- JWT 인증 (access 15분 / refresh 7일)
- PDF 업로드 → Celery 큐 → GP5 변환
- **변환 진행률 바**: WebSocket 또는 SSE(Server-Sent Events)로 단계별 % 푸시
  - 10% 업로드 완료
  - 30% TAB 보표 감지
  - 60% OMR 추론
  - 85% GP5 빌드
  - 100% 완료
- alphaTab으로 GP5 렌더링 (악보 + TAB 동시)
- Web Audio 재생 (SoundFont SF2, CDN에서 로드)
- 재생 속도 조절, 구간 반복
- 파일 목록 (내 악보) — 이름 변경/삭제
- 모바일 반응형 (뷰어·재생 한정, 편집은 데스크탑 전용)

### Phase 1 — 기본 편집기

**목표:** 클릭으로 음표 선택 → 프렛/지속시간/이펙트 수정 → Undo/Redo → 자동저장

**기능 목록:**
- alphaTab 클릭 이벤트로 음표 선택 (하이라이트)
- 사이드 패널에서 편집:
  - 프렛 번호 변경
  - 지속시간 변경 (온/이분/사분/팔분/십육분/서른둘분)
  - 점음표 토글
  - 이펙트: 슬라이드(shift/legato/in/out), 해머온/풀오프, 뮤트(X), 고스트, 하모닉스
  - 스트럼 방향 (▼▲)
  - 다이나믹 (ppp~fff)
- 음표 추가 (비어있는 박자에 클릭 또는 단축키)
- 음표 삭제 (Delete 키)
- **Undo/Redo**: 편집 동작마다 alphaTab.Model 스냅샷 → Zustand 히스토리 스택 (최대 100단계)
- **자동저장**: 편집 후 3초 idle → 서버에 GP5 동기화 (Debounce)
- 저장 시 흐름: 클라이언트 alphaTab Model → JSON 직렬화 → 서버 `/edit` API → pyguitarpro GP5 파일 생성 → 저장
- 키보드 단축키 (Cmd/Ctrl+Z, Cmd/Ctrl+Y, Delete, 방향키로 음표 이동)

### Phase 2 — 고급 편집기 + 내보내기

**목표:** Guitar Pro 수준 구조 편집 + 다양한 포맷 내보내기

**기능 목록:**
- 마디 추가/삭제/이동
- 박자표 변경 (3/4, 6/8 등)
- 조표(Key Signature) 변경
- 트랙 추가/삭제 (다중 트랙)
- 튜닝 변경 (Drop D, Open G 등)
- Capo 설정
- 다성부 편집 (Voice 1/2)
- 섹션 마커 (인트로, 버스, 코러스 등)
- **내보내기**:
  - GP5 다운로드
  - PDF (alphaTab 프린트 렌더링)
  - MIDI (alphaTab Web Audio → MIDI)
  - MP3/WAV (alphaTab AudioExporter, Web Audio API)

### Phase 3 — SaaS 완성

**목표:** 결제, 작업 큐 강화, CDN, 공유 기능

**기능 목록:**
- **공유 링크**: 읽기 전용 URL (로그인 불필요, 만료 옵션)
- **Stripe 결제**:
  - Free: 월 3회 변환, 저장 파일 5개
  - Pro: 무제한 변환, 저장 무제한, 오디오 내보내기
- Celery + Redis 작업 큐 (여러 서버에서 변환 분산 처리)
- SoundFont CDN 서빙 (CloudFront 또는 동급)
- 파일 저장 S3 호환 (배포 환경 결정 시 적용)

---

## 아키텍처 상세

### 변환 진행률 (Phase 0 핵심)

```
[클라이언트] PDF 업로드 POST /convert
              ↓
[서버] job_id 즉시 반환 + BackgroundTask 시작
              ↓
[클라이언트] GET /jobs/{job_id}/stream (SSE 연결)
              ↓
[BackgroundTask] 단계별 진행률 → JobStore에 pct 업데이트
              ↓
[서버 SSE] JobStore polling (0.5초) → 클라이언트로 스트리밍
              data: {"step": "omr", "pct": 60}

[클라이언트] 애니메이션 진행률 바 업데이트

※ Phase 3에서 Celery + Redis로 교체 (멀티서버 스케일)
```

### 편집 데이터 흐름 (Phase 1 핵심)

```
[클라이언트]
alphaTab.Model (메모리) ← 편집 동작
      ↓ (3초 debounce)
Model → JSON 직렬화 → POST /files/{id}/sync
      ↓
[서버] JSON → pyguitarpro Song 객체 → GP5 파일 저장
      ↓
[클라이언트] 저장 완료 표시
```

### 인증 흐름

```
[클라이언트] Google OAuth 버튼 클릭
→ /auth/google → Google OAuth 동의
→ /auth/google/callback → JWT 발급
→ localStorage에 access_token 저장
→ API 요청마다 Authorization: Bearer {token}
```

### DB 스키마 (핵심 테이블)

```sql
users (id, email, provider, provider_id, plan, created_at)
files (id, user_id, name, gp5_path, created_at, updated_at)
jobs  (id, user_id, file_id, status, progress_pct, message, created_at)
```

---

## 프론트엔드 구조

```
src/
  components/
    Editor/
      ScoreViewer.tsx      — alphaTab 마운트, 이벤트 바인딩
      NotePanel.tsx        — 선택된 음표 편집 사이드 패널
      Toolbar.tsx          — 재생/편집 도구 모음
      ProgressBar.tsx      — 변환 진행률 애니메이션
    FileManager/
      FileList.tsx
      UploadButton.tsx
    Auth/
      LoginPage.tsx
      OAuthCallback.tsx
  store/
    editorStore.ts         — Zustand: alphaTab API, 선택 상태, undo 스택
    authStore.ts           — JWT, 사용자 정보
    fileStore.ts           — 파일 목록
  lib/
    alphatab.ts            — alphaTab 초기화 래퍼
    api.ts                 — FastAPI 클라이언트
    sse.ts                 — SSE 연결 관리
```

---

## 백엔드 추가 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | /auth/google | OAuth 리다이렉트 |
| GET | /auth/github | OAuth 리다이렉트 |
| POST | /auth/refresh | JWT 갱신 |
| GET | /jobs/{id}/stream | SSE 진행률 스트리밍 |
| GET | /files | 내 파일 목록 |
| POST | /files/{id}/sync | 편집된 모델 GP5 동기화 |
| GET | /files/{id}/share | 읽기 전용 공유 링크 생성 |
| POST | /stripe/webhook | 결제 이벤트 처리 |

---

## 글로벌 제약

- alphaTab 버전 고정: `1.x` (1.x → 2.x API 파괴적 변경 있음, 업그레이드 별도 검토)
- GP5 포맷 유지 (GPX로의 전환은 Phase 3 이후)
- 편집 중 서버 왕복 없음 — alphaTab.Model이 단일 진실 원천
- 저장은 Debounce 3초 (즉각 저장 아님) → UI에 "저장 중..." 표시 필수
- 배포 환경 미정 — 로컬 파일시스템 + SQLite로 추상화 레이어 유지
- SoundFont는 alphaTab 기본 제공 CDN (`https://cdn.jsdelivr.net/...`) 우선 사용
