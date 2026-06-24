# PDF → Guitar Pro 변환기 MVP 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 디지털 표준악보 PDF를 업로드하면 `.gp5`(Guitar Pro) 파일로 변환해 다운로드하는 웹 앱을 만든다.

**Architecture:** FastAPI 백엔드가 PDF를 받아 job으로 큐잉하고, 백그라운드 워커가 `Audiveris(PDF→MusicXML) → TuxGuitar(MusicXML→.gp5)` 파이프라인을 실행한다. 각 단계는 외부 Java 도구를 subprocess로 호출하는 독립 모듈이며, 단위 테스트에서는 subprocess를 모킹한다.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, pytest. 외부 도구: Audiveris, TuxGuitar (Java/JRE). 배포: Docker.

---

## 파일 구조

```
gp_converter/
  app/
    __init__.py
    config.py            # 경로/도구 위치/제한값 설정
    jobs.py              # Job 모델 + 파일 기반 job 저장소
    pipeline/
      __init__.py
      audiveris.py       # pdf_to_musicxml()
      tuxguitar.py       # musicxml_to_gp5()
      orchestrator.py    # run_conversion()
    worker.py            # 백그라운드 변환 실행
    main.py              # FastAPI 앱 + 라우트
  static/
    index.html           # 최소 프론트엔드
  tests/
    conftest.py
    fixtures/            # sample.pdf, sample.musicxml (스파이크에서 확보)
    test_config.py
    test_jobs.py
    test_audiveris.py
    test_tuxguitar.py
    test_orchestrator.py
    test_api.py
    test_integration.py  # 실도구 사용, 마커로 분리
  spikes/
    spike_audiveris.sh
    spike_tuxguitar.sh
  requirements.txt
  pyproject.toml
  Dockerfile
```

**책임 분리:** `config`(설정값), `jobs`(상태 저장), `pipeline/*`(각 변환 단계 1개씩), `worker`(실행 트리거), `main`(HTTP). 함께 바뀌는 것끼리 모음.

---

## Phase 0: 스파이크 (본 구현 전 미지수 해소)

스파이크는 외부 도구가 실제로 기대대로 동작하는지 확인한다. 통과 기준을 못 넘으면 그 자리에서 멈추고 사용자와 상의한다.

### Task 0a: Audiveris CLI 검증

**Files:**
- Create: `spikes/spike_audiveris.sh`
- Create: `tests/fixtures/sample.pdf` (MuseScore 등에서 만든 간단한 1성부 디지털 악보 PDF — 사용자 또는 구현자가 준비)

- [ ] **Step 1: Audiveris 설치 확인**

Run: `audiveris -help 2>&1 | head -20` (또는 설치된 실행 경로)
Expected: 사용법 출력. 없으면 https://github.com/Audiveris/audiveris 릴리스에서 설치.

- [ ] **Step 2: 스파이크 스크립트 작성**

```bash
#!/usr/bin/env bash
# spikes/spike_audiveris.sh
# 사용법: ./spike_audiveris.sh <input.pdf> <output_dir>
set -euo pipefail
IN="$1"; OUT="$2"
mkdir -p "$OUT"
audiveris -batch -export -output "$OUT" -- "$IN"
echo "=== 산출물 ==="
ls -la "$OUT"
echo "=== MusicXML(.mxl/.xml) 존재 확인 ==="
find "$OUT" -name '*.mxl' -o -name '*.xml'
```

- [ ] **Step 3: 실행 + 통과 기준 확인**

Run: `bash spikes/spike_audiveris.sh tests/fixtures/sample.pdf /tmp/audiveris_out`
Expected (통과 기준):
- `.mxl` 또는 `.xml` 파일이 생성된다
- 그 파일을 열었을 때 `<note>` 요소가 1개 이상 존재한다

확인: `unzip -p /tmp/audiveris_out/*.mxl '*.xml' 2>/dev/null | grep -c '<note' || grep -c '<note' /tmp/audiveris_out/*.xml`
Expected: 1 이상.

- [ ] **Step 4: 결과 기록**

스파이크 결과(정확한 실행 경로, 출력 파일 확장자가 `.mxl`인지 `.xml`인지, 압축 여부)를 `spikes/spike_audiveris.sh` 상단 주석에 기록한다. 이 값이 Task 5(audiveris 래퍼)의 실제 인터페이스가 된다.

