# 공유 링크 기능 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 로그인 없이 URL 하나로 특정 파일 악보를 읽기전용(보기+재생)으로 열람할 수 있는 공유 링크 기능을 만든다.

**Architecture:** `File` 테이블에 `shared_token`/`shared_expires_at` 컬럼을 추가하고, 소유자용 CRUD 라우터(`/files/{file_id}/share`)와 공개 조회 라우터(`/files/shared/{token}`)를 만든다. 프론트는 `ShareModal`(생성/관리 UI)과 독립적인 `SharedScoreViewer`(공개 뷰어, 기존 편집 스토어와 완전 분리)를 추가한다.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 (SQLite), pytest / React 18, TypeScript, react-router-dom, vitest

## Global Constraints

- 만료 정책: 생성 시 `expires_in_days`를 `7`(기본값) / `30` / `null`(무기한) 중 선택
- 파일당 활성 링크 1개 — 재생성 시 기존 토큰 자동 무효화
- 공유 페이지는 보기+재생만, 편집/다운로드 불가
- SQLite 스키마 변경은 `ALTER TABLE ADD COLUMN` 가드로 처리 — 기존 DB 데이터(업로드 파일, 유저) 보존, `create_all()`/DB 재생성 방식 금지
- 공개 API 경로는 `/files/shared/{token}` (프론트 페이지 경로 `/share/:token`과 겹치지 않도록 `/files` 프리픽스 유지)
- 신규 프론트 컴포넌트는 기존 코드베이스처럼 최소 인라인 스타일만 사용 — 디자인 폴리싱 금지(사용자가 추후 직접 작업)
- 스펙 문서: `docs/superpowers/specs/2026-07-01-shared-link-design.md`

---

### Task 1: File 모델 컬럼 추가 + SQLite 마이그레이션 가드

**Files:**
- Modify: `app/models.py` (File 클래스)
- Modify: `app/database.py`
- Modify: `app/main.py:27-28`
- Test: `tests/test_database_migration.py` (신규)

**Interfaces:**
- Produces: `app.database.run_sqlite_migrations(engine) -> None` — 이후 모든 태스크가 앱 시작 시 이 함수가 호출된다는 것을 전제로 함
- Produces: `File.shared_token: str | None`, `File.shared_expires_at: datetime | None` — Task 2/3에서 사용

- [ ] **Step 1: 마이그레이션 가드 실패 테스트 작성**

`tests/test_database_migration.py`:

```python
import sqlalchemy as sa
from app.database import run_sqlite_migrations


def test_migration_adds_missing_columns(tmp_path):
    """구버전 files 테이블(신규 컬럼 없음)에 컬럼을 추가한다."""
    db_path = tmp_path / "old.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files ("
            "id VARCHAR PRIMARY KEY, user_id VARCHAR, name VARCHAR, "
            "gp5_path VARCHAR, created_at DATETIME, updated_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(files)"))}
    assert "shared_token" in cols
    assert "shared_expires_at" in cols


def test_migration_idempotent_on_new_schema(tmp_path):
    """신규 컬럼이 이미 있는 테이블에 다시 실행해도 에러 없이 통과한다."""
    db_path = tmp_path / "new.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files (id VARCHAR PRIMARY KEY, "
            "shared_token VARCHAR, shared_expires_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)  # 에러 없이 통과해야 함

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(files)"))}
    assert "shared_token" in cols
    assert "shared_expires_at" in cols


def test_migration_noop_on_non_sqlite(tmp_path):
    """sqlite가 아닌 dialect면 아무 것도 하지 않는다 (postgres 등 향후 대비)."""
    class FakeDialect:
        name = "postgresql"

    class FakeEngine:
        dialect = FakeDialect()
        def connect(self):
            raise AssertionError("postgres에서는 connect가 호출되면 안 됨")

    run_sqlite_migrations(FakeEngine())  # 예외 없이 그냥 리턴
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_database_migration.py -v`
Expected: `ImportError: cannot import name 'run_sqlite_migrations' from 'app.database'`

- [ ] **Step 3: File 모델에 컬럼 추가**

`app/models.py` — `File` 클래스에 라인 추가 (기존 `updated_at` 다음 줄):

