# S3 호환 파일 저장 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 저장된 GP5 파일(`File.gp5_path`)을 로컬 디스크뿐 아니라 S3 호환 오브젝트 스토리지(AWS S3, MinIO, R2 등)에도 저장할 수 있도록 추상화한다.

**Architecture:** `app/storage.py`에 `Storage` 프로토콜 + `LocalStorage`(기존 동작과 100% 동일) + `S3Storage`(boto3, `endpoint_url` 커스터마이즈로 특정 클라우드에 안 묶임) 두 구현체를 만들고, `File.gp5_path`를 직접 `os.path.*`/`FileResponse(path)`로 다루던 5개 파일(worker/export/edit/share/files)을 이 추상화 경유로 바꾼다. `STORAGE_BACKEND=local|s3` 환경변수로 전환, 기본값 `local`.

**Tech Stack:** FastAPI, boto3, pytest

## Global Constraints

- 범위는 **저장된 GP5 파일만**(`File.gp5_path`) — 변환 작업 중 임시파일(PDF/XML/output.gp5)은 그대로 로컬 디스크, 범위 밖
- `STORAGE_BACKEND=local|s3`, 기본값 `local` — 로컬 개발은 계정 없이 지금처럼 그대로 동작해야 함
- S3 자격증명은 boto3 표준 환경변수(`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_REGION`) 그대로, 커스텀 이름 안 만듦
- 기존 PyGuitarPro/mido 기반 파이프라인 함수(`gp5_to_midi`, `snapshot_to_gp5`)는 손대지 않는다 — 항상 실제 로컬 경로를 받는다는 전제 유지
- `LocalStorage`는 기존 동작과 완전히 동일해야 한다 — 이 회귀 없음이 이 계획 전체의 안전망
- 테스트는 `boto3` client를 `unittest.mock`으로 목킹(Stripe SDK와 동일 컨벤션) — `moto` 등 별도 라이브러리 안 씀. `S3_*` 환경변수 없어도 전체 스위트 통과
- 백엔드 전환 시 기존 저장 파일 마이그레이션 도구 없음(YAGNI)
- 스펙 문서: `docs/superpowers/specs/2026-07-03-s3-file-storage-design.md`

---

### Task 1: Storage 추상화 (`app/storage.py`)

**Files:**
- Create: `app/storage.py`
- Modify: `requirements.txt`
- Test: `tests/test_storage.py`

**Interfaces:**
- Produces: `Storage` 프로토콜(6개 메서드), `LocalStorage`, `S3Storage`, `get_storage() -> Storage` — Task 2~4가 전부 `from app.storage import get_storage`만 가져다 씀
  - `key_for(file_id: str, local_path: str) -> str` — **새 파일**을 처음 저장할 때 쓸 키를 만든다(로컬은 `local_path` 그대로, S3는 `f"{file_id}.gp5"`). 기존 파일을 덮어쓸 때(Task 4의 edit.py)는 이 메서드를 안 쓰고 이미 있는 `f.gp5_path`를 키로 재사용한다.
  - `save_file(key: str, local_path: str) -> None` — `local_path`의 내용을 `key` 위치에 저장. `key == local_path`면(새 파일을 로컬 백엔드에 처음 저장하는 경우) no-op.
  - `load_to_temp(key: str) -> str` — **항상 새로 만든 임시파일 경로**를 반환한다(로컬이어도 복사본). 호출자가 다 쓰고 나서 `os.unlink`로 정리할 책임을 진다 — 백엔드가 뭐든 이 규칙은 동일하다(원본을 실수로 지우는 사고 방지).
  - `exists(key: str) -> bool`, `delete(key: str) -> None`
  - `response_for(key: str, filename: str) -> Response` — 다운로드 응답을 만든다(로컬은 바로 `FileResponse`, S3는 `load_to_temp` 후 `BackgroundTask`로 정리)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_storage.py` (신규):

```python
import os
from unittest.mock import MagicMock, patch

import pytest

from app.storage import LocalStorage, S3Storage, get_storage


