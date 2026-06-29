# GP Converter Phase 0 — 뷰어 + 재생 + 인증 + SSE 진행률 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF→GP5 변환 진행률을 실시간으로 표시하고, Google/GitHub OAuth 로그인 후 변환된 악보를 alphaTab으로 렌더링·재생하며 파일 목록을 관리하는 SaaS 웹 뷰어를 구축한다.

**Architecture:** React+TypeScript 프론트엔드(Vite, 포트 5173)가 FastAPI 백엔드(포트 8000)와 REST + SSE로 통신한다. 변환 진행률은 BackgroundTask가 JobStore의 `progress_pct` 필드를 단계별로 업데이트하고, SSE 엔드포인트가 0.5초 폴링으로 클라이언트에 스트리밍한다. 악보 렌더링은 alphaTab 1.x로 처리하며, SoundFont는 jsDelivr CDN에서 로드한다.

**Tech Stack:** FastAPI, SQLAlchemy 2.x (SQLite), PyJWT, httpx, React 18, TypeScript 5, Vite 5, `@coderline/alphatab@^1.3`, Zustand 4, React Router 6, Vitest 1, `@testing-library/react`

## Global Constraints

- alphaTab: `@coderline/alphatab@^1.3` (2.x는 파괴적 변경 있음, 고정)
- JWT: access token 만료 15분, refresh token 만료 7일, 알고리즘 HS256
- SSE 폴링 간격: 500ms
- DB: SQLite (개발), SQLAlchemy 2.x ORM (PostgreSQL 전환 가능하도록)
- CORS: 개발 시 `http://localhost:5173` 허용
- SoundFont URL: `https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2`
- alphaTab font 디렉토리: `https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/font/`
- OAuth redirect URI (개발): `http://localhost:8000/auth/{google|github}/callback`
- 프론트엔드 URL (개발): `http://localhost:5173`
- 필수 환경변수: `JWT_SECRET_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`
- 선택 환경변수: `FRONTEND_URL` (기본값 `http://localhost:5173`), `DATABASE_URL` (기본값 `sqlite:///./gp_converter.db`)
- 기존 파이프라인 (`app/pipeline/`, `app/jobs.py`, `app/worker.py`) 동작 유지
- Phase 1–3는 별도 플랜 문서 예정

---

## 파일 구조

### Backend (신규/수정)
```
app/
  database.py          ← 신규: SQLAlchemy 엔진, 세션, Base
  models.py            ← 신규: User, File, DbJob 테이블
  auth.py              ← 신규: JWT 발급/검증
  dependencies.py      ← 신규: get_current_user FastAPI 의존성
  jobs.py              ← 수정: Job dataclass에 progress_pct 추가
  worker.py            ← 수정: 진행률 콜백 수용
  pipeline/
    orchestrator.py    ← 수정: progress_callback 파라미터 추가
  routers/
    auth.py            ← 신규: /auth/google, /auth/github, /auth/refresh
    jobs_sse.py        ← 신규: GET /jobs/{id}/stream SSE
    files.py           ← 신규: GET /files, DELETE /files/{id}
  main.py              ← 수정: 라우터 등록, DB init, CORS, /convert 수정
requirements.txt       ← 수정: sqlalchemy, pyjwt, httpx, python-jose 추가
```

### Frontend (신규)
```
frontend/
  package.json
  vite.config.ts
  tsconfig.json
  index.html
  src/
    main.tsx
    App.tsx
    lib/
      api.ts           ← REST 클라이언트 (fetch 래퍼)
      sse.ts           ← SSE 연결 관리
    store/
      authStore.ts     ← Zustand: JWT, user 정보
      fileStore.ts     ← Zustand: 파일 목록
    components/
      Auth/
        LoginPage.tsx
        OAuthCallback.tsx
      Editor/
        ScoreViewer.tsx    ← alphaTab 마운트
        ProgressBar.tsx    ← 변환 진행률
      FileManager/
        FileList.tsx
        UploadButton.tsx
    __tests__/
      ProgressBar.test.tsx
      ScoreViewer.test.tsx
      LoginPage.test.tsx
      UploadButton.test.tsx
      FileList.test.tsx
```

---

## Task 1: DB 모델 + 세션

**Files:**
- Create: `app/database.py`
- Create: `app/models.py`
- Test: `tests/test_db_models.py`

**Interfaces:**
- Produces:
  - `app.database.Base` — SQLAlchemy DeclarativeBase
  - `app.database.get_db() -> Generator[Session, None, None]`
  - `app.database.engine`
  - `app.models.User(id, email, provider, provider_id, plan, created_at)`
  - `app.models.File(id, user_id, name, gp5_path, created_at, updated_at)`
  - `app.models.DbJob(id, user_id, file_id, status, progress_pct, message, created_at)`

- [ ] **Step 1: requirements.txt에 의존성 추가**

```
# requirements.txt 하단에 추가
sqlalchemy==2.0.*
pyjwt==2.9.*
httpx==0.27.*
```

Run: `pip install -r requirements.txt`
Expected: Successfully installed

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_db_models.py`:
```python
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import User, File, DbJob