```python
class File(Base):
    __tablename__ = "files"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    gp5_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    shared_token = Column(String, unique=True, nullable=True, index=True)
    shared_expires_at = Column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 4: 마이그레이션 가드 함수 구현**

`app/database.py` 전체를 아래로 교체:

```python
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./gp_converter.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_sqlite_migrations(engine) -> None:
    """create_all()이 커버하지 못하는 기존 테이블 컬럼 추가.

    Alembic 없이 운영하는 프로젝트라, 기존 files 테이블에 새 컬럼이 생길 때마다
    여기에 (컬럼명, DDL타입) 쌍을 추가한다. 기존 행 데이터는 보존된다.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(files)"))}
        if "shared_token" not in cols:
            conn.execute(text("ALTER TABLE files ADD COLUMN shared_token VARCHAR"))
        if "shared_expires_at" not in cols:
            conn.execute(text("ALTER TABLE files ADD COLUMN shared_expires_at DATETIME"))
        conn.commit()
```

- [ ] **Step 5: main.py에서 마이그레이션 가드 호출**

`app/main.py:27-28`를 아래로 교체:

```python
# DB 테이블 자동 생성 + 기존 테이블 컬럼 마이그레이션
from app.database import run_sqlite_migrations
Base.metadata.create_all(bind=engine)
run_sqlite_migrations(engine)
```

- [ ] **Step 6: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_database_migration.py -v`
Expected: 3 passed

- [ ] **Step 7: 기존 테스트 전체 회귀 확인**

Run: `python -m pytest -q`
Expected: 기존 163개 + 신규 3개 = 166 passed (신규 db 파일 `gp_converter.db`가 로컬에 이미 있다면 이 스텝에서 실제로 `shared_token` 컬럼이 추가됨 — 정상)

- [ ] **Step 8: 커밋**

```bash
git add app/models.py app/database.py app/main.py tests/test_database_migration.py
git commit -m "feat: File 모델에 공유 링크 컬럼 추가 + SQLite 마이그레이션 가드"
```

---

### Task 2: 공유 링크 생성/조회/삭제 API (소유자)

**Files:**
- Create: `app/routers/share.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/test_share.py` (신규)

**Interfaces:**
- Consumes: `File.shared_token`, `File.shared_expires_at` (Task 1)
- Produces: `POST /files/{file_id}/share`, `GET /files/{file_id}/share`, `DELETE /files/{file_id}/share` — Task 3(공개 엔드포인트)이 같은 라우터 파일에 이어서 작성됨. 응답 스키마 `{"token": str | None, "expires_at": str | None}` (ISO8601 or null) — Task 4 프론트 `ShareInfo` 타입이 이 형태를 그대로 따름

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_share.py`:

```python
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user_file(db, tmp_path, uid="u1", fid="f1"):
    from app.models import User, File
    path = str(tmp_path / f"{fid}.gp5")
    with open(path, "wb") as f:
        f.write(b"GP5DATA")
    user = User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid)
    file = File(id=fid, user_id=uid, name="my_song", gp5_path=path)
    db.merge(user); db.merge(file); db.commit()
    return file


class TestCreateShareLink:
    def test_200_default_7days(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        resp = client.post("/files/f1/share", json={},
                            headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["token"]
        assert body["expires_at"] is not None

        db = SessionLocal()
        from app.models import File
        f = db.query(File).filter_by(id="f1").first()
        assert f.shared_token == body["token"]
        db.close()

    def test_200_infinite(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        resp = client.post("/files/f1/share", json={"expires_in_days": None},
                            headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 200
        assert resp.json()["expires_at"] is None

    def test_replaces_existing_token(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        first = client.post("/files/f1/share", json={}, headers=headers).json()
        second = client.post("/files/f1/share", json={}, headers=headers).json()
        assert first["token"] != second["token"]

    def test_422_invalid_expires_in_days(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        resp = client.post("/files/f1/share", json={"expires_in_days": 14},
                            headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 422

    def test_403_wrong_user(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.merge(User(id="u2", email="b@x.com", provider="google", provider_id="u2"))
        db.commit(); db.close()

        resp = client.post("/files/f1/share", json={},
                            headers={"Authorization": f"Bearer {_tok('u2')}"})
        assert resp.status_code == 403

    def test_404_file_not_found(self):
        resp = client.post("/files/nonexistent/share", json={},
                            headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 404


class TestGetShareStatus:
    def test_200_none_when_not_shared(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f2")
        db.close()

        resp = client.get("/files/f2/share",
                           headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 200
        assert resp.json() == {"token": None, "expires_at": None}

    def test_200_returns_existing_token(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f3")
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        created = client.post("/files/f3/share", json={}, headers=headers).json()
        status = client.get("/files/f3/share", headers=headers).json()
        assert status["token"] == created["token"]


class TestRevokeShareLink:
    def test_204_revokes(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f4")
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        client.post("/files/f4/share", json={}, headers=headers)

        resp = client.delete("/files/f4/share", headers=headers)
        assert resp.status_code == 204

        status = client.get("/files/f4/share", headers=headers).json()
        assert status["token"] is None

    def test_403_wrong_user(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f5")
        db.merge(User(id="u5", email="c@x.com", provider="google", provider_id="u5"))
        db.commit(); db.close()

        resp = client.delete("/files/f5/share",
                              headers={"Authorization": f"Bearer {_tok('u5')}"})
        assert resp.status_code == 403
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_share.py -v`
Expected: 전부 404 (라우터 자체가 없어서 `/files/f1/share` 미매칭 → FastAPI 기본 404) 또는 유사 실패. `share.py`가 없으므로 임포트 에러는 없음(main.py가 아직 참조 안 함) — 요청이 전부 404로 실패하는 것을 확인

- [ ] **Step 3: 공유 라우터 구현 (소유자 엔드포인트)**

`app/routers/share.py` (신규 생성):

```python
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File

router = APIRouter(prefix="/files", tags=["share"])


class ShareCreateRequest(BaseModel):
    expires_in_days: Optional[Literal[7, 30]] = 7


def _share_response(f: File) -> dict:
    return {
        "token": f.shared_token,
        "expires_at": f.shared_expires_at.isoformat() if f.shared_expires_at else None,
    }


def _get_owned_file(file_id: str, user: User, db: Session) -> File:
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    return f


@router.post("/{file_id}/share")
def create_share_link(
    file_id: str,
    body: ShareCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """공유 링크 생성 (기존 링크 있으면 덮어씀 — 파일당 1개)."""
    f = _get_owned_file(file_id, user, db)
    f.shared_token = secrets.token_urlsafe(24)
    f.shared_expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None else None
    )
    db.commit()
    db.refresh(f)
    return _share_response(f)


@router.get("/{file_id}/share")
def get_share_status(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 공유 상태 조회 (링크 없으면 token: null)."""
    f = _get_owned_file(file_id, user, db)
    return _share_response(f)


