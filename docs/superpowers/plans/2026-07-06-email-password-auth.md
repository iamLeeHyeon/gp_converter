# 자체가입(이메일+비밀번호) 인증 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 기존 Google/GitHub OAuth 로그인과 공존하는 이메일+비밀번호 자체가입/로그인/이메일인증/비밀번호재설정 기능을 추가한다.

**Architecture:** `User` 모델에 컬럼 6개 추가(마이그레이션 가드 확장) → SMTP 발송 인프라(`app/email.py` + Celery task 2개) → 회원가입/이메일인증/재발송 API → 로그인/`/auth/me`/`/convert` 게이트 → 비밀번호재설정 API → Redis 기반 레이트리밋 → 프론트엔드 폼 4종.

**Tech Stack:** FastAPI, SQLAlchemy(SQLite), `bcrypt`(신규), `smtplib`(표준라이브러리), 기존 Celery+Redis 인프라 재사용.

## Global Constraints

- SQLite 마이그레이션은 `ALTER TABLE ADD COLUMN`만 사용(기존 `provider`/`provider_id` 컬럼의 nullable 여부는 바꾸지 않는다). 각 컬럼 추가는 `if 컬럼명 not in cols` 가드, 인덱스 생성은 컬럼 존재 여부와 무관하게 매번 무조건 실행(`CREATE UNIQUE INDEX IF NOT EXISTS`) — 기존 `run_sqlite_migrations` 컨벤션 그대로.
- `email_verified` 컬럼은 SQLAlchemy 모델 레벨에서 `default=True`(OAuth 계정은 이미 검증된 이메일이므로), 마이그레이션 DDL에서도 `DEFAULT 1`로 기존 행을 백필. 자체가입 코드만 명시적으로 `False`를 넣는다. **기존 `google_callback`/`github_callback` 코드는 이 스펙에서 손대지 않는다** — 컬럼 기본값만으로 충분하다.
- 자체가입 계정은 `provider="password"`, `provider_id=email`로 채운다(제약조건 만족용, 조회에는 안 씀).
- `SMTP_HOST` 미설정 시 `send_email()`은 예외 없이 로그만 남기고 반환한다(dev/test 환경에서 실제 SMTP 없이도 전체 스위트가 통과해야 함) — 이건 버그가 아니라 의도된 폴백이다.
- 레이트리밋은 Redis 장애 시 요청을 막지 않는다(fail-open) — 로그인 자체가 Redis 장애로 막히면 안 됨.
- 계정 존재 여부를 유추할 수 있는 응답 차이를 만들지 않는다: `login` 실패는 항상 동일 메시지, `forgot-password`/`resend-verification`은 항상 동일한 200 메시지.
- 기존 테스트 컨벤션을 따른다: Celery task는 `.delay()` 없이 직접 호출 가능해야 하고(브로커 불필요), 테스트는 `tests/conftest.py`의 더미 환경변수 + `app.database.SessionLocal`(실제 설정된 DB) + `TestClient(app)` + `create_access_token()`으로 만든 진짜 JWT를 쓰는 `tests/test_billing.py` 스타일을 따른다(테스트 격리를 위한 별도 in-memory 엔진을 새로 만들지 않는다).

---

### Task 1: 데이터 모델 + 마이그레이션 + bcrypt 의존성

**Files:**
- Modify: `requirements.txt`
- Modify: `app/models.py`
- Modify: `app/database.py`
- Test: `tests/test_database_migration.py` (확장)
- Test: `tests/test_models_password_auth.py` (신규)

**Interfaces:**
- Produces: `User.password_hash: Optional[str]`, `User.email_verified: bool`(기본 `True`), `User.verification_token: Optional[str]`, `User.verification_token_expires_at: Optional[datetime]`, `User.reset_token: Optional[str]`, `User.reset_token_expires_at: Optional[datetime]` — Task 2~5가 이 컬럼들을 그대로 씀.

- [ ] **Step 1: requirements.txt에 bcrypt 추가**

`requirements.txt` 맨 끝에 추가:

```
bcrypt>=4.0,<5
```

- [ ] **Step 2: bcrypt 설치**

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

- [ ] **Step 3: User 모델에 컬럼 6개 추가**

`app/models.py`의 import 줄(1번째 줄 근처)을 아래로 교체:

```python
import uuid
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean
from sqlalchemy.sql import func
from app.database import Base
```

`class User(Base):` 블록(현재 `app/models.py:11-19`)을 아래로 교체:

```python
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False)
    provider_id = Column(String, nullable=False)
    plan = Column(String, nullable=False, default="free")
    stripe_customer_id = Column(String, unique=True, nullable=True, index=True)
    password_hash = Column(String, nullable=True)
    email_verified = Column(Boolean, nullable=False, default=True)
    verification_token = Column(String, unique=True, nullable=True, index=True)
    verification_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    reset_token = Column(String, unique=True, nullable=True, index=True)
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: 마이그레이션 가드 확장**

`app/database.py`의 `if "users" in tables:` 블록(현재 `app/database.py:50-57`)을 아래로 교체:

```python
        if "users" in tables:
            user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
            if "stripe_customer_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id "
                "ON users (stripe_customer_id)"
            ))
            if "password_hash" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR"))
            if "email_verified" not in user_cols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT 1"
                ))
            if "verification_token" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN verification_token VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_verification_token "
                "ON users (verification_token)"
            ))
            if "verification_token_expires_at" not in user_cols:
                conn.execute(text(
                    "ALTER TABLE users ADD COLUMN verification_token_expires_at DATETIME"
                ))
            if "reset_token" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN reset_token VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_reset_token "
                "ON users (reset_token)"
            ))
            if "reset_token_expires_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN reset_token_expires_at DATETIME"))
```

- [ ] **Step 5: 마이그레이션 테스트 작성(실패 확인 전 상태로)**

`tests/test_database_migration.py` 맨 끝에 추가:

```python
def test_migration_adds_password_auth_columns(tmp_path):
    """구버전 users 테이블에 password_hash/email_verified 등 6개 컬럼을 추가한다."""
    db_path = tmp_path / "old_users_pw.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE users ("
            "id VARCHAR PRIMARY KEY, email VARCHAR, provider VARCHAR, "
            "provider_id VARCHAR, plan VARCHAR, created_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(users)"))}
    assert "password_hash" in cols
    assert "email_verified" in cols
    assert "verification_token" in cols
    assert "verification_token_expires_at" in cols
    assert "reset_token" in cols
    assert "reset_token_expires_at" in cols


