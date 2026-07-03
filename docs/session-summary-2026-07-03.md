# gp_converter 세션 요약 — 2026-07-03 (Phase 3 완료)

**HEAD:** `a1b47ce` | **브랜치:** main (origin/main 동기화 완료)
**테스트:** 백엔드 238 passed(2 deselected: `-m integration`), 프론트 147 passed (27 files)

---

## 완료된 작업 (Phase 3 A~E 전부)

### A. Phase 2 이연 버그 정리
| 버그 | 수정 |
|------|------|
| 구조 편집 Undo/Redo 미작동 | undo 시 `forceSync()` 호출하도록 수정 |
| setTrackName 디바운스 없음 | 500ms 디바운스 추가 |
| selectedIndex 클램프 없음 | `Math.min(idx, newLength-1)` |

커밋: `eaef380` (3건 한 커밋)

### B. 공유 링크
- `File`에 `shared_token`/만료 컬럼 추가, SQLite 마이그레이션 가드
- 소유자용 생성/조회/삭제 API + 토큰 공개조회 API(인증 불필요, 만료체크)
- `ShareModal`(생성/중단 UI) + `SharedScoreViewer`(`/share/:token` 공개 뷰어)
- 발견/수정된 버그: 마이그레이션 unique index가 컬럼 존재여부와 무관하게 항상 생성되도록 수정, `ShareModal` 언마운트 후 setState 레이스 방지(테스트가 reject 경로를 실제로 타도록 재작성해서 검증에 이빨이 서게 함)

커밋 범위: `a437b55`..`838af39` (12커밋)

### C. Stripe 결제
- Free(월 3회 변환/저장 5개) / Pro(무제한) 플랜, Stripe Checkout + Customer Portal 세션 API
- 웹훅으로 구독상태 → `User.plan` 동기화
- `BillingPanel`(사용량 표시 + 업그레이드/구독관리)
- 발견/수정된 버그: 사용량 카운트가 실패/대기 변환까지 세던 문제 → **성공한 파일만 카운트**하도록 수정(무료플랜 영구 잠김 위험 해소), 인증 테스트가 실제 DB를 오염시키던 문제(`get_db` 격리) 수정

커밋 범위: `d2159e4`..`7cb60ff` (13커밋)

### D. 작업큐 Celery 전환
- FastAPI `BackgroundTask`(인메모리) → Celery + Redis 실제 작업큐로 전환
- `/convert`가 `.delay()`로 디스패치, `app/tasks.py`가 task 래퍼

**⚠️ 라이브 스모크테스트로만 발견 가능했던 Critical 버그**: `celery -A app.celery_app worker`로 띄우면 `app/tasks.py`를 임포트한 적이 없어 task가 등록 안 됨(`KeyError`) — 반드시 `celery -A app.tasks:celery_app worker`로 띄워야 함. README에 경고 문단 추가(`7f005a2`).

커밋 범위: `ba50c2c`..`b9c3fa3` (6커밋)

### E. 인프라

**E-1. S3 호환 파일저장**
- `app/storage.py`: `Storage` 프로토콜 + `LocalStorage`/`S3Storage`, `STORAGE_BACKEND=local|s3` 환경변수
- 저장된 GP5 파일(`File.gp5_path`)만 대상, 변환 임시파일은 그대로 로컬
- **최종 리뷰에서 발견된 회귀**: `shutil.copy`(비원자적)로 바뀌면서 Phase 1의 원자적 쓰기(`mkstemp`+`os.replace`)가 회귀 — 동시 다운로드 시 잘린 파일을 받을 위험. 복원 완료(`36e6aaf`), 원자적 교체가 실제로 실행되는지 증명하는 테스트 추가.

커밋 범위: `9344fa3`..`4f15c38` (8커밋)