@router.delete("/{file_id}/share", status_code=204)
def revoke_share_link(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """공유 중단."""
    f = _get_owned_file(file_id, user, db)
    f.shared_token = None
    f.shared_expires_at = None
    db.commit()
```

- [ ] **Step 4: main.py에 라우터 등록**

`app/main.py` — 다른 라우터 import 옆에 추가:

```python
from app.routers.share import router as share_router
```

`app.include_router(export_router)` 다음 줄에 추가:

```python
app.include_router(share_router)
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_share.py -v`
Expected: 10 passed

- [ ] **Step 6: 커밋**

```bash
git add app/routers/share.py app/main.py tests/test_share.py
git commit -m "feat: 공유 링크 생성/조회/삭제 API (소유자)"
```

---

### Task 3: 공개 조회 API (인증 불필요)

**Files:**
- Modify: `app/routers/share.py` (Task 2에서 생성한 파일에 이어서 작성)
- Test: `tests/test_share.py` (Task 2에서 생성한 파일에 이어서 작성)

**Interfaces:**
- Consumes: `File.shared_token`, `File.shared_expires_at` (Task 1), 라우터는 이미 `app.main`에 등록됨 (Task 2)
- Produces: `GET /files/shared/{token}` — GP5 바이너리 응답 (200) 또는 404. 프론트 Task 6의 `fetchSharedGP5`가 이 엔드포인트를 호출

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_share.py` 끝에 추가:

```python
class TestPublicShareAccess:
    def test_200_returns_gp5_bytes(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f6")
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        created = client.post("/files/f6/share", json={}, headers=headers).json()

        resp = client.get(f"/files/shared/{created['token']}")  # 인증 헤더 없음
        assert resp.status_code == 200
        assert resp.content == b"GP5DATA"

    def test_200_infinite_expiry_always_accessible(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f7")
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        created = client.post("/files/f7/share", json={"expires_in_days": None},
                               headers=headers).json()

        resp = client.get(f"/files/shared/{created['token']}")
        assert resp.status_code == 200

    def test_404_unknown_token(self):
        resp = client.get("/files/shared/nonexistent-token-xyz")
        assert resp.status_code == 404

    def test_404_expired_token(self, tmp_path):
        from app.database import SessionLocal
        from app.models import File
        from datetime import datetime, timedelta, timezone
        db = SessionLocal()
        f = _setup_user_file(db, tmp_path, fid="f8")
        f.shared_token = "expired-token-abc"
        f.shared_expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.merge(f); db.commit(); db.close()

        resp = client.get("/files/shared/expired-token-abc")
        assert resp.status_code == 404

    def test_404_revoked_token(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path, fid="f9")
        db.close()

        headers = {"Authorization": f"Bearer {_tok('u1')}"}
        created = client.post("/files/f9/share", json={}, headers=headers).json()
        client.delete("/files/f9/share", headers=headers)

        resp = client.get(f"/files/shared/{created['token']}")
        assert resp.status_code == 404
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_share.py::TestPublicShareAccess -v`
Expected: 전부 실패 — `/files/shared/{token}`이 없어 `/files/{file_id}/share` 계열 라우트와 매칭 안 되고 404가 나오긴 하지만, 200을 기대하는 첫 두 테스트가 실패함 (404 응답이라)

- [ ] **Step 3: 공개 엔드포인트 구현**

`app/routers/share.py` 파일 맨 위 import에 추가:

```python
import os
from fastapi.responses import FileResponse
```

파일 끝에 추가:

```python
def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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

주의: `/shared/{token}` 라우트는 `/{file_id}/share` 라우트들과 경로 세그먼트 위치가 달라 충돌하지 않는다 (`files/shared/X` vs `files/X/share`). FastAPI가 라우트를 등록 순서대로 매칭하므로 이 함수를 라우터 파일 끝에 두는 것으로 충분하다.

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_share.py -v`
Expected: 15 passed (Task 2의 10개 + 이번 5개)

- [ ] **Step 5: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 전부 통과, 신규 실패 없음

- [ ] **Step 6: 커밋**

```bash
git add app/routers/share.py tests/test_share.py
git commit -m "feat: 공유 토큰으로 GP5 공개 조회 API (인증 불필요, 만료 체크)"
```

---

### Task 4: 프론트 api.ts 공유 함수 추가

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/__tests__/api.share.test.ts` (신규)

**Interfaces:**
- Consumes: 없음 (Task 2/3의 백엔드 엔드포인트 호출)
- Produces: `interface ShareInfo { token: string | null; expires_at: string | null }`, `api.getShareStatus(fileId)`, `api.createShareLink(fileId, expiresInDays)`, `api.revokeShareLink(fileId)`, `api.fetchSharedGP5(token)` — Task 5(ShareModal), Task 6(SharedScoreViewer)이 사용

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/api.share.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

beforeEach(() => mockFetch.mockReset())

describe('api 공유 링크', () => {
  it('getShareStatus: GET /files/{id}/share 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ token: null, expires_at: null }),
    })
    const { api } = await import('../lib/api')
    const result = await api.getShareStatus('f1')
    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/share',
      expect.objectContaining({ headers: expect.anything() }),
    )
    expect(result).toEqual({ token: null, expires_at: null })
  })

  it('createShareLink: POST /files/{id}/share에 expires_in_days 전송', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ token: 'abc123', expires_at: '2026-07-08T00:00:00+00:00' }),
    })
    const { api } = await import('../lib/api')
    const result = await api.createShareLink('f1', 7)
    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/share',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ expires_in_days: 7 }),
      }),
    )
    expect(result.token).toBe('abc123')
  })

  it('revokeShareLink: DELETE /files/{id}/share 호출', async () => {
    mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) })
    const { api } = await import('../lib/api')
    await api.revokeShareLink('f1')
    expect(mockFetch).toHaveBeenCalledWith(
      '/files/f1/share',
      expect.objectContaining({ method: 'DELETE' }),
    )
  })

  it('fetchSharedGP5: 인증 헤더 없이 GET /files/shared/{token} 호출', async () => {
    const buf = new ArrayBuffer(8)
    mockFetch.mockResolvedValueOnce({ ok: true, arrayBuffer: async () => buf })
    const { api } = await import('../lib/api')
    const result = await api.fetchSharedGP5('tok123')
    expect(mockFetch).toHaveBeenCalledWith('/files/shared/tok123')
    expect(result).toBe(buf)
  })

  it('fetchSharedGP5 실패 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '링크가 만료되었습니다' }),
    })
    const { api } = await import('../lib/api')
    await expect(api.fetchSharedGP5('expired')).rejects.toThrow('링크가 만료되었습니다')
  })
})
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `npx vitest run src/__tests__/api.share.test.ts`
Expected: FAIL — `api.getShareStatus is not a function` 등

- [ ] **Step 3: api.ts에 함수 추가**

`frontend/src/lib/api.ts` — 파일 최상단 `FileRecord` 인터페이스 다음에 추가:

```typescript
export interface ShareInfo {
  token: string | null
  expires_at: string | null
}
```

`export const api = { ... }` 객체 내부, `downloadMIDI` 다음에 추가 (마지막 항목이므로 `downloadMIDI` 줄 끝의 콤마 유지):

```typescript
  async getShareStatus(fileId: string): Promise<ShareInfo> {
    return request<ShareInfo>(`/files/${fileId}/share`)
  },

  async createShareLink(fileId: string, expiresInDays: 7 | 30 | null): Promise<ShareInfo> {
    return request<ShareInfo>(`/files/${fileId}/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ expires_in_days: expiresInDays }),
    })
  },

  async revokeShareLink(fileId: string): Promise<void> {
    await request<unknown>(`/files/${fileId}/share`, { method: 'DELETE' })
  },

  async fetchSharedGP5(token: string): Promise<ArrayBuffer> {
    const res = await fetch(`/files/shared/${token}`)
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.arrayBuffer()
  },
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `npx vitest run src/__tests__/api.share.test.ts`
Expected: 5 passed

- [ ] **Step 5: 전체 프론트 회귀 확인**

Run: `npx vitest run`
Expected: 전부 통과, 신규 실패 없음

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/lib/api.ts frontend/src/__tests__/api.share.test.ts
git commit -m "feat: 프론트 api.ts에 공유 링크 CRUD 함수 추가"
```

---

### Task 5: ShareModal 컴포넌트 + ExportMenu 연동

**Files:**
- Create: `frontend/src/components/Editor/ShareModal.tsx`
- Modify: `frontend/src/components/Editor/ExportMenu.tsx`
- Test: `frontend/src/__tests__/ShareModal.test.tsx` (신규)
- Test: `frontend/src/__tests__/ExportMenu.test.tsx` (수정 — api 모킹에 공유 함수 추가 + "공유" 버튼 테스트)

**Interfaces:**
- Consumes: `api.getShareStatus`, `api.createShareLink`, `api.revokeShareLink`, `ShareInfo` (Task 4)
- Produces: `ShareModal` props `{ fileId: string; onClose: () => void }` — 이후 태스크 없음(최종 UI)

- [ ] **Step 1: ShareModal 실패 테스트 작성**

`frontend/src/__tests__/ShareModal.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    getShareStatus: vi.fn(),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
  },
}))

import ShareModal from '../components/Editor/ShareModal'

describe('ShareModal', () => {
  const onClose = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(navigator, { clipboard: { writeText: vi.fn() } })
  })

  it('링크 없으면 만료기간 선택 + 생성 버튼 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({ token: null, expires_at: null })

    render(<ShareModal fileId="f1" onClose={onClose} />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /링크 생성/i })).toBeInTheDocument(),
    )
  })

  it('링크 생성 클릭 → api.createShareLink 호출 후 링크 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({ token: null, expires_at: null })
    vi.mocked(api.createShareLink).mockResolvedValue({
      token: 'abc123', expires_at: '2026-07-08T00:00:00+00:00',
    })

    render(<ShareModal fileId="f1" onClose={onClose} />)
    await waitFor(() => screen.getByRole('button', { name: /링크 생성/i }))
    await userEvent.click(screen.getByRole('button', { name: /링크 생성/i }))

    expect(api.createShareLink).toHaveBeenCalledWith('f1', 7)
    await waitFor(() =>
      expect(screen.getByDisplayValue(/\/share\/abc123/)).toBeInTheDocument(),
    )
  })

  it('기존 링크 있으면 링크+복사+공유중단 버튼 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({
      token: 'existing-token', expires_at: null,
    })

    render(<ShareModal fileId="f1" onClose={onClose} />)

    await waitFor(() =>
      expect(screen.getByDisplayValue(/\/share\/existing-token/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: /공유 중단/i })).toBeInTheDocument()
  })

  it('공유 중단 클릭 → api.revokeShareLink 호출 후 생성 폼으로 복귀', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getShareStatus).mockResolvedValue({
      token: 'existing-token', expires_at: null,
    })
    vi.mocked(api.revokeShareLink).mockResolvedValue(undefined)

    render(<ShareModal fileId="f1" onClose={onClose} />)
    await waitFor(() => screen.getByRole('button', { name: /공유 중단/i }))
    await userEvent.click(screen.getByRole('button', { name: /공유 중단/i }))

    expect(api.revokeShareLink).toHaveBeenCalledWith('f1')
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /링크 생성/i })).toBeInTheDocument(),
    )
  })
})
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `npx vitest run src/__tests__/ShareModal.test.tsx`
Expected: FAIL — 모듈 `../components/Editor/ShareModal`을 찾을 수 없음

- [ ] **Step 3: ShareModal.tsx 구현**

`frontend/src/components/Editor/ShareModal.tsx` (신규):

```tsx
import { useEffect, useState } from 'react'
import { api, type ShareInfo } from '../../lib/api'

interface Props {
  fileId: string
  onClose: () => void
}

export default function ShareModal({ fileId, onClose }: Props) {
  const [info, setInfo] = useState<ShareInfo | null>(null)
  const [loading, setLoading] = useState(true)
  const [expiresInDays, setExpiresInDays] = useState<7 | 30 | null>(7)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.getShareStatus(fileId)
      .then(res => { if (!cancelled) setInfo(res) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [fileId])

  async function handleCreate() {
    setLoading(true)
    const res = await api.createShareLink(fileId, expiresInDays)
    setInfo(res)
    setLoading(false)
  }

  async function handleRevoke() {
    setLoading(true)
    await api.revokeShareLink(fileId)
    setInfo({ token: null, expires_at: null })
    setLoading(false)
  }

  function handleCopy() {
    if (!info?.token) return
    navigator.clipboard.writeText(`${window.location.origin}/share/${info.token}`)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: '#fff', padding: 16, minWidth: 300 }}>
        <h3 style={{ marginTop: 0 }}>공유 링크</h3>

        {loading && <p>로딩 중…</p>}

        {!loading && info?.token && (
          <div>
            <input readOnly value={`${window.location.origin}/share/${info.token}`} style={{ width: '100%' }} />
            <p style={{ fontSize: 12, color: '#666' }}>
              만료: {info.expires_at ? new Date(info.expires_at).toLocaleDateString() : '무기한'}
            </p>
            <button onClick={handleCopy}>{copied ? '복사됨' : '복사'}</button>
            <button onClick={handleRevoke}>공유 중단</button>
          </div>
        )}

        {!loading && !info?.token && (
          <div>
            <label>
              만료:
              <select
                aria-label="만료기간"
                value={expiresInDays === null ? 'null' : String(expiresInDays)}
                onChange={e => setExpiresInDays(e.target.value === 'null' ? null : (Number(e.target.value) as 7 | 30))}
              >
                <option value="7">7일</option>
                <option value="30">30일</option>
                <option value="null">무기한</option>
              </select>
            </label>
            <button onClick={handleCreate}>링크 생성</button>
          </div>
        )}

        <div style={{ marginTop: 8 }}>
          <button onClick={onClose}>닫기</button>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: ShareModal 테스트 실행 → 통과 확인**

Run: `npx vitest run src/__tests__/ShareModal.test.tsx`
Expected: 4 passed

- [ ] **Step 5: ExportMenu 실패 테스트 작성 (기존 파일 수정)**

`frontend/src/__tests__/ExportMenu.test.tsx` — 최상단 `vi.mock('../lib/api', ...)` 블록을 아래로 교체:

```tsx
vi.mock('../lib/api', () => ({
  api: {
    downloadGP5: vi.fn().mockResolvedValue(undefined),
    downloadMIDI: vi.fn().mockResolvedValue(undefined),
    getShareStatus: vi.fn().mockResolvedValue({ token: null, expires_at: null }),
    createShareLink: vi.fn(),
    revokeShareLink: vi.fn(),
  },
}))
```

파일 끝 (`describe` 블록 안, 마지막 `it` 다음)에 추가:

```tsx
  it('공유 버튼 클릭 → ShareModal 오픈', async () => {
    render(<ExportMenu fileId="f1" onPrint={onPrint} />)
    await userEvent.click(screen.getByRole('button', { name: /공유/i }))
    expect(await screen.findByText('공유 링크')).toBeInTheDocument()
  })

  it('fileId 없으면 공유 버튼 비활성화', () => {
    render(<ExportMenu fileId={null} onPrint={onPrint} />)
    expect(screen.getByRole('button', { name: /공유/i })).toBeDisabled()
  })
```

- [ ] **Step 6: 테스트 실행 → 실패 확인**

Run: `npx vitest run src/__tests__/ExportMenu.test.tsx`
Expected: FAIL — "공유" 버튼을 찾을 수 없음

- [ ] **Step 7: ExportMenu.tsx에 공유 버튼 연동**

`frontend/src/components/Editor/ExportMenu.tsx` 전체를 아래로 교체:

```tsx
import { useState } from 'react'
import { api } from '../../lib/api'
import ShareModal from './ShareModal'

interface Props {
  fileId: string | null
  onPrint: () => void
}

export default function ExportMenu({ fileId, onPrint }: Props) {
  const [loading, setLoading] = useState<'gp5' | 'midi' | null>(null)
  const [shareOpen, setShareOpen] = useState(false)

  const handleGP5 = async () => {
    if (!fileId) return
    setLoading('gp5')
    try {
      await api.downloadGP5(fileId, 'score.gp5')
    } catch (e) {
      console.error('GP5 다운로드 실패', e)
    } finally {
      setLoading(null)
    }
  }

  const handleMIDI = async () => {
    if (!fileId) return
    setLoading('midi')
    try {
      await api.downloadMIDI(fileId, 'score.mid')
    } catch (e) {
      console.error('MIDI 다운로드 실패', e)
    } finally {
      setLoading(null)
    }
  }

  return (
    <span style={{ display: 'inline-flex', gap: 4, marginLeft: 8 }}>
      <button onClick={handleGP5} disabled={!fileId || loading === 'gp5'}>
        {loading === 'gp5' ? '…' : 'GP5 저장'}
      </button>
      <button onClick={onPrint}>PDF 저장</button>
      <button onClick={handleMIDI} disabled={!fileId || loading === 'midi'}>
        {loading === 'midi' ? '…' : 'MIDI 저장'}
      </button>
      <button onClick={() => setShareOpen(true)} disabled={!fileId}>공유</button>
      {shareOpen && fileId && (
        <ShareModal fileId={fileId} onClose={() => setShareOpen(false)} />
      )}
    </span>
  )
}
```

- [ ] **Step 8: 테스트 실행 → 통과 확인**

Run: `npx vitest run src/__tests__/ExportMenu.test.tsx`
Expected: 7 passed (기존 5개 + 신규 2개)

- [ ] **Step 9: 전체 프론트 회귀 확인**

Run: `npx vitest run`
Expected: 전부 통과

- [ ] **Step 10: 커밋**

```bash
git add frontend/src/components/Editor/ShareModal.tsx frontend/src/components/Editor/ExportMenu.tsx frontend/src/__tests__/ShareModal.test.tsx frontend/src/__tests__/ExportMenu.test.tsx
git commit -m "feat: ShareModal 컴포넌트 + ExportMenu 공유 버튼 연동"
```

---

### Task 6: 공개 뷰어 페이지 (SharedScoreViewer) + 라우트

**Files:**
- Create: `frontend/src/components/Editor/SharedScoreViewer.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/SharedScoreViewer.test.tsx` (신규)

**Interfaces:**
- Consumes: `api.fetchSharedGP5` (Task 4), `initAlphaTab` (기존 `frontend/src/lib/alphatab.ts`)
- Produces: 없음 (최종 사용자 대면 페이지, 편집 스토어와 완전 분리 — 다른 태스크가 이 컴포넌트를 재사용하지 않음)

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/SharedScoreViewer.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'

const loadMock = vi.fn()
const playPauseMock = vi.fn()
const destroyMock = vi.fn()

vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    load: loadMock,
    playPause: playPauseMock,
    destroy: destroyMock,
    playerStateChanged: { on: vi.fn() },
  }),
}))