def test_migration_backfills_email_verified_true_for_existing_rows(tmp_path):
    """기존(마이그레이션 전) 행은 전부 OAuth로 만들어졌으므로 email_verified가 True로 백필돼야 한다."""
    db_path = tmp_path / "old_users_pw2.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE users ("
            "id VARCHAR PRIMARY KEY, email VARCHAR, provider VARCHAR, "
            "provider_id VARCHAR, plan VARCHAR, created_at DATETIME)"
        ))
        conn.execute(sa.text(
            "INSERT INTO users (id, email, provider, provider_id) "
            "VALUES ('u1', 'a@x.com', 'google', 'gid1')"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        row = conn.execute(sa.text("SELECT email_verified FROM users WHERE id='u1'")).fetchone()
    assert row[0] == 1


def test_migration_creates_unique_index_on_verification_token(tmp_path):
    """verification_token에 unique index가 생성되어야 한다."""
    db_path = tmp_path / "old_users_pw3.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE users ("
            "id VARCHAR PRIMARY KEY, email VARCHAR, provider VARCHAR, "
            "provider_id VARCHAR, plan VARCHAR, created_at DATETIME)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)

    with engine.connect() as conn:
        conn.execute(sa.text(
            "INSERT INTO users (id, email, provider, provider_id, verification_token) "
            "VALUES ('u1', 'a@x.com', 'password', 'a@x.com', 'tok123')"
        ))
        conn.commit()

    with engine.connect() as conn:
        try:
            conn.execute(sa.text(
                "INSERT INTO users (id, email, provider, provider_id, verification_token) "
                "VALUES ('u2', 'b@x.com', 'password', 'b@x.com', 'tok123')"
            ))
            conn.commit()
            raise AssertionError("중복 verification_token insert가 실패해야 하는데 성공함")
        except sa.exc.IntegrityError:
            pass
```

- [ ] **Step 6: 마이그레이션 테스트 실행**

Run: `source .venv/bin/activate && pytest tests/test_database_migration.py -v`
Expected: 신규 3개 포함 전부 PASS

- [ ] **Step 7: User 모델 기본값 테스트 작성**

`tests/test_models_password_auth.py` (신규):

```python
from app.database import SessionLocal
from app.models import User


def test_new_oauth_user_defaults_email_verified_true():
    """provider/provider_id만 채우고 만든 User는 email_verified 기본값이 True여야 한다."""
    db = SessionLocal()
    try:
        user = User(id="pwtest-oauth-1", email="oauth1@x.com", provider="google", provider_id="g1")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.email_verified is True
        assert user.password_hash is None
    finally:
        db.query(User).filter_by(id="pwtest-oauth-1").delete()
        db.commit()
        db.close()


def test_password_user_can_set_email_verified_false():
    """자체가입 코드는 email_verified=False를 명시적으로 넣을 수 있어야 한다."""
    db = SessionLocal()
    try:
        user = User(
            id="pwtest-pw-1", email="pw1@x.com", provider="password", provider_id="pw1@x.com",
            password_hash="hashed", email_verified=False,
            verification_token="tok-abc",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.email_verified is False
        assert user.verification_token == "tok-abc"
    finally:
        db.query(User).filter_by(id="pwtest-pw-1").delete()
        db.commit()
        db.close()
```

- [ ] **Step 8: 테스트 실행**

Run: `source .venv/bin/activate && pytest tests/test_models_password_auth.py tests/test_database_migration.py -v`
Expected: 전부 PASS

- [ ] **Step 9: Commit**

```bash
git add requirements.txt app/models.py app/database.py tests/test_database_migration.py tests/test_models_password_auth.py
git commit -m "feat: User에 비밀번호/이메일인증 컬럼 추가 + 마이그레이션 가드"
```

---

### Task 2: 이메일 발송 인프라 (SMTP + Celery task)

**Files:**
- Create: `app/email.py`
- Modify: `app/tasks.py`
- Test: `tests/test_email.py` (신규)
- Test: `tests/test_email_tasks.py` (신규)

**Interfaces:**
- Consumes: Task 1의 `User.verification_token`/`User.reset_token`.
- Produces: `send_email(to: str, subject: str, html_body: str) -> None` (`app/email.py`), `send_verification_email_task(user_id: str) -> None`/`send_reset_email_task(user_id: str) -> None`(`app/tasks.py`, Celery task) — Task 3/5가 `.delay()`로 디스패치.

- [ ] **Step 1: send_email 실패 테스트 작성**

`tests/test_email.py` (신규):

```python
import os
from unittest.mock import patch, MagicMock


def test_send_email_skips_when_smtp_host_unset(monkeypatch):
    """SMTP_HOST 미설정이면 예외 없이 조용히 스킵한다."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    from app.email import send_email
    with patch("smtplib.SMTP") as mock_smtp:
        send_email("to@x.com", "제목", "<p>본문</p>")
    mock_smtp.assert_not_called()


def test_send_email_sends_via_smtp_with_tls(monkeypatch):
    """SMTP_HOST 설정 시 실제로 SMTP 서버에 접속해서 발송한다."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")

    from app.email import send_email
    mock_server = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_server
    with patch("smtplib.SMTP", return_value=mock_smtp_cm) as mock_smtp:
        send_email("to@x.com", "제목", "<p>본문</p>")

    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user@example.com", "app-password")
    mock_server.send_message.assert_called_once()
    sent_msg = mock_server.send_message.call_args[0][0]
    assert sent_msg["To"] == "to@x.com"
    assert sent_msg["From"] == "noreply@example.com"
    assert sent_msg["Subject"] == "제목"


def test_send_email_skips_tls_and_login_when_disabled(monkeypatch):
    """SMTP_USE_TLS=false + SMTP_USERNAME 없으면 starttls/login을 호출하지 않는다."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)

    from app.email import send_email
    mock_server = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_server
    with patch("smtplib.SMTP", return_value=mock_smtp_cm):
        send_email("to@x.com", "제목", "<p>본문</p>")

    mock_server.starttls.assert_not_called()
    mock_server.login.assert_not_called()
    mock_server.send_message.assert_called_once()
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_email.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.email'`

- [ ] **Step 3: app/email.py 구현**

```python
import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str) -> None:
    """SMTP_HOST 미설정 시 조용히 로그만 남기고 스킵한다(dev/test 환경 대비 의도된 동작)."""
    host = os.getenv("SMTP_HOST")
    if not host:
        logger.info("[SMTP_HOST 미설정 — 이메일 발송 스킵] to=%s subject=%s", to, subject)
        return

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM_EMAIL", username)
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() != "false"

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to

    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password)
        server.send_message(msg)
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_email.py -v`
Expected: 3개 전부 PASS

- [ ] **Step 5: Celery task 테스트 작성**

`tests/test_email_tasks.py` (신규):

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.database import SessionLocal
from app.models import User


def _make_user(uid, **kwargs):
    db = SessionLocal()
    user = User(id=uid, email=f"{uid}@x.com", provider="password", provider_id=f"{uid}@x.com",
                password_hash="h", email_verified=False, **kwargs)
    db.add(user)
    db.commit()
    db.close()


def _cleanup(uid):
    db = SessionLocal()
    db.query(User).filter_by(id=uid).delete()
    db.commit()
    db.close()


def test_send_verification_email_task_sends_link_with_token():
    _make_user(
        "task-verify-1",
        verification_token="verify-tok-1",
        verification_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    try:
        from app.tasks import send_verification_email_task
        with patch("app.tasks.send_email") as mock_send:
            send_verification_email_task("task-verify-1")
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[0] == "task-verify-1@x.com"
        assert "verify-tok-1" in args[2]
    finally:
        _cleanup("task-verify-1")


def test_send_verification_email_task_noop_if_no_token():
    _make_user("task-verify-2")
    try:
        from app.tasks import send_verification_email_task
        with patch("app.tasks.send_email") as mock_send:
            send_verification_email_task("task-verify-2")
        mock_send.assert_not_called()
    finally:
        _cleanup("task-verify-2")


def test_send_reset_email_task_sends_link_with_token():
    _make_user(
        "task-reset-1",
        reset_token="reset-tok-1",
        reset_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    try:
        from app.tasks import send_reset_email_task
        with patch("app.tasks.send_email") as mock_send:
            send_reset_email_task("task-reset-1")
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[0] == "task-reset-1@x.com"
        assert "reset-tok-1" in args[2]
    finally:
        _cleanup("task-reset-1")


def test_email_tasks_callable_without_broker():
    """Celery task 데코레이터가 붙어도 일반 함수처럼 직접 호출 가능해야 한다."""
    from app.tasks import send_verification_email_task, send_reset_email_task
    assert hasattr(send_verification_email_task, "delay")
    assert hasattr(send_reset_email_task, "delay")
```

- [ ] **Step 6: 테스트 실행해서 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_tasks.py -v`
Expected: FAIL — `ImportError: cannot import name 'send_verification_email_task'`

- [ ] **Step 7: app/tasks.py에 task 2개 추가**

`app/tasks.py` 전체를 아래로 교체:

```python
import os
from typing import Optional

from app.celery_app import celery_app
from app.database import SessionLocal
from app.email import send_email
from app.jobs import JobStore
from app.models import User
from app.worker import process_job

_FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
_BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


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


@celery_app.task(name="gp_converter.send_verification_email")
def send_verification_email_task(user_id: str) -> None:
    """워커 프로세스 안에서 DB 세션을 새로 만들어 user_id로 유저를 재조회한다."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.verification_token:
            return
        link = f"{_BACKEND_URL}/auth/verify?token={user.verification_token}"
        send_email(
            user.email,
            "GP Converter 이메일 인증",
            f'<p>아래 링크를 눌러 이메일을 인증해주세요 (24시간 이내):</p>'
            f'<p><a href="{link}">{link}</a></p>',
        )
    finally:
        db.close()


@celery_app.task(name="gp_converter.send_reset_email")
def send_reset_email_task(user_id: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.reset_token:
            return
        link = f"{_FRONTEND_URL}/reset-password?token={user.reset_token}"
        send_email(
            user.email,
            "GP Converter 비밀번호 재설정",
            f'<p>아래 링크를 눌러 비밀번호를 재설정해주세요 (1시간 이내):</p>'
            f'<p><a href="{link}">{link}</a></p>',
        )
    finally:
        db.close()
```

- [ ] **Step 8: 테스트 실행해서 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_tasks.py -v`
Expected: 4개 전부 PASS

- [ ] **Step 9: Commit**

```bash
git add app/email.py app/tasks.py tests/test_email.py tests/test_email_tasks.py
git commit -m "feat: SMTP 이메일 발송 인프라 + 인증/재설정 Celery task 추가"
```

---

### Task 3: 회원가입 + 이메일인증 + 재발송 API

**Files:**
- Modify: `app/routers/auth.py`
- Test: `tests/test_email_password_auth.py` (신규, 이 태스크에서 회원가입/인증/재발송 부분만 작성 — 로그인/재설정은 Task 4/5에서 같은 파일에 이어서 추가)

**Interfaces:**
- Consumes: Task 1의 `User` 컬럼, Task 2의 `send_verification_email_task`.
- Produces: `POST /auth/register`, `GET /auth/verify`, `POST /auth/resend-verification` — Task 6이 이 3개 엔드포인트에 레이트리밋을 추가.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_email_password_auth.py` (신규):

```python
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import User

client = TestClient(app, follow_redirects=False)


def _cleanup(*emails):
    db = SessionLocal()
    for email in emails:
        db.query(User).filter_by(email=email).delete()
    db.commit()
    db.close()


class TestRegister:
    def test_register_creates_unverified_user_and_returns_tokens(self):
        try:
            with patch("app.routers.auth.send_verification_email_task") as mock_task:
                r = client.post("/auth/register", json={
                    "email": "newuser1@x.com", "password": "password123",
                })
            assert r.status_code == 200
            body = r.json()
            assert "access_token" in body
            assert "refresh_token" in body

            db = SessionLocal()
            user = db.query(User).filter_by(email="newuser1@x.com").first()
            assert user is not None
            assert user.provider == "password"
            assert user.provider_id == "newuser1@x.com"
            assert user.email_verified is False
            assert user.password_hash is not None
            assert user.password_hash != "password123"
            assert user.verification_token is not None
            db.close()

            mock_task.delay.assert_called_once_with(user.id)
        finally:
            _cleanup("newuser1@x.com")

    def test_register_rejects_short_password(self):
        r = client.post("/auth/register", json={"email": "shortpw@x.com", "password": "abc"})
        assert r.status_code == 400

    def test_register_rejects_duplicate_email_same_provider(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "dup1@x.com", "password": "password123"})
                r = client.post("/auth/register", json={"email": "dup1@x.com", "password": "password456"})
            assert r.status_code == 400
        finally:
            _cleanup("dup1@x.com")

    def test_register_rejects_email_already_used_via_oauth(self):
        db = SessionLocal()
        db.add(User(id="oauth-dup-1", email="oauthdup@x.com", provider="google", provider_id="g-oauth-1"))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/register", json={"email": "oauthdup@x.com", "password": "password123"})
            assert r.status_code == 400
            assert "google" in r.json()["detail"].lower() or "Google" in r.json()["detail"]
        finally:
            _cleanup("oauthdup@x.com")


class TestVerify:
    def test_verify_valid_token_marks_verified_and_redirects_success(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "verifyme@x.com", "password": "password123"})
            db = SessionLocal()
            user = db.query(User).filter_by(email="verifyme@x.com").first()
            token = user.verification_token
            db.close()

            r = client.get("/auth/verify", params={"token": token})
            assert r.status_code in (302, 307)
            assert "verify=success" in r.headers["location"]

            db = SessionLocal()
            user = db.query(User).filter_by(email="verifyme@x.com").first()
            assert user.email_verified is True
            assert user.verification_token is None
            db.close()
        finally:
            _cleanup("verifyme@x.com")

    def test_verify_invalid_token_redirects_expired(self):
        r = client.get("/auth/verify", params={"token": "not-a-real-token"})
        assert r.status_code in (302, 307)
        assert "verify=expired" in r.headers["location"]

    def test_verify_expired_token_redirects_expired(self):
        from datetime import datetime, timedelta, timezone
        db = SessionLocal()
        db.add(User(
            id="expired-verify-1", email="expiredverify@x.com", provider="password",
            provider_id="expiredverify@x.com", password_hash="h", email_verified=False,
            verification_token="expired-tok-1",
            verification_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()
        db.close()
        try:
            r = client.get("/auth/verify", params={"token": "expired-tok-1"})
            assert r.status_code in (302, 307)
            assert "verify=expired" in r.headers["location"]
        finally:
            _cleanup("expiredverify@x.com")


class TestResendVerification:
    def test_resend_dispatches_new_token_for_unverified_user(self):
        try:
            with patch("app.routers.auth.send_verification_email_task") as mock_task:
                client.post("/auth/register", json={"email": "resend1@x.com", "password": "password123"})
                db = SessionLocal()
                old_token = db.query(User).filter_by(email="resend1@x.com").first().verification_token
                db.close()

                r = client.post("/auth/resend-verification", json={"email": "resend1@x.com"})
            assert r.status_code == 200

            db = SessionLocal()
            user = db.query(User).filter_by(email="resend1@x.com").first()
            assert user.verification_token is not None
            assert user.verification_token != old_token
            db.close()
            assert mock_task.delay.call_count == 2
        finally:
            _cleanup("resend1@x.com")

    def test_resend_returns_200_for_nonexistent_email(self):
        """계정 존재 여부를 유추할 수 없도록 항상 동일한 200을 반환한다."""
        r = client.post("/auth/resend-verification", json={"email": "doesnotexist@x.com"})
        assert r.status_code == 200

    def test_resend_returns_200_for_already_verified_user(self):
        db = SessionLocal()
        db.add(User(
            id="already-verified-1", email="alreadyverified@x.com", provider="password",
            provider_id="alreadyverified@x.com", password_hash="h", email_verified=True,
        ))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/resend-verification", json={"email": "alreadyverified@x.com"})
            assert r.status_code == 200
        finally:
            _cleanup("alreadyverified@x.com")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_password_auth.py -v`
Expected: FAIL — `404 Not Found` (엔드포인트 없음)

- [ ] **Step 3: app/routers/auth.py에 회원가입/인증/재발송 추가**

`app/routers/auth.py` 맨 위 import 블록(현재 1~13번째 줄)을 아래로 교체:

```python
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import httpx
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import create_access_token, create_refresh_token, decode_token
from app.database import get_db
from app.models import User
from app.tasks import send_verification_email_task
```

파일 맨 끝(`RefreshRequest`/`refresh_tokens` 다음)에 아래 코드를 추가:

```python
class RegisterRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    existing = db.query(User).filter_by(email=body.email).first()
    if existing:
        if existing.provider != "password":
            raise HTTPException(
                status_code=400,
                detail=f"이미 {existing.provider.capitalize()}로 가입된 이메일입니다. "
                       f"{existing.provider.capitalize()} 로그인을 사용하세요.",
            )
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    password_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    token = secrets.token_urlsafe(32)
    user = User(
        email=body.email,
        provider="password",
        provider_id=body.email,
        password_hash=password_hash,
        email_verified=False,
        verification_token=token,
        verification_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    send_verification_email_task.delay(user.id)

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(verification_token=token).first()
    if not user or not user.verification_token_expires_at:
        return RedirectResponse(f"{_FRONTEND}/login?verify=expired")

    expires_at = user.verification_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return RedirectResponse(f"{_FRONTEND}/login?verify=expired")

    user.email_verified = True
    user.verification_token = None
    user.verification_token_expires_at = None
    db.commit()
    return RedirectResponse(f"{_FRONTEND}/login?verify=success")


class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/resend-verification")
def resend_verification(body: ResendVerificationRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email, provider="password").first()
    if user and not user.email_verified:
        user.verification_token = secrets.token_urlsafe(32)
        user.verification_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        db.commit()
        send_verification_email_task.delay(user.id)
    return {"message": "인증 이메일이 발송되었으면 잠시 후 확인해주세요."}
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_password_auth.py -v`
Expected: 10개 전부 PASS

- [ ] **Step 5: 전체 백엔드 스위트 회귀 확인**

Run: `source .venv/bin/activate && pytest -q`
Expected: 이전 250 + 이번 태스크까지 추가된 테스트 전부 PASS, 실패 0

- [ ] **Step 6: Commit**

```bash
git add app/routers/auth.py tests/test_email_password_auth.py
git commit -m "feat: 이메일+비밀번호 회원가입/인증/재발송 API 추가"
```

---

### Task 4: 로그인 + `/auth/me` + `/convert` 이메일인증 게이트

**Files:**
- Modify: `app/routers/auth.py`
- Modify: `app/main.py:80-98` (`/convert` 핸들러)
- Test: `tests/test_email_password_auth.py` (이어서 추가)
- Test: `tests/test_api.py` (`/convert` 게이트 테스트 추가)

**Interfaces:**
- Consumes: Task 1의 `User.password_hash`/`User.email_verified`, `app/dependencies.py`의 기존 `get_current_user`.
- Produces: `POST /auth/login`, `GET /auth/me` — 프론트(Task 7)가 로그인 폼과 `fetchMe()`에서 사용.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_email_password_auth.py` 맨 끝에 추가:

```python
class TestLogin:
    def test_login_succeeds_with_correct_password(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "loginme@x.com", "password": "password123"})
            r = client.post("/auth/login", json={"email": "loginme@x.com", "password": "password123"})
            assert r.status_code == 200
            assert "access_token" in r.json()
        finally:
            _cleanup("loginme@x.com")

    def test_login_fails_with_wrong_password(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "wrongpw@x.com", "password": "password123"})
            r = client.post("/auth/login", json={"email": "wrongpw@x.com", "password": "wrongpassword"})
            assert r.status_code == 401
        finally:
            _cleanup("wrongpw@x.com")

    def test_login_fails_for_nonexistent_email(self):
        r = client.post("/auth/login", json={"email": "nosuchuser@x.com", "password": "password123"})
        assert r.status_code == 401

    def test_login_fails_for_oauth_only_account(self):
        """password_hash가 없는 OAuth 전용 계정은 자체가입 로그인으로 들어갈 수 없다."""
        db = SessionLocal()
        db.add(User(id="oauth-only-1", email="oauthonly@x.com", provider="google", provider_id="g-only-1"))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/login", json={"email": "oauthonly@x.com", "password": "anything123"})
            assert r.status_code == 401
        finally:
            _cleanup("oauthonly@x.com")


class TestMe:
    def test_me_returns_current_user_info(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                reg = client.post("/auth/register", json={"email": "meuser@x.com", "password": "password123"})
            token = reg.json()["access_token"]
            r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            body = r.json()
            assert body["email"] == "meuser@x.com"
            assert body["plan"] == "free"
            assert body["email_verified"] is False
        finally:
            _cleanup("meuser@x.com")

    def test_me_requires_auth(self):
        r = client.get("/auth/me")
        assert r.status_code in (401, 403)
```

`tests/test_api.py` 안에서 `/convert`를 테스트하는 클래스/함수 근처에 추가(파일 상단에 이미 있는 `patch("app.main.process_job_task.delay")` 컨벤션을 그대로 따른다):

```python
def test_convert_blocked_for_unverified_email_account():
    from app.auth import create_access_token
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    db.add(User(
        id="unverified-convert-1", email="unverifiedconvert@x.com", provider="password",
        provider_id="unverifiedconvert@x.com", password_hash="h", email_verified=False,
    ))
    db.commit()
    db.close()

    token = create_access_token("unverified-convert-1")
    try:
        with patch("app.main.process_job_task.delay"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 dummy", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 403
    finally:
        db = SessionLocal()
        db.query(User).filter_by(id="unverified-convert-1").delete()
        db.commit()
        db.close()


def test_convert_allowed_for_verified_email_account():
    from app.auth import create_access_token
    from app.database import SessionLocal
    from app.models import User

    db = SessionLocal()
    db.add(User(
        id="verified-convert-1", email="verifiedconvert@x.com", provider="password",
        provider_id="verifiedconvert@x.com", password_hash="h", email_verified=True,
    ))
    db.commit()
    db.close()

    token = create_access_token("verified-convert-1")
    try:
        with patch("app.main.process_job_task.delay"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 dummy", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200
    finally:
        db = SessionLocal()
        db.query(User).filter_by(id="verified-convert-1").delete()
        db.commit()
        db.close()
```

이 두 함수를 넣을 정확한 위치를 확인하려면 먼저 실행:

```bash
grep -n "^client = TestClient\|^def test_convert" tests/test_api.py | head -5
```

`client = TestClient(app)` 선언 바로 다음, 첫 `def test_convert...` 함수 앞에 위 두 함수를 붙여넣는다(같은 `client` 인스턴스를 재사용).

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_password_auth.py tests/test_api.py -v -k "Login or Me or unverified or verified_convert"`
Expected: FAIL — `/auth/login`/`/auth/me` 404, `/convert` 게이트 테스트는 통과해버림(아직 체크 없어서 항상 200) → `test_convert_blocked_for_unverified_email_account`가 403을 기대하는데 200이 와서 FAIL

- [ ] **Step 3: app/routers/auth.py에 로그인 + /me 추가**

`app/routers/auth.py` 맨 끝에 추가:

```python
class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email, provider="password").first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    if not bcrypt.checkpw(body.password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "plan": current_user.plan,
        "email_verified": current_user.email_verified,
    }
```

`app/routers/auth.py`의 import 블록에 `get_current_user` 추가 — Step 3에서 만든 import 블록 중 `from app.database import get_db` 다음 줄에 추가:

```python
from app.dependencies import get_current_user
```

- [ ] **Step 4: /convert에 이메일인증 게이트 추가**

`app/main.py:80-90`(`@app.post("/convert")` 함수 시그니처와 그 다음 플랜제한 체크) 중 아래 줄:

```python
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and current_user.plan == "free":
```

을 아래로 교체:

```python
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and not current_user.email_verified:
        raise HTTPException(status_code=403, detail="이메일 인증 후 이용 가능합니다.")

    if current_user and current_user.plan == "free":
```

- [ ] **Step 5: 테스트 실행해서 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_password_auth.py tests/test_api.py -v -k "Login or Me or unverified or verified_convert"`
Expected: 전부 PASS

- [ ] **Step 6: 전체 백엔드 스위트 회귀 확인**

Run: `source .venv/bin/activate && pytest -q`
Expected: 실패 0 (기존 OAuth 로그인 테스트, 익명 `/convert` 테스트 등 전부 그대로 통과 — `current_user`가 `None`인 익명 요청은 새 체크를 안 탐)

- [ ] **Step 7: Commit**

```bash
git add app/routers/auth.py app/main.py tests/test_email_password_auth.py tests/test_api.py
git commit -m "feat: 이메일+비밀번호 로그인/me API + /convert 미인증 계정 차단"
```

---

### Task 5: 비밀번호 재설정 API

**Files:**
- Modify: `app/routers/auth.py`
- Test: `tests/test_email_password_auth.py` (이어서 추가)

**Interfaces:**
- Consumes: Task 1의 `User.reset_token`, Task 2의 `send_reset_email_task`.
- Produces: `POST /auth/forgot-password`, `POST /auth/reset-password`.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_email_password_auth.py` 맨 끝에 추가:

```python
class TestForgotPassword:
    def test_forgot_password_dispatches_reset_email_for_password_account(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "forgot1@x.com", "password": "password123"})
            with patch("app.routers.auth.send_reset_email_task") as mock_task:
                r = client.post("/auth/forgot-password", json={"email": "forgot1@x.com"})
            assert r.status_code == 200

            db = SessionLocal()
            user = db.query(User).filter_by(email="forgot1@x.com").first()
            assert user.reset_token is not None
            db.close()
            mock_task.delay.assert_called_once_with(user.id)
        finally:
            _cleanup("forgot1@x.com")

    def test_forgot_password_returns_200_for_nonexistent_email(self):
        with patch("app.routers.auth.send_reset_email_task") as mock_task:
            r = client.post("/auth/forgot-password", json={"email": "noexist2@x.com"})
        assert r.status_code == 200
        mock_task.delay.assert_not_called()

    def test_forgot_password_returns_200_for_oauth_account_without_dispatching(self):
        """OAuth 전용 계정은 재설정할 비밀번호가 없으므로 메일 발송 안 하되 200은 동일하게."""
        db = SessionLocal()
        db.add(User(id="oauth-forgot-1", email="oauthforgot@x.com", provider="google", provider_id="g-f-1"))
        db.commit()
        db.close()
        try:
            with patch("app.routers.auth.send_reset_email_task") as mock_task:
                r = client.post("/auth/forgot-password", json={"email": "oauthforgot@x.com"})
            assert r.status_code == 200
            mock_task.delay.assert_not_called()
        finally:
            _cleanup("oauthforgot@x.com")


class TestResetPassword:
    def test_reset_password_with_valid_token_changes_password(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "reset1@x.com", "password": "oldpassword1"})
            with patch("app.routers.auth.send_reset_email_task"):
                client.post("/auth/forgot-password", json={"email": "reset1@x.com"})

            db = SessionLocal()
            token = db.query(User).filter_by(email="reset1@x.com").first().reset_token
            db.close()

            r = client.post("/auth/reset-password", json={"token": token, "new_password": "newpassword1"})
            assert r.status_code == 200

            login_old = client.post("/auth/login", json={"email": "reset1@x.com", "password": "oldpassword1"})
            assert login_old.status_code == 401
            login_new = client.post("/auth/login", json={"email": "reset1@x.com", "password": "newpassword1"})
            assert login_new.status_code == 200

            db = SessionLocal()
            user = db.query(User).filter_by(email="reset1@x.com").first()
            assert user.reset_token is None
            db.close()
        finally:
            _cleanup("reset1@x.com")

    def test_reset_password_with_invalid_token_fails(self):
        r = client.post("/auth/reset-password", json={"token": "no-such-token", "new_password": "newpassword1"})
        assert r.status_code == 400

    def test_reset_password_with_expired_token_fails(self):
        from datetime import datetime, timedelta, timezone
        db = SessionLocal()
        db.add(User(
            id="expired-reset-1", email="expiredreset@x.com", provider="password",
            provider_id="expiredreset@x.com", password_hash="h",
            reset_token="expired-reset-tok", reset_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/reset-password", json={"token": "expired-reset-tok", "new_password": "newpassword1"})
            assert r.status_code == 400
        finally:
            _cleanup("expiredreset@x.com")
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_password_auth.py -v -k "ForgotPassword or ResetPassword"`
Expected: FAIL — 404 (엔드포인트 없음)

- [ ] **Step 3: app/routers/auth.py에 비밀번호 재설정 API 추가**

`app/routers/auth.py`의 import 블록(Task 3에서 만든 `from app.tasks import send_verification_email_task`) 줄을 아래로 교체:

```python
from app.tasks import send_verification_email_task, send_reset_email_task
```

`app/routers/auth.py` 맨 끝에 추가:

```python
class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=body.email, provider="password").first()
    if user:
        user.reset_token = secrets.token_urlsafe(32)
        user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()
        send_reset_email_task.delay(user.id)
    return {"message": "메일이 발송되었으면 잠시 후 확인해주세요."}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db)):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    user = db.query(User).filter_by(reset_token=body.token).first()
    if not user or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")

    expires_at = user.reset_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")

    user.password_hash = bcrypt.hashpw(body.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user.reset_token = None
    user.reset_token_expires_at = None
    db.commit()
    return {"message": "비밀번호가 변경되었습니다."}
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_email_password_auth.py -v -k "ForgotPassword or ResetPassword"`
Expected: 6개 전부 PASS

- [ ] **Step 5: 전체 백엔드 스위트 회귀 확인**

Run: `source .venv/bin/activate && pytest -q`
Expected: 실패 0

- [ ] **Step 6: Commit**

```bash
git add app/routers/auth.py tests/test_email_password_auth.py
git commit -m "feat: 비밀번호 재설정(forgot/reset) API 추가"
```

---

### Task 6: 레이트리밋 (Redis 기반)

**Files:**
- Create: `app/rate_limit.py`
- Modify: `app/routers/auth.py`
- Test: `tests/test_rate_limit.py` (신규)

**Interfaces:**
- Consumes: Task 3의 `/auth/register`/`/auth/resend-verification`, Task 4의 `/auth/login`, Task 5의 `/auth/forgot-password`.
- Produces: `rate_limit(endpoint_name: str)` — FastAPI dependency 팩토리, 위 4개 엔드포인트에 적용.

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_rate_limit.py` (신규):

```python
from unittest.mock import MagicMock, patch

import redis
import pytest
from fastapi import HTTPException, Request


def _fake_request():
    req = MagicMock(spec=Request)
    req.client.host = "1.2.3.4"
    return req


def test_rate_limit_allows_under_threshold():
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 5
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        dep(_fake_request())  # 예외 없이 통과해야 함


def test_rate_limit_blocks_over_threshold():
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 21
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        with pytest.raises(HTTPException) as exc_info:
            dep(_fake_request())
        assert exc_info.value.status_code == 429


def test_rate_limit_sets_expiry_only_on_first_request():
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 1
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        dep(_fake_request())
    fake_redis.expire.assert_called_once()


def test_rate_limit_fails_open_when_redis_unavailable():
    """Redis 장애 시 요청을 막지 않는다(fail-open)."""
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.side_effect = redis.exceptions.ConnectionError("boom")
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        dep(_fake_request())  # 예외 없이 통과해야 함
```

- [ ] **Step 2: 테스트 실행해서 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_rate_limit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.rate_limit'`

- [ ] **Step 3: app/rate_limit.py 구현**

```python
import os

import redis
from fastapi import HTTPException, Request

RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW_SEC = 3600

_redis_client = redis.from_url(os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"))


def rate_limit(endpoint_name: str):
    """IP당 시간당 RATE_LIMIT_MAX회로 제한하는 FastAPI dependency를 만든다.

    Redis 장애 시에는 요청을 막지 않는다(fail-open) — 로그인/가입 자체가
    Redis 장애로 완전히 막히는 것을 방지하기 위한 의도된 동작이다.
    """
    def _dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{endpoint_name}:{ip}"
        try:
            count = _redis_client.incr(key)
            if count == 1:
                _redis_client.expire(key, RATE_LIMIT_WINDOW_SEC)
        except redis.exceptions.RedisError:
            return
        if count > RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429, detail="너무 많은 요청입니다. 잠시 후 다시 시도하세요."
            )
    return _dependency
```

- [ ] **Step 4: 테스트 실행해서 통과 확인**

Run: `source .venv/bin/activate && pytest tests/test_rate_limit.py -v`
Expected: 4개 전부 PASS

- [ ] **Step 5: 4개 엔드포인트에 레이트리밋 적용**

`app/routers/auth.py`에서 아래 4개 함수 시그니처를 각각 교체:

```python
@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db), _=Depends(rate_limit("register"))):
```

```python
@router.post("/resend-verification")
def resend_verification(body: ResendVerificationRequest, db: Session = Depends(get_db), _=Depends(rate_limit("resend-verification"))):
```

```python
@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db), _=Depends(rate_limit("login"))):
```

```python
@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db), _=Depends(rate_limit("forgot-password"))):
```

`app/routers/auth.py`의 import 블록에 추가:

```python
from app.rate_limit import rate_limit
```

- [ ] **Step 6: 전체 백엔드 스위트 회귀 확인**

Run: `source .venv/bin/activate && pytest -q`
Expected: 실패 0 — 로컬에 Redis가 안 떠 있어도 `rate_limit`이 fail-open이라 이 4개 엔드포인트를 호출하는 기존/신규 테스트가 전부 그대로 통과해야 한다(실제로 Redis 연결 안 된 상태에서 `pytest tests/test_email_password_auth.py`를 다시 돌려서 확인)

- [ ] **Step 7: Commit**

```bash
git add app/rate_limit.py app/routers/auth.py tests/test_rate_limit.py
git commit -m "feat: 회원가입/로그인/비번재설정 API에 Redis 기반 레이트리밋 추가"
```

---

### Task 7: 프론트엔드 (회원가입/로그인/비번재설정 UI)

**Files:**
- Modify: `frontend/src/components/Auth/LoginPage.tsx`
- Create: `frontend/src/components/Auth/RegisterPage.tsx`
- Create: `frontend/src/components/Auth/ForgotPasswordPage.tsx`
- Create: `frontend/src/components/Auth/ResetPasswordPage.tsx`
- Modify: `frontend/src/store/authStore.ts`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/RegisterPage.test.tsx` (신규)
- Test: `frontend/src/__tests__/LoginPage.test.tsx` (확장)

**Interfaces:**
- Consumes: 백엔드 `POST /auth/register`, `POST /auth/login`, `GET /auth/me`, `POST /auth/resend-verification`, `POST /auth/forgot-password`, `POST /auth/reset-password`(Task 3~5).
- Produces: `authStore`의 `emailVerified: boolean | null`, `plan: string | null`, `fetchMe(): Promise<void>` — `MainPage`(`App.tsx`)가 소비.

- [ ] **Step 1: authStore에 emailVerified/plan/fetchMe 추가**

`frontend/src/store/authStore.ts` 전체를 아래로 교체:

```typescript
import { create } from 'zustand'

interface AuthState {
  token: string | null
  emailVerified: boolean | null
  plan: string | null
  setToken: (access: string, refresh: string) => void
  logout: () => void
  fetchMe: () => Promise<void>
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: localStorage.getItem('access_token'),
  emailVerified: null,
  plan: null,
  setToken: (access, refresh) => {
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
    set({ token: access })
  },
  logout: () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    set({ token: null, emailVerified: null, plan: null })
  },
  fetchMe: async () => {
    const token = get().token
    if (!token) return
    const res = await fetch('/auth/me', { headers: { Authorization: `Bearer ${token}` } })
    if (!res.ok) return
    const data = await res.json()
    set({ emailVerified: data.email_verified, plan: data.plan })
  },
}))
```

- [ ] **Step 2: LoginPage.tsx에 이메일/비번 폼 + 링크 추가**

`frontend/src/components/Auth/LoginPage.tsx` 전체를 아래로 교체:

```typescript
import { useState } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