class TestLocalStorage:
    def test_key_for_returns_local_path_unchanged(self, tmp_path):
        storage = LocalStorage()
        local_path = str(tmp_path / "output.gp5")
        assert storage.key_for("file-1", local_path) == local_path

    def test_save_file_noop_when_key_equals_local_path(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        path.write_bytes(b"GP5DATA")
        storage.save_file(str(path), str(path))
        assert path.read_bytes() == b"GP5DATA"

    def test_save_file_copies_when_key_differs(self, tmp_path):
        storage = LocalStorage()
        src = tmp_path / "src.gp5"
        src.write_bytes(b"NEWDATA")
        dst = tmp_path / "dst.gp5"
        dst.write_bytes(b"OLDDATA")
        storage.save_file(str(dst), str(src))
        assert dst.read_bytes() == b"NEWDATA"
        assert src.read_bytes() == b"NEWDATA"  # 원본은 호출자가 정리하기 전까지 그대로

    def test_load_to_temp_returns_disposable_copy_not_original(self, tmp_path):
        storage = LocalStorage()
        original = tmp_path / "output.gp5"
        original.write_bytes(b"GP5DATA")

        tmp_result = storage.load_to_temp(str(original))
        try:
            assert tmp_result != str(original)
            with open(tmp_result, "rb") as f:
                assert f.read() == b"GP5DATA"
            assert original.exists()
        finally:
            os.unlink(tmp_result)

    def test_exists(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        assert storage.exists(str(path)) is False
        path.write_bytes(b"x")
        assert storage.exists(str(path)) is True

    def test_delete(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        path.write_bytes(b"x")
        storage.delete(str(path))
        assert not path.exists()

    def test_response_for_returns_file_response(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        path.write_bytes(b"GP5DATA")
        response = storage.response_for(str(path), filename="score.gp5")
        assert response.path == str(path)
        assert response.filename == "score.gp5"


class TestS3Storage:
    def test_key_for_ignores_local_path(self):
        with patch("boto3.client"):
            storage = S3Storage(bucket="my-bucket")
        assert storage.key_for("file-42", "/tmp/anything.gp5") == "file-42.gp5"

    def test_save_file_uploads(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            storage.save_file("file-42.gp5", "/tmp/local.gp5")
        mock_client.upload_file.assert_called_once_with("/tmp/local.gp5", "my-bucket", "file-42.gp5")

    def test_load_to_temp_downloads(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            result = storage.load_to_temp("file-42.gp5")
        try:
            args = mock_client.download_file.call_args[0]
            assert args[0] == "my-bucket"
            assert args[1] == "file-42.gp5"
            assert args[2] == result
        finally:
            os.unlink(result)

    def test_exists_true(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            assert storage.exists("file-42.gp5") is True
        mock_client.head_object.assert_called_once_with(Bucket="my-bucket", Key="file-42.gp5")

    def test_exists_false_on_404(self):
        from botocore.exceptions import ClientError
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.head_object.side_effect = ClientError(
                {"Error": {"Code": "404"}}, "HeadObject"
            )
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            assert storage.exists("file-42.gp5") is False

    def test_delete(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            storage.delete("file-42.gp5")
        mock_client.delete_object.assert_called_once_with(Bucket="my-bucket", Key="file-42.gp5")

    def test_response_for_downloads_then_serves_with_cleanup(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            response = storage.response_for("file-42.gp5", filename="score.gp5")
        assert response.filename == "score.gp5"
        assert response.background is not None
        os.unlink(response.path)  # 테스트에선 실제 응답 전송이 없어 BackgroundTask가 안 실행됨


class TestGetStorage:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        assert isinstance(get_storage(), LocalStorage)

    def test_s3_backend_requires_bucket_name(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
        with pytest.raises(ValueError, match="S3_BUCKET_NAME"):
            get_storage()

    def test_s3_backend_returns_s3_storage(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_BUCKET_NAME", "my-bucket")
        with patch("boto3.client"):
            storage = get_storage()
        assert isinstance(storage, S3Storage)
        assert storage._bucket == "my-bucket"

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "azure")
        with pytest.raises(ValueError, match="azure"):
            get_storage()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: `ModuleNotFoundError: No module named 'app.storage'`

- [ ] **Step 3: requirements.txt에 boto3 추가**

`requirements.txt` 끝에 추가:

```
boto3>=1.34,<2
```

Run: `pip install "boto3>=1.34,<2"` (anaconda 기본 python 환경에)

- [ ] **Step 4: storage.py 구현**

`app/storage.py` (신규):

```python
import os
import shutil
import tempfile
from typing import Optional, Protocol

import boto3
from fastapi import Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


class Storage(Protocol):
    def key_for(self, file_id: str, local_path: str) -> str: ...
    def save_file(self, key: str, local_path: str) -> None: ...
    def load_to_temp(self, key: str) -> str: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def response_for(self, key: str, filename: str) -> Response: ...


class LocalStorage:
    """key == 로컬 파일시스템 경로. 기존(추상화 이전) 동작과 완전히 동일하다."""

    def key_for(self, file_id: str, local_path: str) -> str:
        return local_path

    def save_file(self, key: str, local_path: str) -> None:
        if os.path.abspath(key) != os.path.abspath(local_path):
            shutil.copy(local_path, key)

    def load_to_temp(self, key: str) -> str:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".gp5")
        os.close(tmp_fd)
        shutil.copy(key, tmp_path)
        return tmp_path

    def exists(self, key: str) -> bool:
        return os.path.exists(key)

    def delete(self, key: str) -> None:
        os.remove(key)

    def response_for(self, key: str, filename: str) -> Response:
        return FileResponse(key, media_type="application/octet-stream", filename=filename)


class S3Storage:
    """S3 호환 오브젝트 스토리지. endpoint_url을 지정하면 AWS가 아닌 다른 서비스
    (MinIO, Cloudflare R2 등)로도 붙을 수 있다."""

    def __init__(self, bucket: str, endpoint_url: Optional[str] = None):
        self._bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def key_for(self, file_id: str, local_path: str) -> str:
        return f"{file_id}.gp5"

    def save_file(self, key: str, local_path: str) -> None:
        self._client.upload_file(local_path, self._bucket, key)

    def load_to_temp(self, key: str) -> str:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".gp5")
        os.close(tmp_fd)
        self._client.download_file(self._bucket, key, tmp_path)
        return tmp_path

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def response_for(self, key: str, filename: str) -> Response:
        tmp_path = self.load_to_temp(key)
        return FileResponse(
            tmp_path,
            media_type="application/octet-stream",
            filename=filename,
            background=BackgroundTask(os.unlink, tmp_path),
        )


def get_storage() -> "Storage":
    """STORAGE_BACKEND 환경변수(기본 local)로 백엔드 선택."""
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalStorage()
    if backend == "s3":
        bucket = os.getenv("S3_BUCKET_NAME")
        if not bucket:
            raise ValueError(
                "STORAGE_BACKEND=s3인데 S3_BUCKET_NAME 환경변수가 없습니다."
            )
        endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
        return S3Storage(bucket=bucket, endpoint_url=endpoint_url)
    raise ValueError(f"알 수 없는 STORAGE_BACKEND: {backend!r}")
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_storage.py -v`
Expected: 18 passed

- [ ] **Step 6: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 기존 211 + 신규 18 = 229 passed

- [ ] **Step 7: 커밋**

```bash
git add app/storage.py requirements.txt tests/test_storage.py
git commit -m "feat: S3 호환 파일 스토리지 추상화 (Storage/LocalStorage/S3Storage)"
```

---

### Task 2: worker.py 저장 경로 전환

**Files:**
- Modify: `app/worker.py`
- Test: `tests/test_worker.py`

**Interfaces:**
- Consumes: `app.storage.get_storage()`, `Storage.key_for()`, `Storage.save_file()` (Task 1)
- Produces: 없음(내부 구현 변경) — `_update_file_gp5_path`의 외부 시그니처는 무변경이라 다른 태스크가 알아야 할 게 없음

**중요:** `LocalStorage`가 "기존 동작과 완전히 동일"하다는 Task 1의 설계 덕분에, `tests/test_worker.py`의 기존 3개 테스트는 **한 글자도 안 고쳐도 그대로 통과**해야 한다(회귀 안전망). 이 태스크는 새 통합 지점(`_update_file_gp5_path`가 실제로 `storage.key_for`/`storage.save_file`을 호출하는지)만 신규 테스트로 고정한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worker.py` 끝에 추가:

```python
def test_update_file_gp5_path_uses_storage_key_for_and_save_file(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.database import SessionLocal
    from app.models import User, File
    from app.worker import _update_file_gp5_path

    db = SessionLocal()
    db.merge(User(id="w-u5", email="w5@x.com", provider="google", provider_id="w-u5"))
    db.merge(File(id="w-f5", user_id="w-u5", name="test", gp5_path=""))
    db.commit()
    db.close()

    fake_storage = MagicMock()
    fake_storage.key_for.return_value = "custom-key.gp5"

    with patch("app.worker.get_storage", return_value=fake_storage):
        _update_file_gp5_path("w-f5", "/tmp/local-output.gp5")

    fake_storage.key_for.assert_called_once_with("w-f5", "/tmp/local-output.gp5")
    fake_storage.save_file.assert_called_once_with("custom-key.gp5", "/tmp/local-output.gp5")

    db = SessionLocal()
    updated = db.query(File).filter_by(id="w-f5").first()
    assert updated.gp5_path == "custom-key.gp5"
    db.close()
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_worker.py -v`
Expected: `test_update_file_gp5_path_uses_storage_key_for_and_save_file`가 `ModuleNotFoundError`/`AttributeError`(`app.worker`에 `get_storage`가 아직 없음)로 실패. 기존 3개 테스트는 여전히 통과(아직 코드 안 바꿨으므로).

- [ ] **Step 3: worker.py에 storage 연동**

`app/worker.py`의 `_update_file_gp5_path` 함수를:

```python
def _update_file_gp5_path(file_id: str, gp5_path: str) -> None:
    from app.database import SessionLocal
    from app.models import File

    db = SessionLocal()
    try:
        f = db.query(File).filter_by(id=file_id).first()
        if f is not None:
            f.gp5_path = gp5_path
            db.commit()
    finally:
        db.close()
```

로 교체:

```python
def _update_file_gp5_path(file_id: str, local_gp5_path: str) -> None:
    from app.database import SessionLocal
    from app.models import File
    from app.storage import get_storage

    storage = get_storage()
    db = SessionLocal()
    try:
        f = db.query(File).filter_by(id=file_id).first()
        if f is not None:
            key = storage.key_for(file_id, local_gp5_path)
            storage.save_file(key, local_gp5_path)
            f.gp5_path = key
            db.commit()
    finally:
        db.close()
```

(`process_job` 함수 자체는 변경 없음 — `_update_file_gp5_path(file_id, gp5_path)` 호출부 그대로 둔다.)

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_worker.py -v`
Expected: 6 passed (기존 5개 + 신규 1개)

- [ ] **Step 5: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 230 passed (Task 1의 229 + 신규 1)

- [ ] **Step 6: 커밋**

```bash
git add app/worker.py tests/test_worker.py
git commit -m "feat: worker.py가 Storage 경유로 변환결과 저장"
```

---

### Task 3: export.py + share.py 다운로드 경로 전환

**Files:**
- Modify: `app/routers/export.py`
- Modify: `app/routers/share.py`
- Test: `tests/test_export.py`
- Test: `tests/test_share.py`

**Interfaces:**
- Consumes: `app.storage.get_storage()`, `Storage.exists()`, `Storage.load_to_temp()`, `Storage.response_for()` (Task 1)

**중요:** `tests/test_export.py`/`tests/test_share.py`의 기존 테스트는 전부 `LocalStorage` 경로를 타므로 **한 글자도 안 고쳐도 통과**해야 한다(회귀 안전망). 이 태스크는 각 엔드포인트가 실제로 `get_storage()`를 거치는지 확인하는 신규 "위임(delegation)" 테스트만 추가한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_export.py` 끝에 추가 (기존 `_setup_user_file` 헬퍼 재사용, `from starlette.responses import Response`를 파일 상단 import에 추가):

```python
class TestStorageDelegation:
    def test_download_gp5_delegates_to_storage(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        fake_storage = MagicMock()
        fake_storage.exists.return_value = True
        fake_storage.response_for.return_value = Response(
            content=b"FAKE", media_type="application/octet-stream"
        )

        with patch("app.routers.export.get_storage", return_value=fake_storage):
            resp = client.get("/files/f1/download",
                              headers={"Authorization": f"Bearer {_tok('u1')}"})

        assert resp.status_code == 200
        fake_storage.exists.assert_called_once()
        fake_storage.response_for.assert_called_once()

    def test_export_midi_delegates_to_storage_load_to_temp(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        # load_to_temp는 실제로는 항상 새로 만든 사본을 반환한다(원본을 건드리면 안 됨) —
        # 엔드포인트가 다 쓰고 os.unlink로 지우므로, mock도 반드시 별도 파일을 줘야 한다.
        fake_gp5_copy = tmp_path / "fake_copy.gp5"
        fake_gp5_copy.write_bytes(b"GP5DATA")

        fake_storage = MagicMock()
        fake_storage.exists.return_value = True
        fake_storage.load_to_temp.return_value = str(fake_gp5_copy)

        with patch("app.routers.export.get_storage", return_value=fake_storage):
            resp = client.get("/files/f1/export/midi",
                              headers={"Authorization": f"Bearer {_tok('u1')}"})

        assert resp.status_code == 422  # 가짜 GP5DATA라 MIDI 변환은 실패하지만, 위임 자체는 확인됨
        fake_storage.load_to_temp.assert_called_once()
```

`tests/test_share.py` 끝에 추가:

```python
class TestStorageDelegation:
    def test_get_shared_gp5_delegates_to_storage(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f-storage")
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        created = client.post("/files/f-storage/share", json={}, headers=headers).json()

        fake_storage = MagicMock()
        fake_storage.exists.return_value = True
        fake_storage.response_for.return_value = Response(
            content=b"FAKE", media_type="application/octet-stream"
        )

        with patch("app.routers.share.get_storage", return_value=fake_storage):
            resp = client.get(f"/files/shared/{created['token']}")

        assert resp.status_code == 200
        fake_storage.response_for.assert_called_once()
```

(`test_share.py`에 `_setup_user_file` 헬퍼가 이미 있는지 확인 — 있으면 그대로 재사용, `_tok`/`client` 등 기존 픽스처도 그대로 재사용.)

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_export.py tests/test_share.py -v`
Expected: `TestStorageDelegation`의 3개 테스트가 `AttributeError`(각 라우터 모듈에 `get_storage`가 아직 없음)로 실패. 기존 테스트는 전부 통과.

- [ ] **Step 3: export.py 전환**

`app/routers/export.py` 전체를 아래로 교체:

```python
import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from starlette.background import BackgroundTask
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
from app.pipeline.midi_export import gp5_to_midi
from app.storage import get_storage

router = APIRouter(prefix="/files", tags=["export"])


@router.get("/{file_id}/download")
def download_gp5(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GP5 파일 다운로드."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    storage = get_storage()
    if not f.gp5_path or not storage.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")
    return storage.response_for(f.gp5_path, filename=f"{f.name}.gp5")


@router.get("/{file_id}/export/midi")
def export_midi(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GP5 → MIDI 변환 후 다운로드."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    storage = get_storage()
    if not f.gp5_path or not storage.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")

    local_gp5_path = storage.load_to_temp(f.gp5_path)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mid")
    os.close(tmp_fd)
    try:
        gp5_to_midi(local_gp5_path, tmp_path)
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=422, detail=f"MIDI 변환 실패: {e}")
    finally:
        os.unlink(local_gp5_path)

    return FileResponse(
        tmp_path,
        media_type="audio/midi",
        filename=f"{f.name}.mid",
        background=BackgroundTask(os.unlink, tmp_path),
    )
```

- [ ] **Step 4: share.py 전환**

`app/routers/share.py` 맨 위 import에 추가:

```python
from app.storage import get_storage
```

`import os`와 `from fastapi.responses import FileResponse` 줄은 삭제(더 이상 직접 안 씀).

파일 끝의 `get_shared_gp5` 함수:

```python
@router.get("/shared/{token}")
def get_shared_gp5(token: str, db: Session = Depends(get_db)):
    """공유 토큰으로 GP5 파일 조회 — 인증 불필요."""
    f = db.query(File).filter_by(shared_token=token).first()
    if f is None:
        raise HTTPException(status_code=404, detail="유효하지 않은 링크")
    if f.shared_expires_at is not None:
        if datetime.now(timezone.utc) > _as_utc(f.shared_expires_at):
            raise HTTPException(status_code=404, detail="링크가 만료되었습니다")
    if not f.gp5_path or not os.path.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")
    return FileResponse(f.gp5_path, media_type="application/octet-stream")
```

을 아래로 교체:

```python
@router.get("/shared/{token}")
def get_shared_gp5(token: str, db: Session = Depends(get_db)):
    """공유 토큰으로 GP5 파일 조회 — 인증 불필요."""
    f = db.query(File).filter_by(shared_token=token).first()
    if f is None:
        raise HTTPException(status_code=404, detail="유효하지 않은 링크")
    if f.shared_expires_at is not None:
        if datetime.now(timezone.utc) > _as_utc(f.shared_expires_at):
            raise HTTPException(status_code=404, detail="링크가 만료되었습니다")
    storage = get_storage()
    if not f.gp5_path or not storage.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")
    return storage.response_for(f.gp5_path, filename=f"{f.name}.gp5")
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_export.py tests/test_share.py -v`
Expected: 전부 통과(기존 + 신규 3개)

- [ ] **Step 6: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 233 passed (Task 2의 230 + 신규 3)

- [ ] **Step 7: 커밋**

```bash
git add app/routers/export.py app/routers/share.py tests/test_export.py tests/test_share.py
git commit -m "feat: export.py/share.py 다운로드가 Storage 경유"
```

---

### Task 4: edit.py 재저장 + files.py 삭제 전환 + 문서화

**Files:**
- Modify: `app/routers/edit.py`
- Modify: `app/routers/files.py`
- Modify: `README.md`
- Test: `tests/test_edit.py`
- Test: `tests/test_files.py` (신규 — 기존에 `delete_file` 엔드포인트 테스트가 전혀 없었음)

**Interfaces:**
- Consumes: `app.storage.get_storage()`, `Storage.save_file()`, `Storage.exists()`, `Storage.delete()` (Task 1)
- Produces: 없음(최종 통합 지점)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_edit.py` 끝에 추가:

```python
def test_sync_delegates_to_storage_save_file():
    from unittest.mock import MagicMock, patch
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    user = User(id="u2", email="edit-storage@x.com", provider="google", provider_id="x")
    file = File(id="f-storage-edit", user_id="u2", name="test", gp5_path="existing-key.gp5")
    db.merge(user); db.merge(file); db.commit()
    db.close()

    token = _make_token("u2")
    fake_storage = MagicMock()

    with patch("app.routers.edit.snapshot_to_gp5"), \
         patch("app.routers.edit.get_storage", return_value=fake_storage):
        resp = client.post(
            "/files/f-storage-edit/sync",
            content=json.dumps(VALID_SNAPSHOT),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )

    assert resp.status_code == 200
    fake_storage.save_file.assert_called_once()
    call_args = fake_storage.save_file.call_args[0]
    assert call_args[0] == "existing-key.gp5"  # 기존 키 그대로 재사용(key_for 안 씀)
```

`tests/test_files.py` (신규):

```python
from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user_file(db, tmp_path, uid="fu1", fid="ff1"):
    from app.models import User, File
    path = str(tmp_path / f"{fid}.gp5")
    with open(path, "wb") as f:
        f.write(b"GP5DATA")
    db.merge(User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid))
    db.merge(File(id=fid, user_id=uid, name="test", gp5_path=path))
    db.commit()
    return path


def test_delete_file_204(tmp_path):
    from app.database import SessionLocal
    db = SessionLocal()
    _setup_user_file(db, tmp_path)
    db.close()

    resp = client.delete("/files/ff1", headers={"Authorization": f"Bearer {_tok('fu1')}"})
    assert resp.status_code == 204


def test_delete_file_delegates_to_storage(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.database import SessionLocal
    db = SessionLocal()
    _setup_user_file(db, tmp_path, uid="fu2", fid="ff2")
    db.close()

    fake_storage = MagicMock()
    fake_storage.exists.return_value = True

    with patch("app.routers.files.get_storage", return_value=fake_storage):
        resp = client.delete("/files/ff2", headers={"Authorization": f"Bearer {_tok('fu2')}"})

    assert resp.status_code == 204
    fake_storage.exists.assert_called_once()
    fake_storage.delete.assert_called_once()


def test_delete_file_404_missing():
    resp = client.delete("/files/nonexistent", headers={"Authorization": f"Bearer {_tok('fu1')}"})
    assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_edit.py tests/test_files.py -v`
Expected: 신규 테스트들이 `AttributeError`(`app.routers.edit`/`app.routers.files`에 `get_storage` 아직 없음)로 실패

- [ ] **Step 3: edit.py 전환**

`app/routers/edit.py` 맨 위 import에 추가:

```python
from app.storage import get_storage
```

`sync_file` 함수 본문:

```python
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix='.gp5', dir=os.path.dirname(f.gp5_path))
        try:
            os.close(tmp_fd)
            snapshot_to_gp5(snapshot, tmp_path)
            os.replace(tmp_path, f.gp5_path)
        except Exception:
            os.unlink(tmp_path)
            raise
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"ok": True}
```

을 아래로 교체:

```python
    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.gp5')
    os.close(tmp_fd)
    try:
        try:
            snapshot_to_gp5(snapshot, tmp_path)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(status_code=422, detail=str(e))

        storage = get_storage()
        storage.save_file(f.gp5_path, tmp_path)
    finally:
        os.unlink(tmp_path)

    return {"ok": True}
```

- [ ] **Step 4: files.py 전환**

`app/routers/files.py` 맨 위 import를:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
import os
```

을 아래로 교체:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
from app.storage import get_storage
```

`delete_file` 함수:

```python
@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter_by(id=file_id, user_id=user.id).first()
    if not f:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.gp5_path and os.path.exists(f.gp5_path):
        os.remove(f.gp5_path)
    db.delete(f)
    db.commit()
```

을 아래로 교체:

```python
@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter_by(id=file_id, user_id=user.id).first()
    if not f:
        raise HTTPException(status_code=404, detail="파일 없음")
    storage = get_storage()
    if f.gp5_path and storage.exists(f.gp5_path):
        storage.delete(f.gp5_path)
    db.delete(f)
    db.commit()
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_edit.py tests/test_files.py -v`
Expected: 전부 통과

- [ ] **Step 6: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 237 passed (Task 3의 233 + 신규 4: test_edit.py 1개 + test_files.py 3개)

- [ ] **Step 7: README 문서화**

`README.md`의 "환경변수" 표에서, `CELERY_BROKER_URL` 행 다음에 추가:

```markdown
| `STORAGE_BACKEND` | `local` | 파일 저장 백엔드: `local` 또는 `s3` |
| `S3_BUCKET_NAME` | 없음(s3일 때 필수) | S3 버킷 이름 |
| `S3_ENDPOINT_URL` | 없음(비우면 AWS) | MinIO/R2 등 비-AWS S3 호환 엔드포인트 |
```

`README.md`의 "프로젝트 구조" 코드블록에서, `jobs.py` 줄 다음에 추가:

```
  storage.py             # 파일 저장 추상화 (local/S3)
```

`README.md`의 "알려진 한계" 섹션 끝에 추가:

```markdown
- `STORAGE_BACKEND`을 바꾸면(local↔s3) 이미 저장된 기존 파일은 자동 이관되지 않는다. 필요하면 수동으로 옮겨야 한다.
```

- [ ] **Step 8: 커밋**

```bash
git add app/routers/edit.py app/routers/files.py README.md tests/test_edit.py tests/test_files.py
git commit -m "feat: edit.py/files.py가 Storage 경유 + S3 스토리지 README 문서화"
```

---

## 최종 검증 (전체 태스크 완료 후)

- [ ] Run: `python -m pytest -q` — 전체 백엔드 통과 (기존 211 + 신규 = Task1(18)+Task2(1)+Task3(3)+Task4(4)=26 → 총 237)
- [ ] Run: `python -c "import boto3; print('boto3 OK')"` — 설치 확인
- [ ] 수동 확인(선택, S3/MinIO 계정 있으면): `STORAGE_BACKEND=s3 S3_BUCKET_NAME=... S3_ENDPOINT_URL=... uvicorn app.main:app`으로 띄운 뒤 PDF 업로드 → 변환 성공 → 다운로드/편집/삭제/공유 전부 정상 동작하는지 확인