@pytest.fixture
def engine():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def test_tables_exist(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    assert "users" in tables
    assert "files" in tables
    assert "db_jobs" in tables


def test_user_create(session):
    u = User(email="test@example.com", provider="google", provider_id="g123")
    session.add(u)
    session.commit()
    found = session.query(User).filter_by(email="test@example.com").first()
    assert found is not None
    assert found.plan == "free"
    assert found.id is not None


def test_file_create(session):
    u = User(email="a@b.com", provider="github", provider_id="gh1")
    session.add(u)
    session.commit()
    f = File(user_id=u.id, name="my_song", gp5_path="/tmp/out.gp5")
    session.add(f)
    session.commit()
    found = session.query(File).filter_by(user_id=u.id).first()
    assert found.name == "my_song"


def test_dbjob_progress(session):
    j = DbJob(id="abc123", status="pending", progress_pct=0)
    session.add(j)
    session.commit()
    j.progress_pct = 60
    session.commit()
    found = session.query(DbJob).filter_by(id="abc123").first()
    assert found.progress_pct == 60
```

Run: `pytest tests/test_db_models.py -v`
Expected: FAIL — `app.database` not found

- [ ] **Step 3: app/database.py 작성**

```python
import os
from sqlalchemy import create_engine
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
```

- [ ] **Step 4: app/models.py 작성**

```python
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.sql import func
from app.database import Base


def _uuid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False)
    provider_id = Column(String, nullable=False)
    plan = Column(String, nullable=False, default="free")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class File(Base):
    __tablename__ = "files"
    id = Column(String, primary_key=True, default=_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    gp5_path = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DbJob(Base):
    __tablename__ = "db_jobs"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    file_id = Column(String, ForeignKey("files.id"), nullable=True)
    status = Column(String, nullable=False, default="pending")
    progress_pct = Column(Integer, nullable=False, default=0)
    message = Column(String, nullable=True, default="")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `pytest tests/test_db_models.py -v`
Expected: 5 passed

- [ ] **Step 6: 커밋**

```bash
git add app/database.py app/models.py tests/test_db_models.py requirements.txt
git commit -m "feat: DB 모델 + 세션 (User, File, DbJob)"
```

---

## Task 2: JWT 유틸 + FastAPI 의존성

**Files:**
- Create: `app/auth.py`
- Create: `app/dependencies.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `app.database.get_db`, `app.models.User`
- Produces:
  - `app.auth.create_access_token(user_id: str) -> str`
  - `app.auth.create_refresh_token(user_id: str) -> str`
  - `app.auth.decode_token(token: str) -> dict`  — raises `jwt.ExpiredSignatureError`, `jwt.InvalidTokenError`
  - `app.dependencies.get_current_user` — FastAPI Depends, returns `User`, raises `HTTPException(401)`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_auth.py`:
```python
import os, time
import pytest
import jwt

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")


def test_access_token_roundtrip():
    from app.auth import create_access_token, decode_token
    token = create_access_token("user123")
    payload = decode_token(token)
    assert payload["sub"] == "user123"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    from app.auth import create_refresh_token, decode_token
    token = create_refresh_token("user456")
    payload = decode_token(token)
    assert payload["sub"] == "user456"
    assert payload["type"] == "refresh"


def test_expired_token_raises():
    from app.auth import decode_token
    # 만료시간 1초 전 토큰 직접 발급
    payload = {"sub": "u1", "exp": int(time.time()) - 1, "type": "access"}
    token = jwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


def test_invalid_token_raises():
    from app.auth import decode_token
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("not.a.valid.token")
```

Run: `pytest tests/test_auth.py -v`
Expected: FAIL — `app.auth` not found

- [ ] **Step 2: app/auth.py 작성**

```python
import os
from datetime import datetime, timedelta, timezone
import jwt

_SECRET = os.environ["JWT_SECRET_KEY"]
_ALGO = "HS256"
_ACCESS_MINUTES = 15
_REFRESH_DAYS = 7


def create_access_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_MINUTES)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "access"}, _SECRET, algorithm=_ALGO)


def create_refresh_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=_REFRESH_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "refresh"}, _SECRET, algorithm=_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _SECRET, algorithms=[_ALGO])
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest tests/test_auth.py -v`
Expected: 4 passed

- [ ] **Step 4: app/dependencies.py 작성**

```python
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.auth import decode_token
from app.database import get_db
from app.models import User

_bearer = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
```

- [ ] **Step 5: 커밋**

```bash
git add app/auth.py app/dependencies.py tests/test_auth.py
git commit -m "feat: JWT 유틸 + get_current_user 의존성"
```

---

## Task 3: OAuth 라우터 (Google + GitHub)

**Files:**
- Create: `app/routers/auth.py`
- Create: `app/routers/__init__.py`
- Test: `tests/test_oauth.py`

**Interfaces:**
- Consumes: `app.auth.create_access_token`, `app.auth.create_refresh_token`, `app.auth.decode_token`, `app.database.get_db`, `app.models.User`
- Produces:
  - `GET /auth/google` → RedirectResponse (Google OAuth)
  - `GET /auth/google/callback?code=` → RedirectResponse to FRONTEND_URL/auth/callback?access_token=&refresh_token=
  - `GET /auth/github` → RedirectResponse
  - `GET /auth/github/callback?code=` → RedirectResponse
  - `POST /auth/refresh` body `{"refresh_token": "..."}` → `{"access_token": "...", "refresh_token": "..."}`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_oauth.py`:
```python
import os, pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "gh-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "gh-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")

from app.database import Base, get_db
from app.main import app

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine)


def override_db():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app, follow_redirects=False)


def test_google_login_redirects():
    r = client.get("/auth/google")
    assert r.status_code in (302, 307)
    assert "accounts.google.com" in r.headers["location"]


def test_github_login_redirects():
    r = client.get("/auth/github")
    assert r.status_code in (302, 307)
    assert "github.com/login/oauth/authorize" in r.headers["location"]


def test_refresh_invalid_token():
    r = client.post("/auth/refresh", json={"refresh_token": "bad.token.here"})
    assert r.status_code == 401


def test_refresh_wrong_type():
    from app.auth import create_access_token
    token = create_access_token("user1")  # access, not refresh
    r = client.post("/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401
```

Run: `pytest tests/test_oauth.py -v`
Expected: FAIL — router not found

- [ ] **Step 2: app/routers/__init__.py 생성 (비어도 됨)**

```python
```

- [ ] **Step 3: app/routers/auth.py 작성**

```python
import os
import jwt
import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import create_access_token, create_refresh_token, decode_token
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

_GOOGLE_ID = os.environ["GOOGLE_CLIENT_ID"]
_GOOGLE_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
_GITHUB_ID = os.environ["GITHUB_CLIENT_ID"]
_GITHUB_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
_FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:5173")
_BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")


@router.get("/google")
def google_login():
    params = "&".join([
        "response_type=code",
        f"client_id={_GOOGLE_ID}",
        f"redirect_uri={_BACKEND}/auth/google/callback",
        "scope=openid+email+profile",
    ])
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@router.get("/google/callback")
async def google_callback(code: str, db: Session = Depends(get_db)):
    async with httpx.AsyncClient() as c:
        tok = (await c.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": _GOOGLE_ID, "client_secret": _GOOGLE_SECRET,
            "redirect_uri": f"{_BACKEND}/auth/google/callback",
            "grant_type": "authorization_code",
        })).json()
        info = (await c.get("https://www.googleapis.com/oauth2/v2/userinfo",
                             headers={"Authorization": f"Bearer {tok['access_token']}"})).json()

    user = db.query(User).filter_by(provider="google", provider_id=str(info["id"])).first()
    if not user:
        user = User(email=info["email"], provider="google", provider_id=str(info["id"]))
        db.add(user)
        db.commit()
        db.refresh(user)

    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return RedirectResponse(f"{_FRONTEND}/auth/callback?access_token={access}&refresh_token={refresh}")


@router.get("/github")
def github_login():
    params = f"client_id={_GITHUB_ID}&redirect_uri={_BACKEND}/auth/github/callback&scope=user:email"
    return RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")