export default function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const { setToken, fetchMe } = useAuthStore()
  const [searchParams] = useSearchParams()
  const verifyStatus = searchParams.get('verify')

  const handleLogin = async () => {
    setError('')
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(body.detail || '로그인에 실패했습니다.')
      return
    }
    const data = await res.json()
    setToken(data.access_token, data.refresh_token)
    await fetchMe()
    navigate('/')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>GP Converter</h1>
      <p>PDF 악보를 Guitar Pro 파일로 변환하고 웹에서 편집하세요</p>

      {verifyStatus === 'success' && (
        <p style={{ color: 'green' }}>이메일 인증이 완료되었습니다. 로그인해주세요.</p>
      )}
      {verifyStatus === 'expired' && (
        <p style={{ color: 'red' }}>인증 링크가 유효하지 않거나 만료되었습니다.</p>
      )}

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

      <div style={{ marginTop: 32, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input type="password" placeholder="비밀번호" value={password} onChange={(e) => setPassword(e.target.value)} />
        {error && <p style={{ color: 'red', fontSize: 13 }}>{error}</p>}
        <button onClick={handleLogin} style={{ padding: '10px', cursor: 'pointer' }}>이메일로 로그인</button>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
          <Link to="/register">회원가입</Link>
          <Link to="/forgot-password">비밀번호를 잊으셨나요?</Link>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 3: RegisterPage.tsx 작성**

`frontend/src/components/Auth/RegisterPage.tsx` (신규):

```typescript
import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuthStore } from '../../store/authStore'

export default function RegisterPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [registered, setRegistered] = useState(false)
  const navigate = useNavigate()
  const { setToken, fetchMe } = useAuthStore()

  const handleRegister = async () => {
    setError('')
    if (password !== confirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(body.detail || '회원가입에 실패했습니다.')
      return
    }
    const data = await res.json()
    setToken(data.access_token, data.refresh_token)
    await fetchMe()
    setRegistered(true)
  }

  const handleResend = async () => {
    await fetch('/auth/resend-verification', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
  }

  if (registered) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
        <h1>가입 완료</h1>
        <p>인증 메일을 확인해주세요. 인증 전까지는 PDF 변환을 사용할 수 없습니다.</p>
        <button onClick={handleResend} style={{ marginTop: 16, cursor: 'pointer' }}>인증메일 다시 받기</button>
        <button onClick={() => navigate('/')} style={{ marginTop: 8, cursor: 'pointer' }}>앱으로 이동</button>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>회원가입</h1>
      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="email" placeholder="이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input type="password" placeholder="비밀번호 (8자 이상)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input type="password" placeholder="비밀번호 확인" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p style={{ color: 'red', fontSize: 13 }}>{error}</p>}
        <button onClick={handleRegister} style={{ padding: '10px', cursor: 'pointer' }}>가입하기</button>
        <Link to="/login" style={{ fontSize: 13 }}>이미 계정이 있으신가요? 로그인</Link>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: ForgotPasswordPage.tsx / ResetPasswordPage.tsx 작성**

`frontend/src/components/Auth/ForgotPasswordPage.tsx` (신규):

```typescript
import { useState } from 'react'
import { Link } from 'react-router-dom'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)

  const handleSubmit = async () => {
    await fetch('/auth/forgot-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email }),
    })
    setSent(true)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>비밀번호 찾기</h1>
      {sent ? (
        <p>메일이 발송되었으면 잠시 후 확인해주세요.</p>
      ) : (
        <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
          <input type="email" placeholder="가입한 이메일" value={email} onChange={(e) => setEmail(e.target.value)} />
          <button onClick={handleSubmit} style={{ padding: '10px', cursor: 'pointer' }}>재설정 링크 받기</button>
        </div>
      )}
      <Link to="/login" style={{ fontSize: 13, marginTop: 16 }}>로그인으로 돌아가기</Link>
    </div>
  )
}
```

`frontend/src/components/Auth/ResetPasswordPage.tsx` (신규):

```typescript
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const navigate = useNavigate()

  const handleSubmit = async () => {
    setError('')
    if (password !== confirm) {
      setError('비밀번호가 일치하지 않습니다.')
      return
    }
    const res = await fetch('/auth/reset-password', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: password }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(body.detail || '재설정에 실패했습니다.')
      return
    }
    navigate('/login')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', paddingTop: 80 }}>
      <h1>비밀번호 재설정</h1>
      <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 8, width: 280 }}>
        <input type="password" placeholder="새 비밀번호 (8자 이상)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input type="password" placeholder="새 비밀번호 확인" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p style={{ color: 'red', fontSize: 13 }}>{error}</p>}
        <button onClick={handleSubmit} style={{ padding: '10px', cursor: 'pointer' }}>비밀번호 변경</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: App.tsx에 라우트 3개 + 미인증 배너 추가**