- [ ] **Step 5: 픽스처 확정**

생성된 MusicXML을 `tests/fixtures/sample.musicxml`로 저장(압축본이면 풀어서 `.xml` 형태로). 이후 단위 테스트의 입력 픽스처로 쓴다.

```bash
git add spikes/spike_audiveris.sh tests/fixtures/sample.pdf tests/fixtures/sample.musicxml
git commit -m "spike: Audiveris PDF→MusicXML 검증 + 픽스처 확보"
```

### Task 0b: TuxGuitar 헤드리스 MusicXML→.gp5 검증 (최대 위험)

**Files:**
- Create: `spikes/spike_tuxguitar.sh`

- [ ] **Step 1: 헤드리스 변환 경로 조사**

TuxGuitar는 기본이 GUI다. 헤드리스 변환 가능 여부를 다음 순서로 확인한다.
1. TuxGuitar 설치 후 CLI 변환 인자 존재 여부: `tuxguitar --help 2>&1` 확인
2. 없으면 `xvfb-run`(가상 디스플레이)으로 GUI를 헤드리스 구동해 변환 가능한지 조사
3. 둘 다 불가하면 **이 시점에서 멈추고** B안(자체 MusicXML→.gp5 변환기)으로 전환을 사용자와 상의한다

- [ ] **Step 2: 스파이크 스크립트 작성 (경로 1 또는 2 중 확인된 방식으로)**

```bash
#!/usr/bin/env bash
# spikes/spike_tuxguitar.sh
# 사용법: ./spike_tuxguitar.sh <input.musicxml> <output.gp5>
# 주의: Step 1에서 확인한 실제 변환 방식으로 아래 명령을 채운다.
set -euo pipefail
IN="$1"; OUT="$2"
# 예시(경로 2, xvfb): xvfb-run -a tuxguitar --convert "$IN" "$OUT"
# 실제 확인된 명령으로 교체할 것
echo "TODO: Step 1에서 확정한 명령으로 교체"
exit 1
```

- [ ] **Step 3: 실행 + 통과 기준 확인**

Run: `bash spikes/spike_tuxguitar.sh tests/fixtures/sample.musicxml /tmp/out.gp5`
Expected (통과 기준):
- `/tmp/out.gp5` 파일이 생성되고 크기 > 0
- 파일 헤더가 Guitar Pro 5 시그니처로 시작: `head -c 30 /tmp/out.gp5 | xxd | head` → "FICHIER GUITAR PRO" 문자열 포함

- [ ] **Step 4: 결과 기록 / 분기 결정**

통과 → 확정된 명령을 스크립트에 고정하고 주석에 기록. 이 명령이 Task 6(tuxguitar 래퍼)의 실제 인터페이스가 된다.
실패 → 멈추고 B안 전환 상의.

```bash
git add spikes/spike_tuxguitar.sh
git commit -m "spike: TuxGuitar MusicXML→.gp5 헤드리스 변환 검증"
```

---

## Phase 1: 프로젝트 골격

### Task 1: 스캐폴드 + pytest 동작 확인

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `app/__init__.py`, `app/pipeline/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`

- [ ] **Step 1: 의존성 파일 작성**

`requirements.txt`:
```
fastapi==0.115.*
uvicorn[standard]==0.32.*
python-multipart==0.0.*
pytest==8.*
httpx==0.27.*
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "integration: 실제 외부 도구(Audiveris/TuxGuitar)를 사용하는 테스트",
]
addopts = "-m 'not integration'"
```

`app/__init__.py`, `app/pipeline/__init__.py`: 빈 파일.

- [ ] **Step 2: 스모크 테스트 작성**

`tests/test_smoke.py`:
```python
def test_smoke():
    assert True
```

- [ ] **Step 3: 환경 구성 + 실행**

Run: `python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt && pytest -v`
Expected: `test_smoke` PASS.

- [ ] **Step 4: 커밋**

```bash
git add requirements.txt pyproject.toml app/__init__.py app/pipeline/__init__.py tests/conftest.py tests/test_smoke.py
git commit -m "chore: 프로젝트 스캐폴드 + pytest 설정"
```