**E-2. Docker Compose 프로덕션 설정**
- `Dockerfile` 멀티스테이지(node 프론트빌드 → python+Audiveris)로 `npm run build` 수동 실행 불필요
- `docker-compose.yml`: `redis`/`web`/`worker` 3서비스, `jobs-data`/`db-data` named volume으로 **"web/worker가 파일시스템 공유 안 하면 job이 조용히 멈춤"** 한계를 실제로 해소
- `.env.example` 신규(전체 환경변수 템플릿), 리버스프록시/TLS는 의도적으로 제외(배포환경 몫)

커밋 범위: `f1b47a8`..`a1b47ce` (5커밋)

**E-3. SoundFont CDN** — 별도 작업 없이 완료로 간주. `frontend/src/lib/alphatab.ts`가 이미 `cdn.jsdelivr.net`으로 alphaTab 폰트/사운드폰트를 서빙 중 — 자체 CloudFront 구축 없이 기존 CDN으로 충분하다고 판단.

---

## 이번 세션에서 발견한 로컬 환경 이슈 (코드 버그 아님)

로컬 `.venv`(`python3 -m venv .venv`로 생성된 프로젝트 전용 가상환경)에 `sqlalchemy`/`pyjwt`/`stripe`/`celery`/`boto3`가 설치돼 있지 않았음 — Phase 3에서 `requirements.txt`에 추가된 뒤로 이 venv에 `pip install -r requirements.txt`가 재실행된 적이 없었던 것으로 보임. `pytest`가 15개 파일에서 `ModuleNotFoundError`로 수집 자체가 실패하는 상태였고, 터미널의 `celery` 커맨드도 PATH상 anaconda(`/opt/anaconda3/bin/celery`)로 조용히 대체 실행되고 있었음(우연히 그쪽엔 의존성이 다 있어서 겉으로는 정상 동작한 것처럼 보였음).

`pip install -r requirements.txt`를 `.venv`에 재실행해서 해결. 이후 `pytest` 238 passed로 정상 확인. **Docker 이미지 빌드에는 영향 없음**(Dockerfile이 매번 새로 `pip install`하므로) — 순수히 이 로컬 개발머신의 `.venv`만의 문제였음.

---

## 핵심 아키텍처 (Phase 3 반영)

```
POST /convert → JobStore(파일기반) 생성 → Celery .delay() → Redis 큐
                                                    ↓
                                        Celery worker(app.tasks:celery_app)
                                                    ↓
                              Audiveris(OMR) → music21 → PyGuitarPro(.gp5)
                                                    ↓
                                     Storage.save_file() (local 또는 S3)
```

- 인증: Google/GitHub OAuth + JWT(15분) — Phase 2까지 완료
- 결제: Stripe Checkout/Webhook, `User.plan`(free/pro), 사용량 제한은 **성공한 변환만** 카운트
- 공유: `File.shared_token` + 만료, `/share/:token` 공개 뷰어
- 저장: `app/storage.py` 추상화(local/S3), 배포는 `docker-compose.yml`(redis+web+worker, named volume 영속화)

---

## 알려진 한계 (누적, README에 문서화됨)

- 탭 인식은 디지털 PDF 한정, 스캔이미지/화음탭/기법기호 미지원
- SQLite 유지(수평확장 없음), 리버스프록시/TLS는 docker-compose에 미포함(배포자 몫)
- `STORAGE_BACKEND` 전환 시 기존 파일 자동 이관 없음
- 익명 요청이 로그인 유저와 동일 큐를 우선순위 없이 공유(레이트리밋/우선순위 큐 없음)
- 헬스체크/CI-CD 없음 — 향후 필요시 추가

---

## 개발 워크플로 (변경 없음)

```
새 기능: /brainstorming → 스펙 → /writing-plans → /subagent-driven-development
버그:    /systematic-debugging → TDD fix
브랜치:  main 직접 커밋
플랜:    docs/superpowers/plans/YYYY-MM-DD-*.md
SDD 레저: .superpowers/sdd/progress.md
```

**Phase 3(A~E) 전체 완료. 다음 페이즈 후보는 아직 없음 — 필요해지면 새로 브레인스토밍.**