`frontend/src/App.tsx` 전체를 아래로 교체:

```typescript
import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/authStore'
import { useEditorStore } from './store/editorStore'
import LoginPage from './components/Auth/LoginPage'
import RegisterPage from './components/Auth/RegisterPage'
import ForgotPasswordPage from './components/Auth/ForgotPasswordPage'
import ResetPasswordPage from './components/Auth/ResetPasswordPage'
import OAuthCallback from './components/Auth/OAuthCallback'
import ScoreViewer from './components/Editor/ScoreViewer'
import SharedScoreViewer from './components/Editor/SharedScoreViewer'
import UploadButton from './components/FileManager/UploadButton'
import FileList from './components/FileManager/FileList'
import BillingPanel from './components/Billing/BillingPanel'

function MainPage() {
  const [gp5Buffer, setGp5Buffer] = useState<ArrayBuffer | null>(null)
  const { token, emailVerified, logout, fetchMe } = useAuthStore()
  const { setFileId, clearHistory } = useEditorStore()

  useEffect(() => {
    if (token) fetchMe()
  }, [token])

  const handleComplete = (_jobId: string, buf: ArrayBuffer, fileId?: string | null) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId ?? null)
  }

  const handleFileSelect = (buf: ArrayBuffer, fileId: string) => {
    clearHistory()
    setGp5Buffer(buf)
    setFileId(fileId)
  }

  return (
    <div style={{ display: 'flex', height: '100vh' }}>
      {/* 사이드바 */}
      <aside style={{ width: 260, minWidth: 200, borderRight: '1px solid #ddd', padding: 16, overflowY: 'auto', flexShrink: 0 }}>
        <h2 style={{ marginTop: 0 }}>GP Converter</h2>
        {token && emailVerified === false && (
          <div style={{ background: '#fff3cd', padding: 8, fontSize: 12, marginBottom: 12 }}>
            이메일 인증이 필요합니다 — 메일함을 확인하세요.
          </div>
        )}
        <UploadButton onComplete={handleComplete} />
        <hr />
        <h3>내 파일</h3>
        {token ? (
          <FileList onSelect={handleFileSelect} />
        ) : (
          <p style={{ fontSize: 13, color: '#666' }}>로그인하면 파일이 저장됩니다</p>
        )}
        {token && (
          <button onClick={logout} style={{ marginTop: 16, fontSize: 12 }}>로그아웃</button>
        )}
        {token && <BillingPanel />}
      </aside>

      {/* 메인 편집 영역 */}
      <main style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
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
        <Route path="/register" element={<RegisterPage />} />
        <Route path="/forgot-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
        <Route path="/auth/callback" element={<OAuthCallback />} />
        <Route path="/" element={<MainPage />} />
        <Route path="/share/:token" element={<SharedScoreViewer />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
```