vi.mock('../lib/api', () => ({
  api: { fetchSharedGP5: vi.fn() },
}))

import SharedScoreViewer from '../components/Editor/SharedScoreViewer'

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/share/:token" element={<SharedScoreViewer />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('SharedScoreViewer', () => {
  beforeEach(() => vi.clearAllMocks())

  it('정상 로드 시 재생 버튼 표시 + alphaTab.load 호출', async () => {
    const { api } = await import('../lib/api')
    const buf = new ArrayBuffer(8)
    vi.mocked(api.fetchSharedGP5).mockResolvedValue(buf)

    renderAt('/share/tok123')

    await waitFor(() => expect(loadMock).toHaveBeenCalledWith(buf))
    expect(screen.getByRole('button', { name: /재생/i })).toBeInTheDocument()
  })

  it('fetchSharedGP5 실패 시 안내 문구 표시', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.fetchSharedGP5).mockRejectedValue(new Error('링크가 만료되었습니다'))

    renderAt('/share/expired')

    await waitFor(() =>
      expect(screen.getByText(/만료되었거나 존재하지 않습니다/)).toBeInTheDocument(),
    )
  })
})
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `npx vitest run src/__tests__/SharedScoreViewer.test.tsx`
Expected: FAIL — 모듈 `../components/Editor/SharedScoreViewer`를 찾을 수 없음