### Task 2: 설정 모듈

**Files:**
- Create: `app/config.py`, `tests/test_config.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_config.py`:
```python
import os
from app.config import Settings

def test_defaults():
    s = Settings()
    assert s.max_upload_bytes == 20 * 1024 * 1024
    assert s.step_timeout_sec == 300
    assert s.audiveris_cmd == "audiveris"
    assert s.tuxguitar_cmd == "tuxguitar"

def test_env_override(monkeypatch):
    monkeypatch.setenv("GPC_AUDIVERIS_CMD", "/opt/audiveris/bin/audiveris")
    s = Settings()
    assert s.audiveris_cmd == "/opt/audiveris/bin/audiveris"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_config.py -v`
Expected: FAIL (`No module named 'app.config'`).

- [ ] **Step 3: 구현**

`app/config.py`:
```python
import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    max_upload_bytes: int = field(default_factory=lambda: int(_env("GPC_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))))
    step_timeout_sec: int = field(default_factory=lambda: int(_env("GPC_STEP_TIMEOUT_SEC", "300")))
    audiveris_cmd: str = field(default_factory=lambda: _env("GPC_AUDIVERIS_CMD", "audiveris"))
    tuxguitar_cmd: str = field(default_factory=lambda: _env("GPC_TUXGUITAR_CMD", "tuxguitar"))
    jobs_dir: str = field(default_factory=lambda: _env("GPC_JOBS_DIR", "jobs"))


settings = Settings()
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_config.py -v`
Expected: 2 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: 설정 모듈(Settings) 추가"
```

---

## Phase 2: 도메인 — Job 저장소

### Task 3: Job 모델 + 파일 기반 저장소

**Files:**
- Create: `app/jobs.py`, `tests/test_jobs.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_jobs.py`:
```python
from app.jobs import JobStore, JobStatus