- [ ] **Step 6: 프론트 테스트 작성**

`frontend/src/__tests__/RegisterPage.test.tsx` (신규):

```typescript
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import RegisterPage from '../components/Auth/RegisterPage'

describe('RegisterPage', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
    localStorage.clear()
  })

  it('shows verification message after successful registration', async () => {
    (fetch as any).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ access_token: 'a', refresh_token: 'r' }),
    })

    render(<MemoryRouter><RegisterPage /></MemoryRouter>)

    fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 (8자 이상)'), { target: { value: 'password123' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 확인'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByText('가입하기'))

    await waitFor(() => {
      expect(screen.getByText('가입 완료')).toBeInTheDocument()
    })
  })

  it('shows error when passwords do not match', async () => {
    render(<MemoryRouter><RegisterPage /></MemoryRouter>)

    fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 (8자 이상)'), { target: { value: 'password123' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 확인'), { target: { value: 'different123' } })
    fireEvent.click(screen.getByText('가입하기'))

    await waitFor(() => {
      expect(screen.getByText('비밀번호가 일치하지 않습니다.')).toBeInTheDocument()
    })
    expect(fetch).not.toHaveBeenCalled()
  })

  it('shows server error message on failed registration', async () => {
    (fetch as any).mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '이미 가입된 이메일입니다.' }),
    })

    render(<MemoryRouter><RegisterPage /></MemoryRouter>)

    fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 (8자 이상)'), { target: { value: 'password123' } })
    fireEvent.change(screen.getByPlaceholderText('비밀번호 확인'), { target: { value: 'password123' } })
    fireEvent.click(screen.getByText('가입하기'))

    await waitFor(() => {
      expect(screen.getByText('이미 가입된 이메일입니다.')).toBeInTheDocument()
    })
  })
})
```

