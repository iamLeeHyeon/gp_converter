# 작업큐 Celery 전환 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/convert`의 변환 작업 실행을 FastAPI `BackgroundTasks`(웹서버 프로세스 내부)에서 Celery + Redis 큐(별도 워커 프로세스)로 옮긴다.

**Architecture:** `process_job` 순수 함수와 `JobStore`(파일기반 JSON 상태저장)는 손대지 않는다. 얇은 Celery task 래퍼(`process_job_task`)를 추가해 `jobs_dir` 문자열을 받아 워커 프로세스 안에서 `JobStore`를 재구성하게 하고, `/convert`가 `background_tasks.add_task(...)` 대신 `process_job_task.delay(...)`를 호출하도록 바꾼다. Redis는 순수 브로커 용도(결과 백엔드 없음).

**Tech Stack:** FastAPI, Celery 5.x, Redis(브로커), pytest

## Global Constraints

- 재시도 없음 — 실패 시 그대로 `FAILED`
- 결과 백엔드 없음 — 작업 상태는 기존 `JobStore`(파일기반 JSON)가 유일한 출처
- 동시성 제어는 Celery CLI `--concurrency=N` 옵션에 위임 — 코드로 구현 안 함
- `docker-compose.yml` 작성 안 함 — README에 수동 실행법만 안내
- `CELERY_BROKER_URL` 환경변수, 기본값 `redis://localhost:6379/0` (필수 아님, 다른 Stripe/JWT 환경변수처럼 없으면 에러내지 않음)
- 테스트는 Redis가 실제로 떠 있지 않아도 전체 통과해야 한다 — `.delay()` 호출은 전부 mock, `process_job_task`는 직접 호출(브로커 불필요)로만 검증
- 스펙 문서: `docs/superpowers/specs/2026-07-03-celery-job-queue-design.md`

---

### Task 1: Celery 앱 + task 래퍼

**Files:**
- Create: `app/celery_app.py`
- Create: `app/tasks.py`
- Modify: `requirements.txt`
- Test: `tests/test_tasks.py`

**Interfaces:**
- Produces: `app.celery_app.celery_app` (Celery 인스턴스), `app.tasks.process_job_task(jobs_dir: str, job_id: str, pdf_path: str, audiveris_cmd: str, tuxguitar_cmd: str, timeout: int, file_id: Optional[str] = None) -> None` — Task 2의 `app/main.py`가 이 task의 `.delay(...)`를 호출함

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_tasks.py` (신규):

```python
from unittest.mock import patch

from app.jobs import JobStore, JobStatus
from app.tasks import process_job_task


def test_process_job_task_delegates_with_reconstructed_store(tmp_path):
    """jobs_dir 문자열로 JobStore를 재구성해 process_job에 올바른 인자로 위임한다."""
    jobs_dir = str(tmp_path)
    store = JobStore(jobs_dir)
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.tasks.process_job") as mock_process_job:
        process_job_task(
            jobs_dir, job.id, str(pdf),
            audiveris_cmd="a", tuxguitar_cmd="t", timeout=10, file_id="f1",
        )

    mock_process_job.assert_called_once()
    args, kwargs = mock_process_job.call_args
    assert isinstance(args[0], JobStore)
    assert args[0].root == jobs_dir
    assert args[1] == job.id
    assert args[2] == str(pdf)
    assert kwargs == {
        "audiveris_cmd": "a", "tuxguitar_cmd": "t", "timeout": 10, "file_id": "f1",
    }


