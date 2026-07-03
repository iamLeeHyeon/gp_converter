# 작업 큐 Celery 전환 설계 스펙

**날짜:** 2026-07-03
**연관:** Phase 3 후보 D (`docs/session-summary-2026-07-01.md`)

---

## 목표

현재 `/convert`는 FastAPI `BackgroundTasks`로 변환 작업을 웹서버 프로세스 안에서 그대로 실행한다(동시성 제어·재시도·워커 분리 전혀 없음). 아직 실제 부하 문제를 겪는 건 아니지만, 사용자/배포가 늘기 전에 미리 관리 가능한 구조(Celery + Redis)로 바꿔둔다.

| 항목 | 결정 |
|------|------|
| 도입 동기 | 선제적 구조 정비(현재 실사용 문제 아님) — 과잉설계 지양, 최소 변경 |
| 브로커 | Redis, `CELERY_BROKER_URL` 환경변수(기본값 `redis://localhost:6379/0`) |
| 결과 백엔드 | 없음 — 작업 상태/진행률은 기존 `JobStore`(파일기반 JSON)를 그대로 유지, Redis는 순수 큐 용도 |
| 재시도 | 없음 — 실패 시 그대로 `FAILED` (Audiveris 실패는 대부분 악보 자체 문제라 재시도해도 또 실패, 자동재시도 이득 적음) |
| 동시성 제어 | Celery `--concurrency=N` CLI 옵션에 위임 — 코드 변경 없음, README 안내만 |
| Docker Compose | 이번 범위 제외 — Phase 3 E(인프라)에서 별도 처리 |

---

## 아키텍처

```
[변경 전]
POST /convert → background_tasks.add_task(process_job, store, job.id, pdf_path, ...)
             → (웹서버 프로세스 내 스레드풀에서 즉시 실행)

[변경 후]
POST /convert → process_job_task.delay(jobs_dir, job.id, pdf_path, ...)
             → Redis 큐 적재
             → (별도 `celery -A app.celery_app worker` 프로세스가 가져가서 실행)
             → process_job_task 내부에서 JobStore(jobs_dir) 재구성 후 기존 process_job() 그대로 호출
```

**핵심 설계 결정 — Celery task 인자는 JSON 직렬화된다.** `JobStore` 인스턴스를 직접 넘길 수 없으므로, task는 `jobs_dir`(문자열)만 받아 워커 프로세스 안에서 `JobStore(jobs_dir)`를 새로 만든다. 웹서버와 워커가 같은 `jobs_dir` 파일시스템을 봐야 동작한다(로컬 개발·단일 서버 배포에서는 자연히 성립, 워커를 다른 머신으로 분리하려면 공유 스토리지가 필요 — 이건 Phase 3 E "S3 호환 파일저장"의 몫이라 이번엔 다루지 않는다).

`process_job` 순수 함수 자체는 손대지 않는다 — `app/tasks.py`의 얇은 래퍼(`process_job_task`)만 추가해서 감싼다. SSE 상태조회(`/jobs/{id}/stream`)는 여전히 같은 `JobStore` JSON 파일을 폴링하므로 전혀 수정 불필요.

---

## 파일 계획

| 파일 | 변경 |
|------|------|
| `app/celery_app.py` (신규) | Celery 앱 인스턴스, `CELERY_BROKER_URL` 환경변수 읽기 |
| `app/tasks.py` (신규) | `process_job_task` — jobs_dir로 JobStore 재구성 후 `process_job` 호출 |
| `app/main.py` (수정) | `convert()`가 `process_job_task.delay(...)` 호출로 교체. 더 이상 안 쓰는 `BackgroundTasks` 파라미터/import 제거 |
| `requirements.txt` (수정) | `celery[redis]` 추가 |
| `README.md` (수정) | 로컬에서 Redis + Celery 워커 띄우는 법, `CELERY_BROKER_URL` 환경변수 문서화 |
| `tests/test_api.py` (수정) | mock 대상 `app.main.process_job` → `app.main.process_job_task.delay`로 교체 |
| `tests/test_tasks.py` (신규) | `process_job_task` 래퍼 테스트 |
| `tests/test_worker.py` | **무변경** — `process_job` 순수함수 자체는 안 바뀜 |

---

## 테스트 전략

- Redis가 실제로 떠 있지 않아도 전체 테스트 스위트가 통과해야 한다 — Celery는 브로커 연결을 `.delay()`/`.apply_async()` 호출 시점에만 시도하므로, 앱 모듈을 임포트하는 것만으로는 Redis가 필요 없다.
- `tests/test_api.py`의 `/convert` 통합 테스트들은 지금처럼 `patch("app.main.process_job", ...)`로 실제 실행을 막던 것을, `patch("app.main.process_job_task.delay", ...)`(또는 동등한 mock)로 바꿔 큐 적재 자체를 가짜로 만든다 — 실제 브로커 연결 시도 없음.
- `tests/test_tasks.py`는 `process_job_task`를 `.delay()`가 아니라 직접 호출(또는 `.run()`)해서 "jobs_dir로 JobStore를 올바르게 재구성해 process_job에 올바른 인자로 위임하는지"만 검증 — 이것도 브로커 불필요.
- `tests/test_worker.py`는 기존 그대로 유지(회귀 확인용, 코드 변경 없음).

---

## 알려진 한계 / 범위 제외 (YAGNI)

- 자동 재시도 없음
- Celery 결과 백엔드 없음(JobStore만 유일한 상태 저장소)
- `docker-compose.yml` 미작성 — 로컬 실행은 README에 Redis 단일 컨테이너 + `celery worker` CLI 명령으로 안내
- 워커를 다른 머신에 분산 배치하는 시나리오(공유 스토리지 필요)는 다루지 않음
- 동시성 제어 로직 직접 구현 안 함 — Celery CLI `--concurrency` 옵션에 위임