`frontend/src/__tests__/LoginPage.test.tsx`에 이미 있는 기존 테스트 파일의 import/렌더 패턴을 먼저 확인:

```bash
head -20 frontend/src/__tests__/LoginPage.test.tsx
```

그 패턴(라우터 래핑 방식, fetch 목킹 방식)을 그대로 따라 아래 테스트를 기존 파일 끝에 추가:

```typescript
it('logs in with email and password', async () => {
  (fetch as any).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ access_token: 'a', refresh_token: 'r' }),
  }).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ email: 'a@x.com', plan: 'free', email_verified: true }),
  })

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
  fireEvent.change(screen.getByPlaceholderText('비밀번호'), { target: { value: 'password123' } })
  fireEvent.click(screen.getByText('이메일로 로그인'))

  await waitFor(() => {
    expect(localStorage.getItem('access_token')).toBe('a')
  })
})

it('shows error on failed login', async () => {
  (fetch as any).mockResolvedValueOnce({
    ok: false,
    json: async () => ({ detail: '이메일 또는 비밀번호가 올바르지 않습니다.' }),
  })

  render(<MemoryRouter><LoginPage /></MemoryRouter>)
  fireEvent.change(screen.getByPlaceholderText('이메일'), { target: { value: 'a@x.com' } })
  fireEvent.change(screen.getByPlaceholderText('비밀번호'), { target: { value: 'wrong' } })
  fireEvent.click(screen.getByText('이메일로 로그인'))

  await waitFor(() => {
    expect(screen.getByText('이메일 또는 비밀번호가 올바르지 않습니다.')).toBeInTheDocument()
  })
})
```