def test_create_and_get(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    assert job.status == JobStatus.QUEUED
    fetched = store.get(job.id)
    assert fetched.id == job.id
    assert fetched.status == JobStatus.QUEUED

def test_update_status(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    store.update(job.id, status=JobStatus.RUNNING)
    assert store.get(job.id).status == JobStatus.RUNNING
    store.update(job.id, status=JobStatus.FAILED, message="악보 인식 실패")
    got = store.get(job.id)
    assert got.status == JobStatus.FAILED
    assert got.message == "악보 인식 실패"

def test_get_missing_returns_none(tmp_path):
    store = JobStore(str(tmp_path))
    assert store.get("nope") is None

def test_workdir_created(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    import os
    assert os.path.isdir(job.workdir)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_jobs.py -v`
Expected: FAIL (`No module named 'app.jobs'`).

- [ ] **Step 3: 구현**

`app/jobs.py`:
```python
import json
import os
import uuid
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Optional


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Job:
    id: str
    status: JobStatus
    workdir: str
    message: str = ""
    result_path: str = ""


class JobStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _meta_path(self, job_id: str) -> str:
        return os.path.join(self.root, job_id, "job.json")

    def create(self) -> Job:
        job_id = uuid.uuid4().hex
        workdir = os.path.join(self.root, job_id)
        os.makedirs(workdir, exist_ok=True)
        job = Job(id=job_id, status=JobStatus.QUEUED, workdir=workdir)
        self._write(job)
        return job

    def _write(self, job: Job) -> None:
        data = asdict(job)
        data["status"] = job.status.value
        with open(self._meta_path(job.id), "w") as f:
            json.dump(data, f)

    def get(self, job_id: str) -> Optional[Job]:
        path = self._meta_path(job_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            data = json.load(f)
        data["status"] = JobStatus(data["status"])
        return Job(**data)

    def update(self, job_id: str, **fields) -> None:
        job = self.get(job_id)
        if job is None:
            raise KeyError(job_id)
        for k, v in fields.items():
            setattr(job, k, v)
        self._write(job)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_jobs.py -v`
Expected: 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/jobs.py tests/test_jobs.py
git commit -m "feat: 파일 기반 Job 저장소"
```

---

## Phase 3: 파이프라인 단계

### Task 4: Audiveris 래퍼 (pdf_to_musicxml)

**Files:**
- Create: `app/pipeline/audiveris.py`, `tests/test_audiveris.py`

> 주의: 정확한 CLI 명령/출력 확장자는 Task 0a 스파이크 결과로 확정한다. 아래는 `-batch -export -output <dir>` + `.mxl` 산출을 가정한 기본형이며, 스파이크 결과가 다르면 명령 구성과 산출물 탐색 로직을 그에 맞춰 조정한다.

- [ ] **Step 1: 실패 테스트 작성 (subprocess 모킹)**

`tests/test_audiveris.py`:
```python
import os
import pytest
from unittest.mock import patch
from app.pipeline.audiveris import pdf_to_musicxml, AudiverisError


def test_success(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        os.makedirs(out_dir, exist_ok=True)
        (out_dir / "in.mxl").write_bytes(b"PK\x03\x04fake")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        result = pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)
    assert result.endswith(".mxl")
    assert os.path.exists(result)


def test_no_output_raises(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        os.makedirs(out_dir, exist_ok=True)  # 아무 파일도 안 만듦
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        with pytest.raises(AudiverisError):
            pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)


def test_nonzero_exit_raises(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        class R: returncode = 1; stdout = b""; stderr = b"boom"
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        with pytest.raises(AudiverisError):
            pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_audiveris.py -v`
Expected: FAIL (모듈 없음).

- [ ] **Step 3: 구현**

`app/pipeline/audiveris.py`:
```python
import glob
import os
import subprocess


class AudiverisError(Exception):
    pass


def pdf_to_musicxml(pdf_path: str, out_dir: str, audiveris_cmd: str, timeout: int) -> str:
    """PDF를 MusicXML(.mxl/.xml)로 변환하고 산출 파일 경로를 반환한다."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [audiveris_cmd, "-batch", "-export", "-output", out_dir, "--", pdf_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AudiverisError("악보 인식 시간 초과") from e
    if proc.returncode != 0:
        raise AudiverisError(f"악보 인식 실패 (exit {proc.returncode})")
    matches = glob.glob(os.path.join(out_dir, "**", "*.mxl"), recursive=True) \
        + glob.glob(os.path.join(out_dir, "**", "*.xml"), recursive=True)
    if not matches:
        raise AudiverisError("악보 인식 실패: MusicXML 산출물 없음")
    return matches[0]
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_audiveris.py -v`
Expected: 3 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/audiveris.py tests/test_audiveris.py
git commit -m "feat: Audiveris PDF→MusicXML 래퍼"
```

### Task 5: TuxGuitar 래퍼 (musicxml_to_gp5)

**Files:**
- Create: `app/pipeline/tuxguitar.py`, `tests/test_tuxguitar.py`

> 주의: 정확한 변환 명령은 Task 0b 스파이크 결과로 확정한다. 아래 `_build_cmd`는 스파이크에서 확인한 실제 명령으로 맞춘다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_tuxguitar.py`:
```python
import os
import pytest
from unittest.mock import patch
from app.pipeline.tuxguitar import musicxml_to_gp5, TuxGuitarError


def test_success(tmp_path):
    xml = tmp_path / "in.xml"
    xml.write_text("<score-partwise/>")
    out = tmp_path / "out.gp5"

    def fake_run(cmd, **kwargs):
        out.write_bytes(b"FICHIER GUITAR PRO v5.00")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.tuxguitar.subprocess.run", side_effect=fake_run):
        result = musicxml_to_gp5(str(xml), str(out), tuxguitar_cmd="tuxguitar", timeout=10)
    assert result == str(out)
    assert os.path.exists(result) and os.path.getsize(result) > 0


def test_no_output_raises(tmp_path):
    xml = tmp_path / "in.xml"
    xml.write_text("<score-partwise/>")
    out = tmp_path / "out.gp5"

    def fake_run(cmd, **kwargs):
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.tuxguitar.subprocess.run", side_effect=fake_run):
        with pytest.raises(TuxGuitarError):
            musicxml_to_gp5(str(xml), str(out), tuxguitar_cmd="tuxguitar", timeout=10)


def test_nonzero_exit_raises(tmp_path):
    xml = tmp_path / "in.xml"
    xml.write_text("<score-partwise/>")
    out = tmp_path / "out.gp5"

    def fake_run(cmd, **kwargs):
        class R: returncode = 2; stdout = b""; stderr = b"err"
        return R()

    with patch("app.pipeline.tuxguitar.subprocess.run", side_effect=fake_run):
        with pytest.raises(TuxGuitarError):
            musicxml_to_gp5(str(xml), str(out), tuxguitar_cmd="tuxguitar", timeout=10)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_tuxguitar.py -v`
Expected: FAIL (모듈 없음).

- [ ] **Step 3: 구현**

`app/pipeline/tuxguitar.py`:
```python
import os
import subprocess


class TuxGuitarError(Exception):
    pass


def _build_cmd(tuxguitar_cmd: str, xml_path: str, gp5_path: str) -> list:
    # Task 0b 스파이크에서 확정한 실제 변환 명령으로 맞춘다.
    return [tuxguitar_cmd, "--convert", xml_path, gp5_path]


def musicxml_to_gp5(xml_path: str, gp5_path: str, tuxguitar_cmd: str, timeout: int) -> str:
    """MusicXML을 .gp5로 변환하고 출력 경로를 반환한다."""
    cmd = _build_cmd(tuxguitar_cmd, xml_path, gp5_path)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise TuxGuitarError("gp 생성 시간 초과") from e
    if proc.returncode != 0:
        raise TuxGuitarError(f"gp 생성 실패 (exit {proc.returncode})")
    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise TuxGuitarError("gp 생성 실패: 출력 파일 없음")
    return gp5_path
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_tuxguitar.py -v`
Expected: 3 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/tuxguitar.py tests/test_tuxguitar.py
git commit -m "feat: TuxGuitar MusicXML→.gp5 래퍼"
```

### Task 6: 오케스트레이터 (run_conversion)

**Files:**
- Create: `app/pipeline/orchestrator.py`, `tests/test_orchestrator.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_orchestrator.py`:
```python
import os
from unittest.mock import patch
from app.pipeline.orchestrator import run_conversion
from app.pipeline.audiveris import AudiverisError


def test_happy_path(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as a, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as t:
        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    assert result == str(workdir / "out.gp5")
    a.assert_called_once()
    t.assert_called_once()


def test_audiveris_failure_propagates(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", side_effect=AudiverisError("악보 인식 실패")):
        import pytest
        with pytest.raises(AudiverisError):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL (모듈 없음).

- [ ] **Step 3: 구현**

`app/pipeline/orchestrator.py`:
```python
import os
from app.pipeline.audiveris import pdf_to_musicxml
from app.pipeline.tuxguitar import musicxml_to_gp5


def run_conversion(pdf_path: str, workdir: str, audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> str:
    """PDF→MusicXML→.gp5 전 과정을 실행하고 .gp5 경로를 반환한다."""
    xml_dir = os.path.join(workdir, "xml")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)
    gp5_path = os.path.join(workdir, "output.gp5")
    return musicxml_to_gp5(xml_path, gp5_path, tuxguitar_cmd=tuxguitar_cmd, timeout=timeout)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_orchestrator.py -v`
Expected: 2 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: 변환 파이프라인 오케스트레이터"
```

---

## Phase 4: 웹 계층

### Task 7: 워커 (job 실행 + 상태 갱신)

**Files:**
- Create: `app/worker.py`, `tests/test_worker.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worker.py`:
```python
from unittest.mock import patch
from app.jobs import JobStore, JobStatus
from app.worker import process_job
from app.pipeline.audiveris import AudiverisError


def test_process_job_success(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.DONE
    assert got.result_path == "/x/output.gp5"


def test_process_job_failure(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", side_effect=AudiverisError("악보 인식 실패")):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.FAILED
    assert got.message == "악보 인식 실패"
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_worker.py -v`
Expected: FAIL (모듈 없음).

- [ ] **Step 3: 구현**

`app/worker.py`:
```python
from app.jobs import JobStore, JobStatus
from app.pipeline.orchestrator import run_conversion


def process_job(store: JobStore, job_id: str, pdf_path: str,
                audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> None:
    job = store.get(job_id)
    if job is None:
        return
    store.update(job_id, status=JobStatus.RUNNING)
    try:
        gp5_path = run_conversion(
            pdf_path, job.workdir,
            audiveris_cmd=audiveris_cmd, tuxguitar_cmd=tuxguitar_cmd, timeout=timeout,
        )
        store.update(job_id, status=JobStatus.DONE, result_path=gp5_path)
    except Exception as e:
        store.update(job_id, status=JobStatus.FAILED, message=str(e))
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_worker.py -v`
Expected: 2 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: 백그라운드 변환 워커"
```

### Task 8: FastAPI 라우트

**Files:**
- Create: `app/main.py`, `tests/test_api.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_api.py`:
```python
import io
from unittest.mock import patch
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("GPC_JOBS_DIR", str(tmp_path / "jobs"))
    import importlib
    import app.config, app.main
    importlib.reload(app.config)
    importlib.reload(app.main)
    return TestClient(app.main.app), app.main


def test_convert_rejects_non_pdf(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    r = client.post("/convert", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_convert_then_status_then_result(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)

    # 백그라운드 태스크가 즉시 동기 실행되도록 process_job을 패치
    def fake_process(store, job_id, pdf_path, **kwargs):
        gp5 = tmp_path / "r.gp5"
        gp5.write_bytes(b"FICHIER GUITAR PRO")
        store.update(job_id, status=main.JobStatus.DONE, result_path=str(gp5))

    with patch("app.main.process_job", side_effect=fake_process):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        s = client.get(f"/jobs/{job_id}")
        assert s.status_code == 200
        assert s.json()["status"] == "done"

        res = client.get(f"/jobs/{job_id}/result")
        assert res.status_code == 200
        assert res.content.startswith(b"FICHIER GUITAR PRO")


def test_status_missing_job_404(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.get("/jobs/nope").status_code == 404
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_api.py -v`
Expected: FAIL (모듈 없음).

- [ ] **Step 3: 구현**

`app/main.py`:
```python
import os
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.jobs import JobStore, JobStatus
from app.worker import process_job

app = FastAPI(title="PDF → Guitar Pro 변환기")
store = JobStore(settings.jobs_dir)


@app.post("/convert")
async def convert(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    if file.content_type != "application/pdf" and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능")
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=400, detail="파일이 너무 큽니다")

    job = store.create()
    pdf_path = os.path.join(job.workdir, "input.pdf")
    with open(pdf_path, "wb") as f:
        f.write(data)

    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
    )
    return {"job_id": job.id}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    return {"status": job.status.value, "message": job.message}


@app.get("/jobs/{job_id}/result")
async def job_result(job_id: str):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    if job.status != JobStatus.DONE or not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(status_code=409, detail="아직 결과 없음")
    return FileResponse(job.result_path, media_type="application/octet-stream", filename="score.gp5")


# 정적 프론트엔드 (Task 9에서 static/index.html 생성)
if os.path.isdir("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_api.py -v`
Expected: 4 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: FastAPI 변환/상태/결과 엔드포인트"
```

### Task 9: 최소 프론트엔드

**Files:**
- Create: `static/index.html`

- [ ] **Step 1: 페이지 작성**

`static/index.html`:
```html
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PDF → Guitar Pro 변환기</title>
</head>
<body>
  <h1>PDF → Guitar Pro 변환기</h1>
  <input type="file" id="file" accept="application/pdf" />
  <button id="go">변환</button>
  <p id="status"></p>
  <script>
    const $ = (id) => document.getElementById(id);
    $("go").onclick = async () => {
      const f = $("file").files[0];
      if (!f) { $("status").textContent = "PDF를 선택하세요"; return; }
      const fd = new FormData();
      fd.append("file", f);
      $("status").textContent = "업로드 중...";
      const r = await fetch("/convert", { method: "POST", body: fd });
      if (!r.ok) { $("status").textContent = "오류: " + (await r.json()).detail; return; }
      const { job_id } = await r.json();
      poll(job_id);
    };
    async function poll(id) {
      const r = await fetch(`/jobs/${id}`);
      const j = await r.json();
      $("status").textContent = "상태: " + j.status + (j.message ? " - " + j.message : "");
      if (j.status === "done") {
        window.location = `/jobs/${id}/result`;
      } else if (j.status === "failed") {
        // 멈춤
      } else {
        setTimeout(() => poll(id), 1500);
      }
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: 수동 확인**

Run: `. .venv/bin/activate && uvicorn app.main:app --port 8000`
브라우저에서 `http://localhost:8000` 접속 → 페이지 표시 확인. (실제 변환은 도구 설치 후 동작)

- [ ] **Step 3: 커밋**

```bash
git add static/index.html
git commit -m "feat: 최소 업로드/다운로드 프론트엔드"
```

---

## Phase 5: 통합 + 배포

### Task 10: 엔드투엔드 통합 테스트 (실도구)

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: 통합 테스트 작성 (integration 마커)**

`tests/test_integration.py`:
```python
import os
import pytest
from app.pipeline.orchestrator import run_conversion

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pdf")


@pytest.mark.integration
def test_pdf_to_gp5_real(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()
    gp5 = run_conversion(
        FIXTURE, str(workdir),
        audiveris_cmd=os.environ.get("GPC_AUDIVERIS_CMD", "audiveris"),
        tuxguitar_cmd=os.environ.get("GPC_TUXGUITAR_CMD", "tuxguitar"),
        timeout=300,
    )
    assert os.path.exists(gp5) and os.path.getsize(gp5) > 0
    with open(gp5, "rb") as f:
        head = f.read(40)
    assert b"GUITAR PRO" in head
```

- [ ] **Step 2: 실행 (도구 설치된 환경에서)**

Run: `pytest -m integration tests/test_integration.py -v`
Expected: PASS (Audiveris/TuxGuitar 설치 + 픽스처 존재 시).
도구 미설치 환경이면 이 테스트는 기본 실행(`-m 'not integration'`)에서 제외됨.

- [ ] **Step 3: 커밋**

```bash
git add tests/test_integration.py
git commit -m "test: PDF→.gp5 엔드투엔드 통합 테스트"
```

### Task 11: Dockerfile (JRE + 도구 패키징)

**Files:**
- Create: `Dockerfile`, `.dockerignore`

> 주의: Audiveris/TuxGuitar 설치 방식은 Task 0a/0b 스파이크에서 확정한 실제 설치 경로/버전으로 맞춘다. 아래는 골격이며, TuxGuitar가 xvfb 필요로 판명되면 `xvfb`와 `xvfb-run` 래핑을 추가한다.

- [ ] **Step 1: .dockerignore 작성**

`.dockerignore`:
```
.venv/
__pycache__/
jobs/
tests/
docs/
.git/
```

- [ ] **Step 2: Dockerfile 작성**

`Dockerfile`:
```dockerfile
FROM eclipse-temurin:17-jre AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

# TODO(Task 0a/0b 결과 반영): Audiveris, TuxGuitar 설치
#   - Audiveris: 릴리스 zip 다운로드/압축해제, 실행 경로를 GPC_AUDIVERIS_CMD로
#   - TuxGuitar: 설치 후 변환 명령 경로를 GPC_TUXGUITAR_CMD로
#   - xvfb 필요 시: apt-get install -y xvfb

WORKDIR /srv
COPY requirements.txt .
RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt
COPY app ./app
COPY static ./static

ENV GPC_JOBS_DIR=/srv/jobs
EXPOSE 8000
CMD ["python3", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: 빌드 확인 (도구 설치 단계 채운 뒤)**

Run: `docker build -t gp-converter .`
Expected: 빌드 성공.

- [ ] **Step 4: 커밋**

```bash
git add Dockerfile .dockerignore
git commit -m "build: Docker 이미지 (JRE + 변환 도구)"
```

---

## 자가검토 결과

- **스펙 커버리지:** 입력(디지털 표준악보 PDF)·출력(.gp5)·웹앱·비동기·에러처리·테스트·스파이크 모두 태스크로 매핑됨.
- **플레이스홀더:** 외부 도구 명령은 스파이크(Task 0a/0b)로 확정하도록 명시. 코드 단계는 전부 실제 코드 포함.
- **타입 일관성:** `JobStatus`/`Job`/`JobStore.get/update/create`, `pdf_to_musicxml`/`musicxml_to_gp5`/`run_conversion`/`process_job` 시그니처가 태스크 간 일치.
- **위험:** TuxGuitar 헤드리스(Task 0b)가 최대 미지수 — 실패 시 B안(자체 변환기) 전환을 스파이크에서 결정.