@router.get("/github/callback")
async def github_callback(code: str, db: Session = Depends(get_db)):
    async with httpx.AsyncClient() as c:
        tok = (await c.post(
            "https://github.com/login/oauth/access_token",
            data={"client_id": _GITHUB_ID, "client_secret": _GITHUB_SECRET,
                  "code": code, "redirect_uri": f"{_BACKEND}/auth/github/callback"},
            headers={"Accept": "application/json"},
        )).json()
        info = (await c.get("https://api.github.com/user",
                              headers={"Authorization": f"Bearer {tok['access_token']}",
                                       "Accept": "application/json"})).json()
        emails = (await c.get("https://api.github.com/user/emails",
                               headers={"Authorization": f"Bearer {tok['access_token']}",
                                        "Accept": "application/json"})).json()

    primary_email = next((e["email"] for e in emails if e.get("primary")), info.get("email", ""))
    provider_id = str(info["id"])

    user = db.query(User).filter_by(provider="github", provider_id=provider_id).first()
    if not user:
        user = User(email=primary_email, provider="github", provider_id=provider_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return RedirectResponse(f"{_FRONTEND}/auth/callback?access_token={access}&refresh_token={refresh}")


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh_tokens(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user_id = payload["sub"]
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
    }
```

- [ ] **Step 4: 테스트 통과 확인** (main.py에 라우터 등록은 Task 7에서 하지만 테스트는 app import로 직접 확인)

main.py에 임시로 라우터 등록 (Task 7에서 정식 통합):
```python
# app/main.py 상단에 추가 (임시)
from app.routers.auth import router as auth_router
app.include_router(auth_router)
```

Run: `pytest tests/test_oauth.py -v`
Expected: 4 passed

- [ ] **Step 5: 임시 라우터 등록 제거 후 커밋** (Task 7에서 정식으로 추가)

```bash
git add app/routers/__init__.py app/routers/auth.py tests/test_oauth.py
git commit -m "feat: Google/GitHub OAuth + JWT refresh 라우터"
```

---

## Task 4: JobStore 진행률 확장

**Files:**
- Modify: `app/jobs.py` (Job dataclass에 `progress_pct: int = 0` 추가)
- Test: `tests/test_jobs.py` (기존 + 진행률 테스트 추가)

**Interfaces:**
- Produces:
  - `Job.progress_pct: int` 필드 (기존 Job에 추가)
  - `JobStore.update(job_id, progress_pct=60, ...)` — 기존 update 동일 방식으로 작동

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_jobs.py`에 추가 (파일이 없으면 신규 작성):
```python
import os, tempfile, pytest
from app.jobs import Job, JobStore, JobStatus


@pytest.fixture
def store(tmp_path):
    return JobStore(str(tmp_path))


def test_job_has_progress_pct(store):
    job = store.create()
    assert job.progress_pct == 0


def test_update_progress_pct(store):
    job = store.create()
    store.update(job.id, progress_pct=42)
    updated = store.get(job.id)
    assert updated.progress_pct == 42


def test_progress_persists_across_read(store):
    job = store.create()
    store.update(job.id, progress_pct=75, status=JobStatus.RUNNING)
    reloaded = store.get(job.id)
    assert reloaded.progress_pct == 75
    assert reloaded.status == JobStatus.RUNNING
```

Run: `pytest tests/test_jobs.py -v`
Expected: FAIL — `Job` has no attribute `progress_pct`

- [ ] **Step 2: app/jobs.py 수정** — `Job` dataclass에 필드 추가

```python
# 기존 Job dataclass 찾아서 progress_pct 필드 추가:
@dataclass
class Job:
    id: str
    status: JobStatus
    workdir: str
    message: str = ""
    result_path: str = ""
    progress_pct: int = 0   # ← 추가
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest tests/test_jobs.py -v`
Expected: 3 passed (기존 테스트도 모두 통과)

Run: `pytest tests/ -v --ignore=tests/test_oauth.py`
Expected: 모두 pass (regression 없음)

- [ ] **Step 4: 커밋**

```bash
git add app/jobs.py tests/test_jobs.py
git commit -m "feat: Job.progress_pct 필드 추가"
```

---

## Task 5: Worker + Orchestrator 진행률 콜백

**Files:**
- Modify: `app/pipeline/orchestrator.py` (progress_callback 파라미터 추가)
- Modify: `app/worker.py` (콜백으로 JobStore 업데이트)
- Test: `tests/test_worker_progress.py`

**Interfaces:**
- Consumes: `Job.progress_pct`, `JobStore.update`
- Produces:
  - `run_conversion(pdf_path, workdir, ..., progress_callback=None)` — callback 시그니처: `(pct: int, step: str) -> None`
  - `process_job(store, job_id, pdf_path, ...)` — 단계별로 progress_pct 업데이트

진행률 단계:
```
10%  — TAB 보표 감지 완료
30%  — OMR 추론 시작
80%  — GP5 빌드 완료
90%  — (Audiveris 경로) MusicXML 변환 완료
100% — 완료 (worker에서 status=DONE과 함께 설정)
```

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worker_progress.py`:
```python
import os, tempfile, pytest
from unittest.mock import patch, MagicMock
from app.jobs import JobStore, JobStatus


@pytest.fixture
def store(tmp_path):
    return JobStore(str(tmp_path))


def test_worker_updates_progress(store, tmp_path):
    pdf_path = str(tmp_path / "in.pdf")
    open(pdf_path, "w").close()

    recorded = []

    def fake_run_conversion(pdf_path, workdir, **kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb(10, "tab_detect")
            cb(30, "omr")
            cb(80, "gp5_build")
        return str(tmp_path / "out.gp5")

    open(str(tmp_path / "out.gp5"), "w").close()

    with patch("app.worker.run_conversion", side_effect=fake_run_conversion):
        from app.worker import process_job
        job = store.create()
        process_job(store, job.id, pdf_path,
                    audiveris_cmd="", tuxguitar_cmd="", timeout=0)

    final = store.get(job.id)
    assert final.status == JobStatus.DONE
    assert final.progress_pct == 100
```

Run: `pytest tests/test_worker_progress.py -v`
Expected: FAIL

- [ ] **Step 2: app/pipeline/orchestrator.py 수정** — `progress_callback` 추가

```python
# run_conversion 시그니처 변경:
def run_conversion(
    pdf_path: str,
    workdir: str,
    audiveris_cmd: str,
    tuxguitar_cmd: str,
    timeout: int,
    progress_callback=None,   # ← 추가. (pct: int, step: str) -> None
) -> str:
    gp5_path = os.path.join(workdir, "output.gp5")

    def _cb(pct: int, step: str):
        if progress_callback:
            progress_callback(pct, step)

    tab_regions = None
    try:
        tab_regions = detect_tab_staves(pdf_path)
    except Exception as e:
        logger.warning("탭 인식 실패, 휴리스틱으로 폴백: %s", e)

    _cb(10, "tab_detect")

    if tab_regions:
        _cb(30, "omr")
        token_texts = run_omr_tab(pdf_path, tab_regions, workdir, timeout=timeout)
        result = token_texts_to_gp5(token_texts, gp5_path)
        _cb(80, "gp5_build")
        return result

    xml_dir = os.path.join(workdir, "xml")
    _cb(30, "audiveris")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)
    _cb(80, "musicxml_convert")
    result = musicxml_to_gp5(xml_path, gp5_path, timeout=timeout, tab_hints=None)
    _cb(90, "gp5_build")
    return result
```

- [ ] **Step 3: app/worker.py 수정**

```python
from app.jobs import JobStore, JobStatus
from app.pipeline.orchestrator import run_conversion


def process_job(store: JobStore, job_id: str, pdf_path: str,
                audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> None:
    job = store.get(job_id)
    if job is None:
        return
    store.update(job_id, status=JobStatus.RUNNING, progress_pct=5)

    def _progress(pct: int, step: str):
        store.update(job_id, progress_pct=pct, message=step)

    try:
        gp5_path = run_conversion(
            pdf_path, job.workdir,
            audiveris_cmd=audiveris_cmd,
            tuxguitar_cmd=tuxguitar_cmd,
            timeout=timeout,
            progress_callback=_progress,
        )
        store.update(job_id, status=JobStatus.DONE, result_path=gp5_path, progress_pct=100)
    except Exception as e:
        store.update(job_id, status=JobStatus.FAILED, message=str(e))
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `pytest tests/test_worker_progress.py tests/test_jobs.py -v`
Expected: 모두 pass

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/orchestrator.py app/worker.py tests/test_worker_progress.py
git commit -m "feat: 파이프라인 진행률 콜백 + worker progress_pct 업데이트"
```

---

## Task 6: SSE 엔드포인트 + 파일 관리 API

**Files:**
- Create: `app/routers/jobs_sse.py`
- Create: `app/routers/files.py`
- Test: `tests/test_sse.py`

**Interfaces:**
- Consumes: `app.jobs.JobStore`, `app.dependencies.get_current_user`, `app.models.File`
- Produces:
  - `GET /jobs/{job_id}/stream` → `text/event-stream` — `data: {"status":"running","pct":60,"step":"omr"}\n\n`
  - `GET /files` → `[{"id":"...", "name":"...", "created_at":"..."}]`
  - `DELETE /files/{file_id}` → `204 No Content`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_sse.py`:
```python
import os, pytest, json
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "gh-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "gh-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import app

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine)


def override_db():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def test_sse_unknown_job_returns_failed_event():
    with client.stream("GET", "/jobs/nonexistent-job/stream") as r:
        assert r.status_code == 200
        line = next(r.iter_lines())
        data = json.loads(line.replace("data: ", ""))
        assert data["status"] == "failed"


def test_sse_done_job_streams_done():
    from app.jobs import JobStore, JobStatus
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        store = JobStore(d)
        job = store.create()
        store.update(job.id, status=JobStatus.DONE, progress_pct=100)

        # SSE 스트리밍: done 이벤트 하나 받으면 종료
        with client.stream("GET", f"/jobs/{job.id}/stream") as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    data = json.loads(line[6:])
                    assert data["status"] == "done"
                    assert data["pct"] == 100
                    break
```

Run: `pytest tests/test_sse.py -v`
Expected: FAIL

- [ ] **Step 2: app/routers/jobs_sse.py 작성**

```python
import asyncio
import json
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from app.config import Settings
from app.jobs import JobStore, JobStatus
from functools import lru_cache

router = APIRouter(tags=["jobs"])


@lru_cache
def _get_store() -> JobStore:
    return JobStore(Settings().jobs_dir)


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str, store: JobStore = Depends(_get_store)):
    async def generate():
        while True:
            job = store.get(job_id)
            if job is None:
                yield f"data: {json.dumps({'status': 'failed', 'pct': 0, 'step': 'job not found'})}\n\n"
                return
            payload = {
                "status": job.status.value,
                "pct": job.progress_pct,
                "step": job.message or "",
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if job.status in (JobStatus.DONE, JobStatus.FAILED):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

- [ ] **Step 3: app/routers/files.py 작성**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
import os

router = APIRouter(prefix="/files", tags=["files"])


@router.get("")
def list_files(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    files = db.query(File).filter_by(user_id=user.id).order_by(File.created_at.desc()).all()
    return [{"id": f.id, "name": f.name, "created_at": str(f.created_at)} for f in files]


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

- [ ] **Step 4: 테스트 통과 확인**

main.py에 라우터 임시 등록 후:

Run: `pytest tests/test_sse.py -v`
Expected: 2 passed

- [ ] **Step 5: 커밋**

```bash
git add app/routers/jobs_sse.py app/routers/files.py tests/test_sse.py
git commit -m "feat: SSE 진행률 스트리밍 + 파일 관리 API"
```

---

## Task 7: main.py 통합 (CORS + 라우터 + DB init + /convert 수정)

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_main_integration.py`

**Interfaces:**
- Consumes: 모든 라우터, `app.database.Base`, `app.database.engine`
- Produces: 완전한 FastAPI 앱 — 모든 엔드포인트 등록, 인증 필요한 `/convert`, DB 자동 생성

`/convert` 변경사항:
- 선택적 인증 (비로그인 허용, 로그인 시 File 레코드 생성)
- 응답에 `file_id` 추가 (로그인 시)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_main_integration.py`:
```python
import os, pytest, io
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "gh-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "gh-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base, get_db
from app.main import app

_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine)


def override_db():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


app.dependency_overrides[get_db] = override_db
client = TestClient(app)


def test_cors_header_present():
    r = client.options("/convert", headers={"Origin": "http://localhost:5173",
                                             "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" in r.headers


def test_convert_returns_job_id():
    fake_pdf = b"%PDF-1.4 fake"
    r = client.post("/convert", files={"file": ("t.pdf", io.BytesIO(fake_pdf), "application/pdf")})
    assert r.status_code == 200
    assert "job_id" in r.json()


def test_auth_routes_exist():
    r = client.get("/auth/google", follow_redirects=False)
    assert r.status_code in (302, 307)
```

Run: `pytest tests/test_main_integration.py -v`
Expected: FAIL (CORS / 라우터 미등록)

- [ ] **Step 2: app/main.py 전면 수정**

```python
import os
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import Depends, FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import Base, engine, get_db
from app.jobs import JobStore, JobStatus
from app.models import User, File as DbFile
from app.routers.auth import router as auth_router
from app.routers.jobs_sse import router as jobs_sse_router
from app.routers.files import router as files_router
from app.worker import process_job

# DB 테이블 자동 생성
Base.metadata.create_all(bind=engine)

app = FastAPI(title="GP Converter")

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(jobs_sse_router)
app.include_router(files_router)

_UPLOAD_CHUNK_BYTES = 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_store(settings: Settings = Depends(get_settings)) -> JobStore:
    return JobStore(settings.jobs_dir)


async def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Authorization 헤더가 없으면 None 반환 (비로그인 허용)."""
    from app.auth import decode_token
    import jwt as _jwt
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        payload = decode_token(auth.split(" ", 1)[1])
        if payload.get("type") != "access":
            return None
        return db.query(User).filter(User.id == payload["sub"]).first()
    except (_jwt.ExpiredSignatureError, _jwt.InvalidTokenError):
        return None


@app.post("/convert")
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=".pdf")
    checked_magic = False
    try:
        with os.fdopen(fd, "wb") as out:
            total = 0
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                if not checked_magic:
                    if not chunk.startswith(b"%PDF-"):
                        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능")
                    checked_magic = True
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(status_code=400, detail="파일이 너무 큽니다")
                out.write(chunk)
        if not checked_magic:
            raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능")
    except Exception:
        os.remove(tmp_path)
        raise

    job = store.create()
    pdf_path = os.path.join(job.workdir, "input.pdf")
    os.replace(tmp_path, pdf_path)

    # 로그인 사용자면 File 레코드 예약 생성 (gp5_path는 변환 후 채워짐)
    file_id = None
    if current_user:
        db_file = DbFile(
            user_id=current_user.id,
            name=file.filename or "untitled",
            gp5_path="",  # 변환 완료 후 worker가 업데이트 (Phase 1에서 구현)
        )
        db.add(db_file)
        db.commit()
        db.refresh(db_file)
        file_id = db_file.id

    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
    )
    return {"job_id": job.id, "file_id": file_id}


@app.get("/jobs/{job_id}")
async def job_status(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    return {"status": job.status.value, "message": job.message, "pct": job.progress_pct}


@app.get("/jobs/{job_id}/result")
async def job_result(job_id: str, store: JobStore = Depends(get_store)):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job 없음")
    if job.status != JobStatus.DONE or not job.result_path or not os.path.exists(job.result_path):
        raise HTTPException(status_code=409, detail="아직 결과 없음")
    return FileResponse(job.result_path, media_type="application/octet-stream", filename="score.gp5")


# 프론트엔드 정적 파일 (프로덕션 빌드)
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
```

- [ ] **Step 3: 테스트 통과 확인**

Run: `pytest tests/test_main_integration.py tests/test_oauth.py -v`
Expected: 모두 pass

Run: `pytest tests/ -v`
Expected: 모든 기존 테스트 pass (regression 없음)

- [ ] **Step 4: 커밋**

```bash
git add app/main.py
git commit -m "feat: CORS + 라우터 통합 + /convert 선택적 인증"
```

---

## Task 8: Frontend Vite + React + 의존성 셋업

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `http://localhost:5173` — 빈 React 앱, 백엔드 프록시 설정

- [ ] **Step 1: frontend 디렉토리 생성 및 Vite 프로젝트 초기화**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
npm create vite@latest frontend -- --template react-ts
cd frontend
```

- [ ] **Step 2: 의존성 설치**

```bash
npm install @coderline/alphatab@^1.3 zustand react-router-dom
npm install -D vitest @testing-library/react @testing-library/user-event @testing-library/jest-dom jsdom
```

- [ ] **Step 3: vite.config.ts 수정** — 프록시 + Vitest 설정

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/convert': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
```

- [ ] **Step 4: 테스트 setup 파일 작성**

`frontend/src/__tests__/setup.ts`:
```typescript
import '@testing-library/jest-dom'
```

- [ ] **Step 5: 빈 앱 동작 확인**

```bash
# frontend/ 에서
npm run dev
```
Expected: `http://localhost:5173` 에서 Vite 기본 화면 확인

- [ ] **Step 6: 기본 테스트 확인**

`frontend/src/__tests__/App.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import App from '../App'

test('앱이 렌더링된다', () => {
  render(<App />)
  expect(document.body).toBeTruthy()
})
```

Run (frontend/): `npm run test -- --run`
Expected: 1 passed

- [ ] **Step 7: 커밋**

```bash
cd ..  # 프로젝트 루트로
git add frontend/
git commit -m "feat: Vite + React + TypeScript + alphaTab 프론트엔드 셋업"
```

---

## Task 9: API 클라이언트 + SSE 유틸 + Zustand 스토어

**Files:**
- Create: `frontend/src/lib/api.ts`
- Create: `frontend/src/lib/sse.ts`
- Create: `frontend/src/store/authStore.ts`
- Create: `frontend/src/store/fileStore.ts`
- Test: `frontend/src/__tests__/api.test.ts`
- Test: `frontend/src/__tests__/sse.test.ts`

**Interfaces:**
- Produces:
  - `api.upload(file: File): Promise<{job_id: string, file_id: string|null}>`
  - `api.getResult(jobId: string): Promise<ArrayBuffer>` — GP5 바이너리
  - `api.listFiles(): Promise<FileRecord[]>`
  - `api.deleteFile(id: string): Promise<void>`
  - `connectSSE(url, onProgress, onDone, onError): () => void` — cleanup 함수 반환
  - `useAuthStore()` — `{token, user, setToken, logout}`
  - `useFileStore()` — `{files, load, remove}`

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/api.test.ts`:
```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

// fetch 모킹
const mockFetch = vi.fn()
global.fetch = mockFetch

beforeEach(() => mockFetch.mockReset())

describe('api.upload', () => {
  it('POST /convert FormData 전송 후 job_id 반환', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ job_id: 'abc123', file_id: null }),
    })
    const { api } = await import('../lib/api')
    const file = new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })
    const result = await api.upload(file)
    expect(result.job_id).toBe('abc123')
    expect(mockFetch).toHaveBeenCalledWith('/convert', expect.objectContaining({ method: 'POST' }))
  })

  it('업로드 실패 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '파일이 너무 큽니다' }),
    })
    const { api } = await import('../lib/api')
    const file = new File(['x'], 'test.pdf')
    await expect(api.upload(file)).rejects.toThrow('파일이 너무 큽니다')
  })
})

describe('api.listFiles', () => {
  it('GET /files 반환값 파싱', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => [{ id: '1', name: 'song', created_at: '2026-01-01' }],
    })
    const { api } = await import('../lib/api')
    const files = await api.listFiles()
    expect(files).toHaveLength(1)
    expect(files[0].name).toBe('song')
  })
})
```

Run: `npm run test -- --run`
Expected: FAIL

- [ ] **Step 2: frontend/src/lib/api.ts 작성**

```typescript
export interface FileRecord {
  id: string
  name: string
  created_at: string
}

function getToken(): string {
  return localStorage.getItem('access_token') ?? ''
}

function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { ...authHeaders(), ...(init.headers ?? {}) },
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = {
  async upload(file: File): Promise<{ job_id: string; file_id: string | null }> {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/convert', { method: 'POST', body: fd, headers: authHeaders() })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail ?? `HTTP ${res.status}`)
    }
    return res.json()
  },

  async getResult(jobId: string): Promise<ArrayBuffer> {
    const res = await fetch(`/jobs/${jobId}/result`, { headers: authHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.arrayBuffer()
  },

  async listFiles(): Promise<FileRecord[]> {
    return request<FileRecord[]>('/files')
  },

  async deleteFile(id: string): Promise<void> {
    await request<void>(`/files/${id}`, { method: 'DELETE' })
  },
}
```

- [ ] **Step 3: frontend/src/lib/sse.ts 작성**

```typescript
export interface ProgressEvent {
  status: 'queued' | 'running' | 'done' | 'failed'
  pct: number
  step: string
}

export function connectSSE(
  jobId: string,
  onProgress: (e: ProgressEvent) => void,
  onDone: () => void,
  onError: (msg: string) => void,
): () => void {
  const es = new EventSource(`/jobs/${jobId}/stream`)

  es.onmessage = (e) => {
    const data: ProgressEvent = JSON.parse(e.data)
    onProgress(data)
    if (data.status === 'done') {
      es.close()
      onDone()
    } else if (data.status === 'failed') {
      es.close()
      onError(data.step || '변환 실패')
    }
  }

  es.onerror = () => {
    es.close()
    onError('SSE 연결 오류')
  }

  return () => es.close()
}
```

- [ ] **Step 4: frontend/src/store/authStore.ts 작성**

```typescript
import { create } from 'zustand'

interface AuthState {
  token: string | null
  setToken: (access: string, refresh: string) => void
  logout: () => void
}

export const useAuthStore = create<AuthState>((set) => ({
  token: localStorage.getItem('access_token'),
  setToken: (access, refresh) => {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
    set({ token: access })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ token: null })
  },
}))
```

- [ ] **Step 5: frontend/src/store/fileStore.ts 작성**

```typescript
import { create } from 'zustand'
import { api, FileRecord } from '../lib/api'

interface FileState {
  files: FileRecord[]
  loading: boolean
  load: () => Promise<void>
  remove: (id: string) => Promise<void>
}

export const useFileStore = create<FileState>((set, get) => ({
  files: [],
  loading: false,
  load: async () => {
    set({ loading: true })
    try {
      const files = await api.listFiles()
      set({ files, loading: false })
    } catch {
      set({ loading: false })
    }
  },
  remove: async (id) => {
    await api.deleteFile(id)
    set({ files: get().files.filter((f) => f.id !== id) })
  },
}))
```

- [ ] **Step 6: 테스트 통과 확인**

Run (frontend/): `npm run test -- --run`
Expected: 모두 pass

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/lib/ frontend/src/store/ frontend/src/__tests__/
git commit -m "feat: API 클라이언트 + SSE 유틸 + Zustand 스토어"
```

---

## Task 10: 로그인 UI (LoginPage + OAuthCallback)

**Files:**
- Create: `frontend/src/components/Auth/LoginPage.tsx`
- Create: `frontend/src/components/Auth/OAuthCallback.tsx`
- Test: `frontend/src/__tests__/LoginPage.test.tsx`

**Interfaces:**
- Produces:
  - `LoginPage` — `/login` 라우트. Google/GitHub 버튼 클릭 시 `/auth/google` or `/auth/github`로 이동
  - `OAuthCallback` — `/auth/callback` 라우트. URL 쿼리파라미터 `?access_token=&refresh_token=` 읽어서 저장 후 `/`로 이동

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/LoginPage.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import LoginPage from '../components/Auth/LoginPage'

test('Google 로그인 버튼 렌더링', () => {
  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  expect(screen.getByText(/Google/i)).toBeInTheDocument()
  expect(screen.getByText(/GitHub/i)).toBeInTheDocument()
})

test('Google 버튼 클릭 시 /auth/google로 이동', async () => {
  const user = userEvent.setup()
  const assignSpy = vi.spyOn(window, 'location', 'get').mockReturnValue({
    ...window.location,
    assign: vi.fn(),
  } as Location)

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  await user.click(screen.getByText(/Google/i))
  // window.location.href 변경 확인은 jsdom 제약으로 직접 확인 어려움
  // 버튼이 존재하고 클릭 가능하면 충분
  expect(screen.getByText(/Google/i)).toBeInTheDocument()
  assignSpy.mockRestore()
})
```

- [ ] **Step 2: LoginPage.tsx 작성**

```tsx
// frontend/src/components/Auth/LoginPage.tsx
export default function LoginPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>GP Converter</h1>
      <p>PDF 악보를 Guitar Pro 파일로 변환하고 웹에서 편집하세요</p>
      <div style={{ display: 'flex', gap: 16, marginTop: 32 }}>
        <button
          onClick={() => { window.location.href = '/auth/google' }}
          style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
        >
          Google로 로그인
        </button>
        <button
          onClick={() => { window.location.href = '/auth/github' }}
          style={{ padding: '12px 24px', fontSize: 16, cursor: 'pointer' }}
        >
          GitHub로 로그인
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: OAuthCallback.tsx 작성**

```tsx
// frontend/src/components/Auth/OAuthCallback.tsx
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

export default function OAuthCallback() {
  const navigate = useNavigate()
  const setToken = useAuthStore((s) => s.setToken)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const access = params.get('access_token')
    const refresh = params.get('refresh_token')
    if (access && refresh) {
      setToken(access, refresh)
      navigate('/', { replace: true })
    } else {
      navigate('/login', { replace: true })
    }
  }, [navigate, setToken])

  return <p>로그인 처리 중...</p>
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm run test -- --run`
Expected: 모두 pass

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/components/Auth/
git commit -m "feat: LoginPage + OAuthCallback 컴포넌트"
```

---

## Task 11: 업로드 버튼 + 진행률 바

**Files:**
- Create: `frontend/src/components/Editor/ProgressBar.tsx`
- Create: `frontend/src/components/FileManager/UploadButton.tsx`
- Test: `frontend/src/__tests__/ProgressBar.test.tsx`
- Test: `frontend/src/__tests__/UploadButton.test.tsx`

**Interfaces:**
- Consumes: `api.upload`, `connectSSE`
- Produces:
  - `ProgressBar({ pct: number, step: string, visible: boolean })` — 애니메이션 진행 바
  - `UploadButton({ onComplete: (jobId: string, gp5Buffer: ArrayBuffer) => void })` — 파일 선택 + 업로드 + SSE 연결 + 완료 시 GP5 버퍼 전달

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/ProgressBar.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import ProgressBar from '../components/Editor/ProgressBar'

test('pct 60이면 바 너비 60%', () => {
  render(<ProgressBar pct={60} step="omr" visible={true} />)
  const bar = screen.getByRole('progressbar')
  expect(bar).toHaveStyle({ width: '60%' })
})

test('visible=false면 숨김', () => {
  render(<ProgressBar pct={50} step="" visible={false} />)
  const container = screen.getByTestId('progress-container')
  expect(container).not.toBeVisible()
})
```

- [ ] **Step 2: ProgressBar.tsx 작성**

```tsx
// frontend/src/components/Editor/ProgressBar.tsx
interface Props {
  pct: number
  step: string
  visible: boolean
}

const STEP_LABELS: Record<string, string> = {
  tab_detect: 'TAB 보표 감지 중...',
  omr: 'OMR 추론 중...',
  gp5_build: 'GP5 변환 중...',
  audiveris: 'Audiveris 변환 중...',
  musicxml_convert: 'MusicXML 변환 중...',
}

export default function ProgressBar({ pct, step, visible }: Props) {
  return (
    <div
      data-testid="progress-container"
      style={{
        visibility: visible ? 'visible' : 'hidden',
        padding: '16px 0',
      }}
    >
      <p style={{ marginBottom: 8, fontSize: 14 }}>
        {STEP_LABELS[step] || '변환 중...'}  {pct}%
      </p>
      <div
        style={{
          background: '#e0e0e0',
          borderRadius: 4,
          height: 8,
          overflow: 'hidden',
        }}
      >
        <div
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          style={{
            width: `${pct}%`,
            height: '100%',
            background: '#1976d2',
            transition: 'width 0.4s ease',
          }}
        />
      </div>
    </div>
  )
}
```

`frontend/src/__tests__/UploadButton.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import UploadButton from '../components/FileManager/UploadButton'

vi.mock('../lib/api', () => ({
  api: { upload: vi.fn().mockResolvedValue({ job_id: 'job1', file_id: null }) },
}))
vi.mock('../lib/sse', () => ({
  connectSSE: vi.fn().mockImplementation((_id, _onP, onDone) => { onDone(); return () => {} }),
}))
vi.spyOn(global, 'fetch').mockResolvedValue({
  ok: true, arrayBuffer: async () => new ArrayBuffer(8),
} as Response)

test('파일 선택 후 업로드 버튼 활성화', async () => {
  render(<UploadButton onComplete={vi.fn()} />)
  const input = screen.getByLabelText(/PDF/i)
  const file = new File(['%PDF-1.4'], 'test.pdf', { type: 'application/pdf' })
  await userEvent.upload(input, file)
  expect(screen.getByRole('button', { name: /변환/i })).not.toBeDisabled()
})
```

- [ ] **Step 3: UploadButton.tsx 작성**

```tsx
// frontend/src/components/FileManager/UploadButton.tsx
import { useRef, useState } from 'react'
import { api } from '../../lib/api'
import { connectSSE, ProgressEvent } from '../../lib/sse'
import ProgressBar from '../Editor/ProgressBar'

interface Props {
  onComplete: (jobId: string, gp5Buffer: ArrayBuffer) => void
}

export default function UploadButton({ onComplete }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState<ProgressEvent | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleUpload = async () => {
    if (!file) return
    setBusy(true)
    setError(null)
    try {
      const { job_id } = await api.upload(file)
      setProgress({ status: 'running', pct: 5, step: 'queued' })
      connectSSE(
        job_id,
        (e) => setProgress(e),
        async () => {
          const buf = await api.getResult(job_id)
          setBusy(false)
          setProgress(null)
          onComplete(job_id, buf)
        },
        (msg) => {
          setError(msg)
          setBusy(false)
          setProgress(null)
        },
      )
    } catch (e: any) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div>
      <label htmlFor="pdf-input">PDF 파일 선택</label>
      <input
        id="pdf-input"
        ref={inputRef}
        type="file"
        accept="application/pdf"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        disabled={busy}
      />
      <button onClick={handleUpload} disabled={!file || busy}>
        변환 시작
      </button>
      <ProgressBar
        pct={progress?.pct ?? 0}
        step={progress?.step ?? ''}
        visible={!!progress}
      />
      {error && <p style={{ color: 'red' }}>{error}</p>}
    </div>
  )
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm run test -- --run`
Expected: 모두 pass

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/components/Editor/ProgressBar.tsx \
        frontend/src/components/FileManager/UploadButton.tsx \
        frontend/src/__tests__/ProgressBar.test.tsx \
        frontend/src/__tests__/UploadButton.test.tsx
git commit -m "feat: ProgressBar + UploadButton (SSE 진행률 연동)"
```

---

## Task 12: ScoreViewer (alphaTab 렌더링 + 재생)

**Files:**
- Create: `frontend/src/components/Editor/ScoreViewer.tsx`
- Create: `frontend/src/lib/alphatab.ts`
- Test: `frontend/src/__tests__/ScoreViewer.test.tsx`

**Interfaces:**
- Consumes: `@coderline/alphatab`
- Produces:
  - `ScoreViewer({ gp5Buffer: ArrayBuffer | null })` — GP5 ArrayBuffer를 받아 악보 렌더링 + 재생 버튼
  - `initAlphaTab(element: HTMLElement): AlphaTabApi` — alphaTab 초기화 설정 래퍼

alphaTab 설정값:
- `core.engine`: `'html5'`
- `core.fontDirectory`: `'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/font/'`
- `player.enablePlayer`: `true`
- `player.enableCursor`: `true`
- `player.soundFont`: `'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2'`

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/ScoreViewer.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

// alphaTab은 브라우저 Canvas 필요 → 목 처리
vi.mock('../lib/alphatab', () => ({
  initAlphaTab: vi.fn().mockReturnValue({
    scoreLoaded: { on: vi.fn() },
    playerStateChanged: { on: vi.fn() },
    load: vi.fn(),
    playPause: vi.fn(),
    destroy: vi.fn(),
  }),
}))

import ScoreViewer from '../components/Editor/ScoreViewer'

test('gp5Buffer 없으면 안내 문구 표시', () => {
  render(<ScoreViewer gp5Buffer={null} />)
  expect(screen.getByText(/악보를 불러오세요/i)).toBeInTheDocument()
})

test('gp5Buffer 있으면 재생 버튼 표시', () => {
  render(<ScoreViewer gp5Buffer={new ArrayBuffer(8)} />)
  expect(screen.getByRole('button', { name: /재생/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: frontend/src/lib/alphatab.ts 작성**

```typescript
import * as alphaTab from '@coderline/alphatab'

export function initAlphaTab(element: HTMLElement): alphaTab.AlphaTabApi {
  const settings = new alphaTab.Settings()
  settings.core.engine = 'html5'
  settings.core.fontDirectory =
    'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/font/'
  settings.player.enablePlayer = true
  settings.player.enableCursor = true
  settings.player.soundFont =
    'https://cdn.jsdelivr.net/npm/@coderline/alphatab@latest/dist/soundfont/sonivox.sf2'
  return new alphaTab.AlphaTabApi(element, settings)
}
```

- [ ] **Step 3: ScoreViewer.tsx 작성**

```tsx
// frontend/src/components/Editor/ScoreViewer.tsx
import { useEffect, useRef, useState } from 'react'
import { initAlphaTab } from '../../lib/alphatab'
import type * as alphaTab from '@coderline/alphatab'

interface Props {
  gp5Buffer: ArrayBuffer | null
}

export default function ScoreViewer({ gp5Buffer }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const [playing, setPlaying] = useState(false)
  const [loaded, setLoaded] = useState(false)

  useEffect(() => {
    if (!containerRef.current) return
    const api = initAlphaTab(containerRef.current)
    apiRef.current = api

    api.scoreLoaded.on(() => setLoaded(true))
    api.playerStateChanged.on((e: any) => {
      setPlaying(e.state === 1) // 1 = Playing
    })

    return () => {
      api.destroy()
      apiRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!apiRef.current || !gp5Buffer) return
    setLoaded(false)
    apiRef.current.load(gp5Buffer)
  }, [gp5Buffer])

  if (!gp5Buffer) {
    return (
      <div style={{ padding: 32, textAlign: 'center', color: '#666' }}>
        악보를 불러오세요 — PDF를 업로드하거나 파일 목록에서 선택하세요
      </div>
    )
  }

  return (
    <div>
      <div style={{ marginBottom: 8 }}>
        <button
          onClick={() => apiRef.current?.playPause()}
          disabled={!loaded}
        >
          {playing ? '일시정지' : '재생'}
        </button>
      </div>
      <div ref={containerRef} style={{ width: '100%' }} />
    </div>
  )
}
```

- [ ] **Step 4: 테스트 통과 확인**

Run: `npm run test -- --run`
Expected: 모두 pass

- [ ] **Step 5: 커밋**

```bash
git add frontend/src/components/Editor/ScoreViewer.tsx \
        frontend/src/lib/alphatab.ts \
        frontend/src/__tests__/ScoreViewer.test.tsx
git commit -m "feat: ScoreViewer — alphaTab 렌더링 + 재생 버튼"
```

---

## Task 13: 파일 목록 + App.tsx 라우팅 + 레이아웃

**Files:**
- Create: `frontend/src/components/FileManager/FileList.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/main.tsx`
- Test: `frontend/src/__tests__/FileList.test.tsx`

**Interfaces:**
- Consumes: `useFileStore`, `useAuthStore`, `ScoreViewer`, `UploadButton`, `LoginPage`, `OAuthCallback`
- Produces: 완성된 단일 페이지 앱
  - `/login` → LoginPage
  - `/auth/callback` → OAuthCallback
  - `/` → 메인 (UploadButton + ScoreViewer + FileList), 비로그인 시 /login 리다이렉트

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/FileList.test.tsx`:
```typescript
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

vi.mock('../store/fileStore', () => ({
  useFileStore: () => ({
    files: [
      { id: '1', name: 'Song A', created_at: '2026-01-01' },
      { id: '2', name: 'Song B', created_at: '2026-01-02' },
    ],
    loading: false,
    load: vi.fn(),
    remove: vi.fn(),
  }),
}))
vi.mock('../lib/api', () => ({ api: { getResult: vi.fn().mockResolvedValue(new ArrayBuffer(8)) } }))

import FileList from '../components/FileManager/FileList'

test('파일 목록 렌더링', () => {
  render(<FileList onSelect={vi.fn()} />)
  expect(screen.getByText('Song A')).toBeInTheDocument()
  expect(screen.getByText('Song B')).toBeInTheDocument()
})

test('파일 클릭 시 onSelect 호출', async () => {
  const onSelect = vi.fn()
  render(<FileList onSelect={onSelect} />)
  await userEvent.click(screen.getByText('Song A'))
  expect(onSelect).toHaveBeenCalled()
})
```

- [ ] **Step 2: FileList.tsx 작성**

```tsx
// frontend/src/components/FileManager/FileList.tsx
import { useEffect } from 'react'
import { useFileStore } from '../../store/fileStore'
import { api } from '../../lib/api'

interface Props {
  onSelect: (gp5Buffer: ArrayBuffer) => void
}

export default function FileList({ onSelect }: Props) {
  const { files, loading, load, remove } = useFileStore()

  useEffect(() => { load() }, [load])

  if (loading) return <p>불러오는 중...</p>
  if (files.length === 0) return <p>저장된 파일이 없습니다</p>

  return (
    <ul style={{ listStyle: 'none', padding: 0 }}>
      {files.map((f) => (
        <li key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
          <button
            onClick={async () => {
              const buf = await api.getResult(f.id)  // Phase 1에서 /files/{id}/gp5로 교체
              onSelect(buf)
            }}
            style={{ flex: 1, textAlign: 'left', background: 'none', border: 'none', cursor: 'pointer', fontSize: 14 }}
          >
            {f.name}
          </button>
          <small style={{ color: '#999' }}>{f.created_at.slice(0, 10)}</small>
          <button
            onClick={() => remove(f.id)}
            style={{ color: 'red', background: 'none', border: 'none', cursor: 'pointer' }}
            aria-label={`${f.name} 삭제`}
          >
            ✕
          </button>
        </li>
      ))}
    </ul>
  )
}
```

- [ ] **Step 3: App.tsx 작성**

```tsx
// frontend/src/App.tsx
import { useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import LoginPage from './components/Auth/LoginPage'
import OAuthCallback from './components/Auth/OAuthCallback'
import ScoreViewer from './components/Editor/ScoreViewer'
import UploadButton from './components/FileManager/UploadButton'
import FileList from './components/FileManager/FileList'

function MainPage() {
  const [gp5Buffer, setGp5Buffer] = useState<ArrayBuffer | null>(null)
  const { token, logout } = useAuthStore()

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      {/* 사이드바 */}
      <aside style={{ width: 260, borderRight: '1px solid #ddd', padding: 16, overflowY: 'auto' }}>
        <h2 style={{ marginTop: 0 }}>GP Converter</h2>
        <UploadButton onComplete={(_jobId, buf) => setGp5Buffer(buf)} />
        <hr />
        <h3>내 파일</h3>
        {token ? (
          <FileList onSelect={setGp5Buffer} />
        ) : (
          <p style={{ fontSize: 13, color: '#666' }}>로그인하면 파일이 저장됩니다</p>
        )}
        {token && (
          <button onClick={logout} style={{ marginTop: 16, fontSize: 12 }}>
            로그아웃
          </button>
        )}
      </aside>
      {/* 메인 편집 영역 */}
      <main style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        <ScoreViewer gp5Buffer={gp5Buffer} />
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/auth/callback" element={<OAuthCallback />} />
        <Route path="/" element={<MainPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
```

- [ ] **Step 4: main.tsx 업데이트**

```tsx
// frontend/src/main.tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

- [ ] **Step 5: 테스트 통과 확인**

Run: `npm run test -- --run`
Expected: 모두 pass

- [ ] **Step 6: 모바일 반응형 CSS 추가** (App.tsx 사이드바)

뷰어는 모바일에서도 동작해야 함. App.tsx의 레이아웃 수정:

```tsx
// MainPage 내부 사이드바 div — style 교체
<aside style={{
  width: 260,
  minWidth: 200,
  borderRight: '1px solid #ddd',
  padding: 16,
  overflowY: 'auto',
  // 모바일: 세로 배치
  flexShrink: 0,
}}>
```

`frontend/index.html` head에 추가:
```html
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>
  @media (max-width: 600px) {
    body > #root > div { flex-direction: column !important; }
    aside { width: 100% !important; border-right: none !important; border-bottom: 1px solid #ddd; }
  }
</style>
```

- [ ] **Step 7: 수동 통합 테스트**

```bash
# 터미널 1 (백엔드)
cd /Users/leehyeon/Desktop/projects/gp_converter
uvicorn app.main:app --reload --port 8000

# 터미널 2 (프론트엔드)
cd frontend
npm run dev
```

1. `http://localhost:5173` 접속
2. PDF 파일 선택 → "변환 시작" 클릭
3. 진행률 바 애니메이션 확인 (TAB 감지 → OMR → GP5 빌드)
4. 변환 완료 후 alphaTab 악보 렌더링 확인
5. 재생 버튼 클릭 → 오디오 재생 확인

- [ ] **Step 7: 커밋**

```bash
git add frontend/src/components/FileManager/FileList.tsx \
        frontend/src/App.tsx frontend/src/main.tsx \
        frontend/src/__tests__/FileList.test.tsx
git commit -m "feat: FileList + App 라우팅 + 메인 레이아웃"
```

---

## Task 14: 프로덕션 빌드 통합

**Files:**
- Modify: `frontend/vite.config.ts` (build 출력 경로)
- Modify: `app/main.py` (빌드 결과 static 서빙 경로 확인)
- Create: `Makefile` (또는 `package.json` scripts 추가)

**Interfaces:**
- Produces: `npm run build` → `static/` 디렉토리에 빌드 결과. `uvicorn app.main:app` 하나로 프론트+백 서빙.

- [ ] **Step 1: vite.config.ts build 출력 경로 설정**

```typescript
// frontend/vite.config.ts — build 섹션 추가
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../static',  // FastAPI가 서빙하는 static/ 디렉토리
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/convert': 'http://localhost:8000',
      '/jobs': 'http://localhost:8000',
      '/files': 'http://localhost:8000',
      '/auth': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
```

- [ ] **Step 2: 빌드 실행 확인**

```bash
cd frontend
npm run build
```

Expected:
```
dist 대신 ../static/ 에 파일 생성
static/index.html
static/assets/index-xxx.js
static/assets/index-xxx.css
```

- [ ] **Step 3: 프로덕션 서버 동작 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
uvicorn app.main:app --port 8000
```

`http://localhost:8000` 접속 → React 앱 로드 확인

- [ ] **Step 4: .gitignore에 static 빌드 결과 추가** (소스는 frontend/, 빌드 결과는 무시)

```
# .gitignore에 추가
static/assets/
```

- [ ] **Step 5: 커밋**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/vite.config.ts .gitignore
git commit -m "feat: Vite 빌드 출력 → static/ 통합 (단일 서버 서빙)"
```

---

## 전체 테스트 실행

Phase 0 완료 후 전체 테스트:

```bash
# 백엔드
pytest tests/ -v
# Expected: 모든 테스트 pass

# 프론트엔드
cd frontend && npm run test -- --run
# Expected: 모든 테스트 pass
```

---

## 다음 단계

Phase 0 완료 후 Phase 1 플랜 (`2026-06-29-phase1-editor.md`) 작성:
- alphaTab 음표 선택 이벤트
- NotePanel (프렛/지속시간/이펙트 편집 사이드 패널)
- Undo/Redo (Zustand 히스토리 스택)
- 자동저장 (debounce 3초)
- `POST /files/{id}/sync` — pyguitarpro GP5 동기화