(필요한 `render`/`screen`/`fireEvent`/`waitFor`/`MemoryRouter`/`vi` import는 기존 파일 상단에 이미 있으면 그대로 두고, 없는 것만 추가한다 — Step 6 시작 시 `head -20`으로 확인한 실제 import 목록 기준으로 판단한다.)

- [ ] **Step 7: 프론트 테스트 실행**

Run: `cd frontend && npx vitest run`
Expected: 기존 147 + 이번에 추가된 테스트 전부 PASS, 실패 0

- [ ] **Step 8: Commit**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
git add frontend/src/store/authStore.ts frontend/src/components/Auth/LoginPage.tsx \
        frontend/src/components/Auth/RegisterPage.tsx frontend/src/components/Auth/ForgotPasswordPage.tsx \
        frontend/src/components/Auth/ResetPasswordPage.tsx frontend/src/App.tsx \
        frontend/src/__tests__/RegisterPage.test.tsx frontend/src/__tests__/LoginPage.test.tsx
git commit -m "feat: 회원가입/로그인/비번재설정 프론트엔드 UI 추가"
```

---

### Task 8: README 문서화

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 2의 `SMTP_*` 환경변수.
- Produces: 없음(최종 태스크).

- [ ] **Step 1: 환경변수 표에 SMTP 관련 행 추가**

`README.md`의 `## 환경변수` 표(`GITHUB_CLIENT_SECRET` 행 다음, `GUITAR_OMR_DIR` 행 앞)에 추가:

```bash
grep -n "GITHUB_CLIENT_SECRET\|GUITAR_OMR_DIR" README.md
```

위 grep 결과로 정확한 줄을 확인한 뒤, `GITHUB_CLIENT_SECRET` 행 바로 다음 줄에 삽입:

```markdown
| `SMTP_HOST` | 없음(선택) | 이메일 인증/비번재설정 발송용 SMTP 서버. 미설정 시 발송 스킵(로그만 남김) — dev/test 환경 대비 |
| `SMTP_PORT` | `587` | SMTP 포트 |
| `SMTP_USERNAME` | 없음 | SMTP 인증 계정(Gmail이면 앱 비밀번호 발급 필요) |
| `SMTP_PASSWORD` | 없음 | SMTP 인증 비밀번호 |
| `SMTP_FROM_EMAIL` | `SMTP_USERNAME`과 동일 | 발신자 이메일 주소 |
| `SMTP_USE_TLS` | `true` | STARTTLS 사용 여부 |
```

- [ ] **Step 2: "로컬에서 실행하기" 섹션에 자체가입 관련 안내 한 줄 추가**

```bash
grep -n "^## 로컬에서 실행하기\|^## 환경변수" README.md
```

`## 로컬에서 실행하기` 섹션과 `## 환경변수` 섹션 사이(가장 마지막 하위섹션 다음)에 아래 문단 추가:

```markdown

**이메일+비밀번호로 자체 가입도 가능**하다(Google/GitHub 계정 없이). `SMTP_*` 환경변수를 안 채워도 가입/로그인 자체는 되지만, 인증메일이 실제로 발송되지 않으므로(로그에만 남음) `/convert`가 계속 403으로 막힌다 — 로컬 개발 중엔 서버 로그에서 인증 링크(`.../auth/verify?token=...`)를 직접 찾아 브라우저로 열면 된다.
```

- [ ] **Step 3: README 렌더링 확인**

```bash
grep -n "^## " README.md
```

Expected: 기존 헤더 순서 그대로 유지, 새 문단만 텍스트로 삽입되고 헤더 개수는 안 늘어남

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: 이메일+비밀번호 자체가입 환경변수(SMTP_*) 문서화"
```