def test_process_job_task_real_success_updates_job_status(tmp_path):
    """mock 없이 실제 process_job까지 타서, 성공 시 job 상태가 DONE으로 바뀌는지 확인."""
    jobs_dir = str(tmp_path)
    store = JobStore(jobs_dir)
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job_task(jobs_dir, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.DONE
    assert got.result_path == "/x/output.gp5"


def test_process_job_task_callable_without_broker():
    """Celery task 데코레이터가 붙어도 일반 함수처럼 직접 호출 가능해야 한다(브로커 불필요)."""
    from app.tasks import process_job_task as task
    assert callable(task)
    # .delay/.apply_async 속성이 있다는 것 자체가 Celery task로 등록됐다는 증거
    assert hasattr(task, "delay")
    assert hasattr(task, "apply_async")
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_tasks.py -v`
Expected: `ModuleNotFoundError: No module named 'app.tasks'` (아직 파일이 없어서 임포트 자체가 실패)

- [ ] **Step 3: requirements.txt에 celery 추가**

`requirements.txt` 끝에 추가:

```
celery[redis]>=5.3,<6
```

Run: `pip install "celery[redis]>=5.3,<6"` (시스템/anaconda python 환경에 설치 — 이 프로젝트는 `python -m pytest`를 anaconda 기본 python으로 돌린다)

- [ ] **Step 4: Celery 앱 인스턴스 생성**

`app/celery_app.py` (신규):

```python
import os

from celery import Celery

celery_app = Celery(
    "gp_converter",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
)
celery_app.conf.update(task_ignore_result=True)
```

- [ ] **Step 5: task 래퍼 구현**

`app/tasks.py` (신규):

```python
from typing import Optional

from app.celery_app import celery_app
from app.jobs import JobStore
from app.worker import process_job


@celery_app.task(name="gp_converter.process_job")
def process_job_task(
    jobs_dir: str, job_id: str, pdf_path: str,
    audiveris_cmd: str, tuxguitar_cmd: str, timeout: int,
    file_id: Optional[str] = None,
) -> None:
    """Celery task 인자는 JSON 직렬화되므로 JobStore 객체를 직접 못 넘긴다.

    jobs_dir(문자열)만 받아 워커 프로세스 안에서 JobStore를 재구성한다.
    """
    store = JobStore(jobs_dir)
    process_job(
        store, job_id, pdf_path,
        audiveris_cmd=audiveris_cmd, tuxguitar_cmd=tuxguitar_cmd, timeout=timeout,
        file_id=file_id,
    )
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_tasks.py -v`
Expected: 3 passed

- [ ] **Step 7: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 기존 208개 전부 통과 + 신규 3개 = 211 passed (아직 `app/main.py`를 안 건드렸으므로 기존 `/convert` 관련 테스트는 원래대로 `app.main.process_job`을 패치하는 채로 통과해야 함 — Task 2에서 이걸 바꿈)

- [ ] **Step 8: 커밋**

```bash
git add app/celery_app.py app/tasks.py requirements.txt tests/test_tasks.py
git commit -m "feat: Celery 앱 + process_job task 래퍼 추가 (아직 미연결)"
```

---

### Task 2: /convert를 Celery 디스패치로 전환 + 테스트 마이그레이션 + 문서화

**Files:**
- Modify: `app/main.py`
- Modify: `tests/test_api.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `app.tasks.process_job_task` (Task 1)
- Produces: 없음 (최종 통합 지점 — 이후 태스크 없음)

- [ ] **Step 1: 실패 테스트로 먼저 바꾸기 (mock 대상 교체)**

`tests/test_api.py`에서 `app.main.process_job`을 참조하는 곳이 7군데 있다. 전부 `app.main.process_job_task.delay`로 바꾼다. 그중 3곳은 `side_effect` 핸들러 함수의 파라미터도 함께 고쳐야 한다(첫 인자가 이제 `JobStore` 객체가 아니라 `jobs_dir` 문자열이기 때문).

**(a) `test_convert_then_status_then_result`** (44-64행) 전체를 아래로 교체:

```python
def test_convert_then_status_then_result(tmp_path):
    client, m = make_client(tmp_path)

    # Celery task 디스패치(.delay)가 즉시 동기 실행되도록 패치
    def fake_delay(jobs_dir, job_id, pdf_path, **kwargs):
        from app.jobs import JobStore
        store = JobStore(jobs_dir)
        gp5 = tmp_path / "r.gp5"
        gp5.write_bytes(b"FICHIER GUITAR PRO")
        store.update(job_id, status=m.JobStatus.DONE, result_path=str(gp5))

    with patch("app.main.process_job_task.delay", side_effect=fake_delay):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        s = client.get(f"/jobs/{job_id}")
        assert s.status_code == 200
        assert s.json()["status"] == "done"

        res = client.get(f"/jobs/{job_id}/result")
        assert res.status_code == 200
        assert res.content.startswith(b"FICHIER GUITAR PRO")
```

**(b) `test_result_not_done_returns_409`** (72-84행) 전체를 아래로 교체:

```python
def test_result_not_done_returns_409(tmp_path):
    # 큐 디스패치가 no-op이라 job은 "queued" 상태로 남는다
    def noop_delay(jobs_dir, job_id, pdf_path, **kwargs):
        pass

    client, _ = make_client(tmp_path)
    with patch("app.main.process_job_task.delay", side_effect=noop_delay):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

    res = client.get(f"/jobs/{job_id}/result")
    assert res.status_code == 409
```

**(c) `test_accepted_upload_content_fully_written`** (118-129행) 중 아래 부분:

```python
    def noop_process(store, job_id, pdf_path, **kwargs):
        with open(pdf_path, "rb") as f:
            assert f.read() == body

    with patch("app.main.process_job", side_effect=noop_process):
```

을 아래로 교체:

```python
    def noop_delay(jobs_dir, job_id, pdf_path, **kwargs):
        with open(pdf_path, "rb") as f:
            assert f.read() == body

    with patch("app.main.process_job_task.delay", side_effect=noop_delay):
```

**(d) 나머지 4곳** — `test_free_user_allowed_with_2_successful_conversions`(179행 부근), `test_free_user_not_blocked_by_failed_conversions`(226행 부근), `test_pro_user_unlimited`(250행 부근), `test_anonymous_user_not_limited`(263행 부근)에 각각 있는 다음 줄:

```python
        with patch("app.main.process_job"):
```

을 전부 아래로 교체 (4곳 모두 동일한 치환, `replace_all` 사용 가능):

```python
        with patch("app.main.process_job_task.delay"):
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_api.py -v`
Expected: `AttributeError: <module 'app.main' ...> does not have the attribute 'process_job_task'` (아직 main.py가 `process_job_task`를 임포트하지 않으므로 patch 대상 자체가 없음)

- [ ] **Step 3: main.py를 Celery 디스패치로 전환**

`app/main.py`의 import 부분에서:

```python
from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
```

을:

```python
from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, Request
```

로 교체(더 이상 `BackgroundTasks` 안 씀).

그리고:

```python
from app.worker import process_job
```

을:

```python
from app.tasks import process_job_task
```

로 교체.

`convert()` 함수 시그니처에서:

```python
@app.post("/convert")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
```

을:

```python
@app.post("/convert")
async def convert(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
```

로 교체(`background_tasks` 파라미터 제거).

함수 끝부분, 현재 이렇게 되어 있는 블록:

```python
    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
        file_id=file_id,
    )
    return {"job_id": job.id, "file_id": file_id}
```

을 아래로 교체:

```python
    process_job_task.delay(
        settings.jobs_dir, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
        file_id=file_id,
    )
    return {"job_id": job.id, "file_id": file_id}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_api.py -v`
Expected: 전부 통과 (기존 13개 그대로, 시그니처만 바뀜)

- [ ] **Step 5: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 211 passed (Task 1의 211 그대로, 이번 태스크는 테스트 개수 안 늘리고 기존 걸 마이그레이션만 함)

- [ ] **Step 6: README 문서화**

`README.md`의 "### 3. 서버 실행" 섹션:

```markdown
### 3. 서버 실행

```bash
uvicorn app.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속 → PDF 업로드 → 변환 완료되면 `.gp5` 다운로드.
```

을 아래로 교체(Redis + Celery 워커 섹션 추가):

```markdown
### 3. Redis + Celery 워커 실행

변환 작업은 Celery 워커가 처리한다. 로컬에서 Redis를 띄운다:

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

브로커 주소가 기본값(`redis://localhost:6379/0`)과 다르면 환경변수로 지정한다:

```bash
export CELERY_BROKER_URL=redis://localhost:6379/0
```

별도 터미널에서 워커를 띄운다(동시 처리 개수는 `--concurrency`로 조절):

```bash
celery -A app.celery_app worker --loglevel=info --concurrency=2
```

### 4. 서버 실행

```bash
uvicorn app.main:app --reload --port 8000
```

브라우저에서 `http://localhost:8000` 접속 → PDF 업로드 → 변환 완료되면 `.gp5` 다운로드.

**주의:** Celery 워커가 떠 있지 않으면 `/convert`는 job을 큐에 넣기만 하고 실제 변환은 영영 시작되지 않는다(`GET /jobs/{id}`가 `queued`에서 안 넘어감).
```

`README.md`의 "환경변수" 표에서, `GPC_JOBS_DIR` 행 다음에 추가:

```markdown
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery 브로커(Redis) 주소 |
```

`README.md`의 "프로젝트 구조" 코드블록에서, `worker.py` 줄 다음에 추가:

```
  celery_app.py          # Celery 앱 인스턴스 (브로커 설정)
  tasks.py               # Celery task 래퍼 (process_job 위임)
```

- [ ] **Step 7: 커밋**

```bash
git add app/main.py tests/test_api.py README.md
git commit -m "feat: /convert가 Celery 큐로 변환 작업을 디스패치하도록 전환"
```

---

## 최종 검증 (전체 태스크 완료 후)

- [ ] Run: `python -m pytest -q` — 전체 백엔드 통과 (기존 208 + 신규 3 = 211, Redis 안 떠 있어도 통과해야 함)
- [ ] 수동 확인(선택, Redis/Docker 있으면): `docker run --rm -p 6379:6379 redis:7-alpine` → `celery -A app.celery_app worker --loglevel=info` → `uvicorn app.main:app --reload` → PDF 업로드 후 워커 로그에 task가 찍히고 `.gp5`가 정상 다운로드되는지 확인