- [ ] **Step 3: SharedScoreViewer.tsx 구현**

`frontend/src/components/Editor/SharedScoreViewer.tsx` (신규):

```tsx
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { initAlphaTab } from '../../lib/alphatab'
import { api } from '../../lib/api'
import type * as alphaTab from '@coderline/alphatab'

export default function SharedScoreViewer() {
  const { token } = useParams<{ token: string }>()
  const containerRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current || !token) return
    const atApi = initAlphaTab(containerRef.current)
    apiRef.current = atApi
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    atApi.playerStateChanged.on((e: any) => setPlaying(e.state === 1))

    api.fetchSharedGP5(token)
      .then(buf => atApi.load(buf))
      .catch(() => setError('링크가 만료되었거나 존재하지 않습니다'))

    return () => { atApi.destroy(); apiRef.current = null }
  }, [token])

  if (error) {
    return <div style={{ padding: 32, textAlign: 'center', color: '#666' }}>{error}</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <div style={{ padding: 8 }}>
        <button onClick={() => apiRef.current?.playPause()}>
          {playing ? '일시정지' : '재생'}
        </button>
      </div>
      <div ref={containerRef} style={{ flex: 1, overflow: 'auto' }} />
    </div>
  )
}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `npx vitest run src/__tests__/SharedScoreViewer.test.tsx`
Expected: 2 passed

- [ ] **Step 5: App.tsx에 라우트 추가**

`frontend/src/App.tsx` — import 목록에 추가:

```tsx
import SharedScoreViewer from './components/Editor/SharedScoreViewer'
```

`<Route path="/" element={<MainPage />} />` 다음 줄에 추가 (catch-all `*` 라우트보다 먼저):

```tsx
        <Route path="/share/:token" element={<SharedScoreViewer />} />
```

- [ ] **Step 6: 전체 프론트 회귀 확인**

Run: `npx vitest run`
Expected: 전부 통과

- [ ] **Step 7: 타입체크 + lint 확인**

Run: `npx tsc --noEmit -p tsconfig.app.json && npm run lint`
Expected: 새로 생긴 에러 없음 (기존 pre-existing 경고 12개는 무관 — Task 시작 전과 동일 개수인지 확인)

- [ ] **Step 8: 커밋**

```bash
git add frontend/src/components/Editor/SharedScoreViewer.tsx frontend/src/App.tsx frontend/src/__tests__/SharedScoreViewer.test.tsx
git commit -m "feat: 공유 링크 공개 뷰어 페이지(SharedScoreViewer) + /share/:token 라우트"
```

---

## 최종 검증 (전체 태스크 완료 후)

- [ ] Run: `python -m pytest -q` — 전체 백엔드 통과 (기존 163 + 신규 18 = 181)
- [ ] Run: `cd frontend && npx vitest run` — 전체 프론트 통과 (기존 119 + 신규 13 = 132)
- [ ] 수동 확인: 로컬에서 `POST /files/{id}/share` → 응답 token으로 `/share/{token}` 브라우저 접속 → 악보 렌더링 + 재생 동작 확인
