# Stripe 결제 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Free(월 3회 변환/저장 5개)/Pro($4.99/월 무제한) 요금제를 도입하고 Stripe Checkout+Customer Portal로 결제·구독관리를 연동한다.

**Architecture:** Stripe Checkout 호스티드 페이지로 결제, Customer Portal로 해지/카드관리 위임 — 자체 결제 UI 없음. 웹훅으로 `User.plan`을 동기화. 사용량은 별도 카운터 테이블 없이 `File` 행을 그때그때 쿼리해서 계산.

**Tech Stack:** FastAPI, SQLAlchemy 2.0(SQLite), `stripe` Python SDK, pytest / React 18, TypeScript, vitest

## Global Constraints

- Free: 월 3회 **성공한** 변환(실패/재시도는 카운트 안 함), 저장 5개(시간 무관, 삭제하면 슬롯 회수)
- 변환 카운트 리셋: 가입일 기준이 아니라 매 요청마다 "최근 30일 내 성공 변환 수"를 계산(롤링), 별도 리셋 배치 없음
- Pro: $4.99/월, 무제한
- 결제 UI: Stripe Checkout 호스티드 페이지로 리다이렉트(임베디드 폼 금지)
- 구독 해지/카드변경: Stripe Customer Portal로 리다이렉트(자체 UI 금지)
- DB 스키마 변경은 SQLite `ALTER TABLE ADD COLUMN` + `CREATE UNIQUE INDEX IF NOT EXISTS`를 **컬럼 존재 여부와 무관하게 매번 무조건 실행**(과거 공유링크 기능에서 인덱스 생성이 컬럼-존재 체크 안에 갇혀 부분마이그레이션을 못 잡는 버그를 겪었음 — 처음부터 무조건 실행 형태로 작성)
- Stripe 관련 환경변수(`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID_PRO`)는 계정이 아직 없으므로 테스트에서 전부 더미값 + `stripe` SDK mock으로 처리, 실제 API 호출 없음
- 신규 프론트 컴포넌트는 기존 코드베이스처럼 최소 인라인 스타일만 사용 — 디자인 폴리싱 금지
- 스펙 문서: `docs/superpowers/specs/2026-07-02-stripe-billing-design.md`
- **`/convert` 402 응답 시 프론트 에러 표시는 별도 태스크 없음**: `frontend/src/components/FileManager/UploadButton.tsx`의 `api.upload()` 호출부가 이미 `catch (e: any) { setError(e.message) }`로 백엔드 `detail` 메시지를 그대로 화면에 띄우는 기존 경로가 있다. Task 5가 402 응답에 한국어 안내 문구를 `detail`로 담아 보내는 것만으로 이 요구사항이 자동으로 충족된다 — `UploadButton.tsx`는 수정하지 않는다.

---

### Task 1: 변환 성공 시 File.gp5_path 갱신 (사전조건 버그 수정)

**Files:**
- Modify: `app/worker.py`
- Modify: `app/main.py:127-132`
- Test: `tests/test_worker.py`

**Interfaces:**
- Produces: `process_job(store, job_id, pdf_path, audiveris_cmd, tuxguitar_cmd, timeout, file_id: Optional[str] = None) -> None` — `file_id` 파라미터는 하위호환을 위해 키워드 전용 기본값 `None`. Task 5의 `/convert` 사용량 카운트가 이 함수가 성공 시 `File.gp5_path`를 실제 경로로 채워준다는 것에 의존함

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_worker.py` 끝에 추가:

```python
def test_process_job_success_updates_file_gp5_path(tmp_path):
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    db.merge(User(id="w-u1", email="w1@x.com", provider="google", provider_id="w-u1"))
    db.merge(File(id="w-f1", user_id="w-u1", name="test", gp5_path=""))
    db.commit()
    db.close()

    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t",
                     timeout=10, file_id="w-f1")

    db = SessionLocal()
    updated = db.query(File).filter_by(id="w-f1").first()
    assert updated.gp5_path == "/x/output.gp5"
    db.close()


def test_process_job_failure_does_not_touch_file(tmp_path):
    from app.database import SessionLocal
    from app.models import User, File
    from app.pipeline.audiveris import AudiverisError

    db = SessionLocal()
    db.merge(User(id="w-u2", email="w2@x.com", provider="google", provider_id="w-u2"))
    db.merge(File(id="w-f2", user_id="w-u2", name="test", gp5_path=""))
    db.commit()
    db.close()

    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", side_effect=AudiverisError("실패")):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t",
                     timeout=10, file_id="w-f2")

    db = SessionLocal()
    untouched = db.query(File).filter_by(id="w-f2").first()
    assert untouched.gp5_path == ""
    db.close()


def test_process_job_without_file_id_still_works(tmp_path):
    """기존 호출 시그니처(익명 유저, file_id 없음) 하위호환."""
    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.DONE
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_worker.py -v`
Expected: `test_process_job_success_updates_file_gp5_path`와 `test_process_job_failure_does_not_touch_file`가 `TypeError: process_job() got an unexpected keyword argument 'file_id'`로 실패. `test_process_job_without_file_id_still_works`는 기존 코드로도 통과함(이건 회귀 방지용이라 지금부터 통과해도 정상)

- [ ] **Step 3: process_job에 file_id 파라미터 + DB 갱신 추가**

`app/worker.py` 전체를 아래로 교체:

```python
from typing import Optional

from app.jobs import JobStore, JobStatus
from app.pipeline.orchestrator import run_conversion


def process_job(store: JobStore, job_id: str, pdf_path: str,
                audiveris_cmd: str, tuxguitar_cmd: str, timeout: int,
                file_id: Optional[str] = None) -> None:
    job = store.get(job_id)
    if job is None:
        return
    store.update(job_id, status=JobStatus.RUNNING, progress_pct=5)

    def _progress(pct: int, step: str):
        store.update(job_id, progress_pct=pct, message=step)

    try:
        gp5_path = run_conversion(
            pdf_path, job.workdir,
            audiveris_cmd=audiveris_cmd, tuxguitar_cmd=tuxguitar_cmd, timeout=timeout,
            progress_callback=_progress,
        )
        store.update(job_id, status=JobStatus.DONE, result_path=gp5_path, progress_pct=100)
        if file_id:
            _update_file_gp5_path(file_id, gp5_path)
    except Exception as e:
        store.update(job_id, status=JobStatus.FAILED, message=str(e))


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

- [ ] **Step 4: main.py에서 file_id 전달**

`app/main.py:127-132`의 아래 블록:

```python
    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
    )
```

을 아래로 교체:

```python
    background_tasks.add_task(
        process_job, store, job.id, pdf_path,
        audiveris_cmd=settings.audiveris_cmd,
        tuxguitar_cmd=settings.tuxguitar_cmd,
        timeout=settings.step_timeout_sec,
        file_id=file_id,
    )
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_worker.py -v`
Expected: 5 passed (기존 2개 + 신규 3개)

- [ ] **Step 6: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 전부 통과, 신규 실패 없음

- [ ] **Step 7: 커밋**

```bash
git add app/worker.py app/main.py tests/test_worker.py
git commit -m "fix: 변환 성공 시 File.gp5_path 실제 경로로 갱신 (결제 사용량 카운트 사전조건)"
```

---

### Task 2: User.stripe_customer_id 컬럼 + 마이그레이션 가드 확장

**Files:**
- Modify: `app/models.py`
- Modify: `app/database.py`
- Test: `tests/test_database_migration.py`

**Interfaces:**
- Produces: `User.stripe_customer_id: str | None` — Task 3의 checkout/portal, Task 4의 웹훅이 이 컬럼으로 유저를 조회/갱신함

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_database_migration.py` 끝에 추가:

```python
def test_migration_adds_stripe_customer_id_column(tmp_path):
    """구버전 users 테이블(신규 컬럼 없음)에 stripe_customer_id를 추가한다."""
    db_path = tmp_path / "old_users.db"
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
    assert "stripe_customer_id" in cols


def test_migration_creates_unique_index_on_stripe_customer_id(tmp_path):
    """마이그레이션 후 stripe_customer_id에 unique index가 생성되어야 한다."""
    db_path = tmp_path / "old_users2.db"
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
            "INSERT INTO users (id, email, provider, provider_id, stripe_customer_id) "
            "VALUES ('u1', 'a@x.com', 'google', 'u1', 'cus_123')"
        ))
        conn.commit()

    with engine.connect() as conn:
        try:
            conn.execute(sa.text(
                "INSERT INTO users (id, email, provider, provider_id, stripe_customer_id) "
                "VALUES ('u2', 'b@x.com', 'google', 'u2', 'cus_123')"
            ))
            conn.commit()
            raise AssertionError("중복 stripe_customer_id insert가 실패해야 하는데 성공함")
        except sa.exc.IntegrityError:
            pass


def test_migration_users_table_missing_is_noop(tmp_path):
    """users 테이블이 없는 DB(예: files만 있는 구버전 테스트 DB)에서도 에러 없이 통과해야 한다.

    이 테스트는 회귀 방지용이다: run_sqlite_migrations가 users 테이블을
    무조건 건드리게 만들면, files만 있는 기존 테스트 DB들(위의 다른 테스트들)이
    전부 'no such table: users'로 깨진다 — 각 테이블 블록은 반드시
    존재 여부를 먼저 확인해야 한다.
    """
    db_path = tmp_path / "files_only.db"
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        conn.execute(sa.text(
            "CREATE TABLE files (id VARCHAR PRIMARY KEY, shared_token VARCHAR)"
        ))
        conn.commit()

    run_sqlite_migrations(engine)  # users 테이블 없어도 에러 없이 통과해야 함
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_database_migration.py -v`
Expected: `test_migration_adds_stripe_customer_id_column`와 `test_migration_creates_unique_index_on_stripe_customer_id`가 `stripe_customer_id` 컬럼 없음으로 실패(assert 실패 또는 `OperationalError: no such column`). `test_migration_users_table_missing_is_noop`은 현재 코드로도 통과함(아직 users 블록이 없으므로) — 이건 Step 3 이후에도 계속 통과해야 하는 회귀 방지 테스트

- [ ] **Step 3: User 모델에 컬럼 추가**

`app/models.py` — `User` 클래스에 라인 추가(기존 `plan` 다음 줄):

```python
class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String, unique=True, nullable=False)
    provider = Column(String, nullable=False)
    provider_id = Column(String, nullable=False)
    plan = Column(String, nullable=False, default="free")
    stripe_customer_id = Column(String, unique=True, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: 마이그레이션 가드에 users 테이블 블록 추가 (테이블 존재 여부 가드 포함)**

`app/database.py`의 `run_sqlite_migrations` 함수 전체를 아래로 교체:

```python
def run_sqlite_migrations(engine) -> None:
    """create_all()이 커버하지 못하는 기존 테이블 컬럼 추가.

    Alembic 없이 운영하는 프로젝트라, 기존 테이블에 새 컬럼이 생길 때마다
    여기에 (컬럼명, DDL타입) 쌍을 추가한다. 기존 행 데이터는 보존된다.
    각 테이블 블록은 해당 테이블이 실제 존재할 때만 실행한다 — 그렇지 않으면
    특정 테이블만 있는 상태로 이 함수를 호출하는 테스트/부분 DB에서 에러가 난다.
    """
    if engine.dialect.name != "sqlite":
        return

    with engine.connect() as conn:
        tables = {row[0] for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )}

        if "files" in tables:
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(files)"))}
            if "shared_token" not in cols:
                conn.execute(text("ALTER TABLE files ADD COLUMN shared_token VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_files_shared_token ON files (shared_token)"
            ))
            if "shared_expires_at" not in cols:
                conn.execute(text("ALTER TABLE files ADD COLUMN shared_expires_at DATETIME"))

        if "users" in tables:
            user_cols = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
            if "stripe_customer_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR"))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_stripe_customer_id "
                "ON users (stripe_customer_id)"
            ))

        conn.commit()
```

- [ ] **Step 5: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_database_migration.py -v`
Expected: 8 passed (기존 5개 + 신규 3개)

- [ ] **Step 6: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 전부 통과 (`files`만 있던 기존 5개 마이그레이션 테스트가 `users` 블록 추가로 깨지지 않는지가 핵심 확인 포인트)

- [ ] **Step 7: 커밋**

```bash
git add app/models.py app/database.py tests/test_database_migration.py
git commit -m "feat: User 모델에 stripe_customer_id 컬럼 추가 + 마이그레이션 가드 확장"
```

---

### Task 3: billing 라우터 스캐폴딩 + Checkout/Portal 엔드포인트

**Files:**
- Create: `app/routers/billing.py`
- Modify: `app/main.py` (라우터 등록)
- Modify: `requirements.txt`
- Modify: `tests/conftest.py`
- Test: `tests/test_billing.py` (신규)

**Interfaces:**
- Consumes: `User.stripe_customer_id` (Task 2)
- Produces: `POST /billing/checkout`, `POST /billing/portal` — Task 4(웹훅), Task 5(사용량)가 같은 `app/routers/billing.py` 파일에 이어서 작성함. 응답 스키마 둘 다 `{"url": str}`

- [ ] **Step 1: requirements.txt에 stripe 추가**

`requirements.txt` 끝에 추가:

```
stripe>=10.0.0
```

Run: `pip install stripe>=10.0.0` (또는 프로젝트가 쓰는 파이썬 환경에 설치 — 이 저장소는 `python -m pytest`를 anaconda 기본 python으로 돌린다는 걸 확인했음)

- [ ] **Step 2: conftest.py에 Stripe 환경변수 기본값 추가**

`tests/conftest.py` 끝에 추가:

```python
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("STRIPE_PRICE_ID_PRO", "price_dummy")
```

- [ ] **Step 3: 실패 테스트 작성**

`tests/test_billing.py` (신규):

```python
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user(db, uid="u1", plan="free", stripe_customer_id=None):
    from app.models import User
    user = User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid,
                plan=plan, stripe_customer_id=stripe_customer_id)
    db.merge(user)
    db.commit()
    return user


class TestCreateCheckoutSession:
    def test_200_creates_customer_and_session(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u1")
        db.close()

        fake_customer = MagicMock(id="cus_abc")
        fake_session = MagicMock(url="https://checkout.stripe.com/session/xyz")
        with patch("stripe.Customer.create", return_value=fake_customer) as mock_customer, \
             patch("stripe.checkout.Session.create", return_value=fake_session) as mock_session:
            resp = client.post("/billing/checkout",
                                headers={"Authorization": f"Bearer {_tok('b-u1')}"})

        assert resp.status_code == 200
        assert resp.json() == {"url": "https://checkout.stripe.com/session/xyz"}
        mock_customer.assert_called_once()
        mock_session.assert_called_once()

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="b-u1").first()
        assert u.stripe_customer_id == "cus_abc"
        db.close()

    def test_reuses_existing_stripe_customer_id(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u2", stripe_customer_id="cus_existing")
        db.close()

        fake_session = MagicMock(url="https://checkout.stripe.com/session/abc")
        with patch("stripe.Customer.create") as mock_customer, \
             patch("stripe.checkout.Session.create", return_value=fake_session) as mock_session:
            resp = client.post("/billing/checkout",
                                headers={"Authorization": f"Bearer {_tok('b-u2')}"})

        assert resp.status_code == 200
        mock_customer.assert_not_called()
        mock_session.assert_called_once()
        assert mock_session.call_args.kwargs["customer"] == "cus_existing"


class TestCreatePortalSession:
    def test_200_with_existing_customer(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u3", stripe_customer_id="cus_p1")
        db.close()

        fake_session = MagicMock(url="https://billing.stripe.com/session/p1")
        with patch("stripe.billing_portal.Session.create", return_value=fake_session) as mock_portal:
            resp = client.post("/billing/portal",
                                headers={"Authorization": f"Bearer {_tok('b-u3')}"})

        assert resp.status_code == 200
        assert resp.json() == {"url": "https://billing.stripe.com/session/p1"}
        mock_portal.assert_called_once()

    def test_400_without_stripe_customer(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u4")
        db.close()

        resp = client.post("/billing/portal",
                            headers={"Authorization": f"Bearer {_tok('b-u4')}"})
        assert resp.status_code == 400
```

- [ ] **Step 4: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_billing.py -v`
Expected: 전부 404 (라우터 자체가 아직 없어서 `/billing/checkout`, `/billing/portal` 미매칭)

- [ ] **Step 5: billing.py 구현**

`app/routers/billing.py` (신규):

```python
import os

import stripe
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User

router = APIRouter(prefix="/billing", tags=["billing"])

try:
    _STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
    _STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
    _STRIPE_PRICE_ID_PRO = os.environ["STRIPE_PRICE_ID_PRO"]
except KeyError as e:
    raise ValueError(
        f"필수 환경변수 누락: {e}. .env 파일 또는 환경변수를 설정하세요."
    ) from e

stripe.api_key = _STRIPE_SECRET_KEY

_FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:5173")


@router.post("/checkout")
def create_checkout_session(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pro 구독 결제용 Stripe Checkout 세션 생성."""
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": _STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=f"{_FRONTEND}/?billing=success",
        cancel_url=f"{_FRONTEND}/?billing=cancel",
    )
    return {"url": session.url}


@router.post("/portal")
def create_portal_session(
    user: User = Depends(get_current_user),
):
    """구독 해지/카드변경용 Stripe Customer Portal 세션 생성."""
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="구독 정보가 없습니다")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{_FRONTEND}/",
    )
    return {"url": session.url}
```

- [ ] **Step 6: main.py에 라우터 등록**

`app/main.py` — 다른 라우터 import 옆에 추가:

```python
from app.routers.billing import router as billing_router
```

`app.include_router(share_router)` 다음 줄에 추가:

```python
app.include_router(billing_router)
```

- [ ] **Step 7: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_billing.py -v`
Expected: 4 passed

- [ ] **Step 8: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 전부 통과. `app/routers/billing.py`가 module import 시점에 `STRIPE_SECRET_KEY` 등을 요구하므로, conftest.py의 더미값 설정이 안 되어 있으면 **모든** 테스트가 import 에러로 깨진다 — 만약 그런 실패가 보이면 Step 2가 제대로 적용됐는지 다시 확인

- [ ] **Step 9: 커밋**

```bash
git add app/routers/billing.py app/main.py requirements.txt tests/conftest.py tests/test_billing.py
git commit -m "feat: Stripe Checkout/Customer Portal 세션 생성 API"
```

---

### Task 4: Stripe 웹훅 엔드포인트

**Files:**
- Modify: `app/routers/billing.py` (Task 3에서 생성한 파일에 이어서 작성)
- Test: `tests/test_billing.py` (Task 3에서 생성한 파일에 이어서 작성)

**Interfaces:**
- Consumes: `User.stripe_customer_id` (Task 2), 라우터는 이미 `app.main`에 등록됨(Task 3)
- Produces: `POST /billing/webhook` — Stripe 대시보드에 등록할 엔드포인트. 이후 태스크 없음(웹훅은 Stripe가 호출하는 쪽이라 프론트가 직접 부르지 않음)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_billing.py` 맨 위 import에 추가:

```python
import stripe
```

파일 끝에 추가:

```python
class TestStripeWebhook:
    def test_400_invalid_signature(self):
        with patch("stripe.Webhook.construct_event",
                   side_effect=stripe.error.SignatureVerificationError("bad sig", "sig_header")):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "bad"})
        assert resp.status_code == 400

    def test_checkout_session_completed_sets_plan_pro(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u1", plan="free", stripe_customer_id="cus_w1")
        db.close()

        fake_event = {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_w1"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u1").first()
        assert u.plan == "pro"
        db.close()

    def test_subscription_updated_active_sets_pro(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u2", plan="free", stripe_customer_id="cus_w2")
        db.close()

        fake_event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_w2", "status": "active"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u2").first()
        assert u.plan == "pro"
        db.close()

    def test_subscription_updated_canceled_sets_free(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u3", plan="pro", stripe_customer_id="cus_w3")
        db.close()

        fake_event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_w3", "status": "canceled"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u3").first()
        assert u.plan == "free"
        db.close()

    def test_subscription_deleted_sets_free(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u4", plan="pro", stripe_customer_id="cus_w4")
        db.close()

        fake_event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_w4"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u4").first()
        assert u.plan == "free"
        db.close()

    def test_unknown_customer_id_does_not_crash(self):
        fake_event = {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_unknown"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200  # 유저 못 찾아도 200 (Stripe 재전송 방지)
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_billing.py::TestStripeWebhook -v`
Expected: 전부 404 (`/billing/webhook` 라우트가 아직 없음)

- [ ] **Step 3: 웹훅 엔드포인트 구현**

`app/routers/billing.py` 파일 맨 위 import에 추가:

```python
from fastapi import Request
```

파일 끝에 추가:

```python
@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe 웹훅 수신 — 인증 대신 서명 검증."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, _STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="잘못된 웹훅 서명")

    event_type = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")

    if customer_id:
        user = db.query(User).filter_by(stripe_customer_id=customer_id).first()
        if user:
            if event_type == "checkout.session.completed":
                user.plan = "pro"
            elif event_type == "customer.subscription.updated":
                user.plan = "pro" if obj.get("status") in ("active", "trialing") else "free"
            elif event_type == "customer.subscription.deleted":
                user.plan = "free"
            db.commit()

    return {"ok": True}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_billing.py -v`
Expected: 10 passed (Task 3의 4개 + 이번 6개)

- [ ] **Step 5: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 전부 통과

- [ ] **Step 6: 커밋**

```bash
git add app/routers/billing.py tests/test_billing.py
git commit -m "feat: Stripe 웹훅으로 구독 상태 → User.plan 동기화"
```

---

### Task 5: 사용량 조회 API + /convert 제한 적용

**Files:**
- Modify: `app/routers/billing.py` (Task 3/4에서 만든 파일에 이어서 작성)
- Modify: `app/main.py` (`/convert`에 제한 체크 추가)
- Test: `tests/test_billing.py` (사용량 조회 테스트 추가)
- Test: `tests/test_api.py` (`/convert` 제한 테스트 추가)

**Interfaces:**
- Consumes: `File` 모델 (`user_id`, `gp5_path`, `created_at`) — Task 1에서 고친 "성공 시 gp5_path 실제 경로로 채워짐" 동작에 의존
- Produces: `count_usage(db: Session, user_id: str) -> tuple[int, int]` (반환: `(conversions_used, files_used)`), `FREE_CONVERSIONS_LIMIT = 3`, `FREE_FILES_LIMIT = 5` — `app/main.py`의 `/convert`가 이 함수와 상수를 그대로 가져다 씀. `GET /billing/usage` 응답 스키마 `{"plan": str, "conversions_used": int, "conversions_limit": int, "files_used": int, "files_limit": int}` — Task 6 프론트 `UsageInfo` 타입이 이 형태를 그대로 따름

- [ ] **Step 1: 사용량 조회 실패 테스트 작성**

`tests/test_billing.py` 끝에 추가:

```python
class TestUsage:
    def test_free_user_usage_counts(self, tmp_path):
        from app.database import SessionLocal
        from app.models import File
        db = SessionLocal()
        _setup_user(db, uid="u-u1", plan="free")
        for i in range(2):
            db.merge(File(id=f"u-f{i}", user_id="u-u1", name="s",
                           gp5_path=str(tmp_path / f"{i}.gp5")))
        db.merge(File(id="u-f-pending", user_id="u-u1", name="s", gp5_path=""))
        db.commit()
        db.close()

        resp = client.get("/billing/usage",
                           headers={"Authorization": f"Bearer {_tok('u-u1')}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "free"
        assert body["conversions_used"] == 2
        assert body["conversions_limit"] == 3
        assert body["files_used"] == 3
        assert body["files_limit"] == 5

    def test_old_conversions_excluded_from_30day_window(self):
        from datetime import datetime, timedelta
        from app.database import SessionLocal
        from app.models import File
        db = SessionLocal()
        _setup_user(db, uid="u-u2", plan="free")
        old_file = File(id="u-f-old", user_id="u-u2", name="s", gp5_path="/x/old.gp5")
        old_file.created_at = datetime.utcnow() - timedelta(days=31)
        db.merge(old_file)
        db.commit()
        db.close()

        resp = client.get("/billing/usage",
                           headers={"Authorization": f"Bearer {_tok('u-u2')}"})
        body = resp.json()
        assert body["conversions_used"] == 0  # 30일 밖이라 카운트 제외
        assert body["files_used"] == 1  # 저장 카운트는 시간 무관

    def test_pro_user_plan_reported(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="u-u3", plan="pro")
        db.close()

        resp = client.get("/billing/usage",
                           headers={"Authorization": f"Bearer {_tok('u-u3')}"})
        assert resp.json()["plan"] == "pro"
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_billing.py::TestUsage -v`
Expected: 전부 404 (`/billing/usage` 라우트가 아직 없음)

- [ ] **Step 3: count_usage 함수 + GET /usage 엔드포인트 구현**

`app/routers/billing.py` 파일 맨 위 import에 추가:

```python
from datetime import datetime, timedelta

from app.models import File
```

`_FRONTEND = os.getenv(...)` 줄 다음에 추가:

```python
FREE_CONVERSIONS_LIMIT = 3
FREE_FILES_LIMIT = 5


def count_usage(db: Session, user_id: str) -> tuple[int, int]:
    """(최근 30일 성공 변환 수, 저장된 파일 총개수) 반환.

    30일 컷오프는 timezone-naive UTC로 계산한다 — File.created_at이
    SQLite server_default(func.now())로 채워질 때 naive datetime 문자열로
    저장되므로, 비교 대상도 naive로 맞춰야 문자열 비교가 정확하다
    (aware datetime을 쓰면 오프셋 접미사 유무가 달라져서 문자열 비교가 깨짐).
    """
    cutoff = datetime.utcnow() - timedelta(days=30)
    conversions_used = (
        db.query(File)
        .filter(File.user_id == user_id, File.gp5_path != "", File.created_at >= cutoff)
        .count()
    )
    files_used = db.query(File).filter(File.user_id == user_id).count()
    return conversions_used, files_used
```

파일 끝에 추가:

```python
@router.get("/usage")
def get_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 플랜 + 사용량 조회."""
    conversions_used, files_used = count_usage(db, user.id)
    return {
        "plan": user.plan,
        "conversions_used": conversions_used,
        "conversions_limit": FREE_CONVERSIONS_LIMIT,
        "files_used": files_used,
        "files_limit": FREE_FILES_LIMIT,
    }
```

- [ ] **Step 4: 사용량 조회 테스트 통과 확인**

Run: `python -m pytest tests/test_billing.py -v`
Expected: 13 passed (Task 3/4의 10개 + 이번 3개)

- [ ] **Step 5: /convert 제한 실패 테스트 작성**

`tests/test_api.py` 파일 끝에 추가:

```python
class TestConvertUsageLimits:
    def test_free_user_blocked_after_3_successful_conversions(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u1", email="cv1@x.com", provider="google",
                       provider_id="cv-u1", plan="free"))
        for i in range(3):
            db.merge(File(id=f"cv-f{i}", user_id="cv-u1", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u1")
        r = client.post(
            "/convert",
            files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 402

    def test_free_user_allowed_with_2_successful_conversions(self, tmp_path):
        from unittest.mock import patch
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u2", email="cv2@x.com", provider="google",
                       provider_id="cv-u2", plan="free"))
        for i in range(2):
            db.merge(File(id=f"cv-f2-{i}", user_id="cv-u2", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u2")
        with patch("app.main.process_job"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200

    def test_free_user_blocked_after_5_saved_files(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u3", email="cv3@x.com", provider="google",
                       provider_id="cv-u3", plan="free"))
        for i in range(5):
            db.merge(File(id=f"cv-f3-{i}", user_id="cv-u3", name="s", gp5_path=""))
        db.commit()
        db.close()

        token = create_access_token("cv-u3")
        r = client.post(
            "/convert",
            files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 402

    def test_pro_user_unlimited(self, tmp_path):
        from unittest.mock import patch
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u4", email="cv4@x.com", provider="google",
                       provider_id="cv-u4", plan="pro"))
        for i in range(10):
            db.merge(File(id=f"cv-f4-{i}", user_id="cv-u4", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u4")
        with patch("app.main.process_job"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200

    def test_anonymous_user_not_limited(self, tmp_path):
        """비로그인 유저는 사용량 제한 대상이 아니다 (기존 아키텍처 연장, 알려진 한계)."""
        from unittest.mock import patch

        client, _ = make_client(tmp_path)
        with patch("app.main.process_job"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
            )
        assert r.status_code == 200
```

- [ ] **Step 6: 테스트 실행 → 실패 확인**

Run: `python -m pytest tests/test_api.py::TestConvertUsageLimits -v`
Expected: `test_free_user_blocked_after_3_successful_conversions`와 `test_free_user_blocked_after_5_saved_files`가 402를 기대하는데 실제로는 200(제한 로직이 없어서)이라 실패. 나머지는 이미 통과(제한이 없으니까)

- [ ] **Step 7: /convert에 제한 체크 추가**

`app/main.py` 상단 import 목록에 추가:

```python
from app.routers.billing import count_usage, FREE_CONVERSIONS_LIMIT, FREE_FILES_LIMIT
```

`app/main.py`의 `convert` 함수 시작 부분, 현재 이렇게 되어 있는 곳:

```python
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=".pdf")
```

`current_user: ... ):` 다음, `fd, tmp_path = ...` 앞에 아래 블록을 삽입:

```python
async def convert(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_store),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    if current_user and current_user.plan == "free":
        conversions_used, files_used = count_usage(db, current_user.id)
        if conversions_used >= FREE_CONVERSIONS_LIMIT:
            raise HTTPException(
                status_code=402,
                detail=f"무료 플랜 월 변환 한도({FREE_CONVERSIONS_LIMIT}회)를 초과했습니다. "
                       f"Pro로 업그레이드하세요.",
            )
        if files_used >= FREE_FILES_LIMIT:
            raise HTTPException(
                status_code=402,
                detail=f"무료 플랜 저장 한도({FREE_FILES_LIMIT}개)를 초과했습니다. "
                       f"파일을 삭제하거나 Pro로 업그레이드하세요.",
            )

    fd, tmp_path = tempfile.mkstemp(prefix="upload_", suffix=".pdf")
```

- [ ] **Step 8: 테스트 실행 → 통과 확인**

Run: `python -m pytest tests/test_api.py::TestConvertUsageLimits -v`
Expected: 5 passed

- [ ] **Step 9: 전체 백엔드 회귀 확인**

Run: `python -m pytest -q`
Expected: 전부 통과 (기존 183 + Task 1~5 신규 = 확인)

- [ ] **Step 10: 커밋**

```bash
git add app/routers/billing.py app/main.py tests/test_billing.py tests/test_api.py
git commit -m "feat: 사용량 조회 API + /convert 무료플랜 사용량 제한 적용"
```

---

### Task 6: 프론트 api.ts 결제 함수 추가

**Files:**
- Modify: `frontend/src/lib/api.ts`
- Test: `frontend/src/__tests__/api.billing.test.ts` (신규)

**Interfaces:**
- Consumes: 없음 (Task 3/4/5의 백엔드 엔드포인트 호출)
- Produces: `interface UsageInfo { plan: string; conversions_used: number; conversions_limit: number; files_used: number; files_limit: number }`, `api.getUsage()`, `api.createCheckoutSession()`, `api.createPortalSession()` — Task 7(BillingPanel)이 사용

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/api.billing.test.ts` (신규):

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'

const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

beforeEach(() => mockFetch.mockReset())

describe('api 결제', () => {
  it('getUsage: GET /billing/usage 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        plan: 'free', conversions_used: 1, conversions_limit: 3,
        files_used: 2, files_limit: 5,
      }),
    })
    const { api } = await import('../lib/api')
    const result = await api.getUsage()
    expect(mockFetch).toHaveBeenCalledWith(
      '/billing/usage',
      expect.objectContaining({ headers: expect.anything() }),
    )
    expect(result.plan).toBe('free')
    expect(result.conversions_used).toBe(1)
  })

  it('createCheckoutSession: POST /billing/checkout 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ url: 'https://checkout.stripe.com/x' }),
    })
    const { api } = await import('../lib/api')
    const result = await api.createCheckoutSession()
    expect(mockFetch).toHaveBeenCalledWith(
      '/billing/checkout',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result.url).toBe('https://checkout.stripe.com/x')
  })

  it('createPortalSession: POST /billing/portal 호출', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ url: 'https://billing.stripe.com/x' }),
    })
    const { api } = await import('../lib/api')
    const result = await api.createPortalSession()
    expect(mockFetch).toHaveBeenCalledWith(
      '/billing/portal',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(result.url).toBe('https://billing.stripe.com/x')
  })

  it('createPortalSession 실패 시 Error throw', async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      json: async () => ({ detail: '구독 정보가 없습니다' }),
    })
    const { api } = await import('../lib/api')
    await expect(api.createPortalSession()).rejects.toThrow('구독 정보가 없습니다')
  })
})
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `npx vitest run src/__tests__/api.billing.test.ts`
Expected: FAIL — `api.getUsage is not a function` 등

- [ ] **Step 3: api.ts에 함수 추가**

`frontend/src/lib/api.ts` — `ShareInfo` 인터페이스 다음에 추가:

```typescript
export interface UsageInfo {
  plan: string
  conversions_used: number
  conversions_limit: number
  files_used: number
  files_limit: number
}
```

`export const api = { ... }` 객체 내부, 마지막 항목(`fetchSharedGP5`) 다음에 추가:

```typescript
  async getUsage(): Promise<UsageInfo> {
    return request<UsageInfo>('/billing/usage')
  },

  async createCheckoutSession(): Promise<{ url: string }> {
    return request<{ url: string }>('/billing/checkout', { method: 'POST' })
  },

  async createPortalSession(): Promise<{ url: string }> {
    return request<{ url: string }>('/billing/portal', { method: 'POST' })
  },
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `npx vitest run src/__tests__/api.billing.test.ts`
Expected: 4 passed

- [ ] **Step 5: 전체 프론트 회귀 확인**

Run: `npx vitest run`
Expected: 전부 통과

- [ ] **Step 6: 커밋**

```bash
git add frontend/src/lib/api.ts frontend/src/__tests__/api.billing.test.ts
git commit -m "feat: 프론트 api.ts에 Stripe 결제 함수 추가"
```

---

### Task 7: BillingPanel 컴포넌트 + App.tsx 연동

**Files:**
- Create: `frontend/src/components/Billing/BillingPanel.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/__tests__/BillingPanel.test.tsx` (신규)

**Interfaces:**
- Consumes: `api.getUsage`, `api.createCheckoutSession`, `api.createPortalSession`, `UsageInfo` (Task 6)
- Produces: `BillingPanel` 컴포넌트(props 없음) — 최종 UI, 이후 태스크 없음

- [ ] **Step 1: 실패 테스트 작성**

`frontend/src/__tests__/BillingPanel.test.tsx` (신규):

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi, describe, it, expect, beforeEach } from 'vitest'

vi.mock('../lib/api', () => ({
  api: {
    getUsage: vi.fn(),
    createCheckoutSession: vi.fn(),
    createPortalSession: vi.fn(),
  },
}))

import BillingPanel from '../components/Billing/BillingPanel'

describe('BillingPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.defineProperty(window, 'location', {
      value: { href: '' },
      writable: true,
      configurable: true,
    })
  })

  it('free 유저: 사용량 표시 + 업그레이드 버튼', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'free', conversions_used: 1, conversions_limit: 3,
      files_used: 2, files_limit: 5,
    })

    render(<BillingPanel />)

    await waitFor(() => expect(screen.getByText(/1\/3/)).toBeInTheDocument())
    expect(screen.getByText(/2\/5/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /업그레이드/i })).toBeInTheDocument()
  })

  it('pro 유저: 무제한 표시 + 구독관리 버튼', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'pro', conversions_used: 10, conversions_limit: 3,
      files_used: 20, files_limit: 5,
    })

    render(<BillingPanel />)

    await waitFor(() =>
      expect(screen.getByRole('button', { name: /구독 관리/i })).toBeInTheDocument(),
    )
  })

  it('업그레이드 클릭 → checkout url로 리다이렉트', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'free', conversions_used: 0, conversions_limit: 3,
      files_used: 0, files_limit: 5,
    })
    vi.mocked(api.createCheckoutSession).mockResolvedValue({
      url: 'https://checkout.stripe.com/x',
    })

    render(<BillingPanel />)
    await waitFor(() => screen.getByRole('button', { name: /업그레이드/i }))
    await userEvent.click(screen.getByRole('button', { name: /업그레이드/i }))

    await waitFor(() => expect(window.location.href).toBe('https://checkout.stripe.com/x'))
  })

  it('구독관리 클릭 → portal url로 리다이렉트', async () => {
    const { api } = await import('../lib/api')
    vi.mocked(api.getUsage).mockResolvedValue({
      plan: 'pro', conversions_used: 0, conversions_limit: 3,
      files_used: 0, files_limit: 5,
    })
    vi.mocked(api.createPortalSession).mockResolvedValue({
      url: 'https://billing.stripe.com/x',
    })

    render(<BillingPanel />)
    await waitFor(() => screen.getByRole('button', { name: /구독 관리/i }))
    await userEvent.click(screen.getByRole('button', { name: /구독 관리/i }))

    await waitFor(() => expect(window.location.href).toBe('https://billing.stripe.com/x'))
  })
})
```

- [ ] **Step 2: 테스트 실행 → 실패 확인**

Run: `npx vitest run src/__tests__/BillingPanel.test.tsx`
Expected: FAIL — 모듈 `../components/Billing/BillingPanel`을 찾을 수 없음

- [ ] **Step 3: BillingPanel.tsx 구현**

`frontend/src/components/Billing/BillingPanel.tsx` (신규):

```tsx
import { useEffect, useState } from 'react'
import { api, type UsageInfo } from '../../lib/api'

export default function BillingPanel() {
  const [usage, setUsage] = useState<UsageInfo | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    api.getUsage()
      .then(res => { if (!cancelled) setUsage(res) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [])

  async function handleUpgrade() {
    setBusy(true)
    try {
      const { url } = await api.createCheckoutSession()
      window.location.href = url
    } catch {
      setBusy(false)
    }
  }

  async function handleManage() {
    setBusy(true)
    try {
      const { url } = await api.createPortalSession()
      window.location.href = url
    } catch {
      setBusy(false)
    }
  }

  if (!usage) return null

  return (
    <div style={{ marginTop: 16, fontSize: 12, borderTop: '1px solid #ddd', paddingTop: 12 }}>
      <strong>요금제: {usage.plan === 'pro' ? 'Pro' : 'Free'}</strong>
      {usage.plan === 'free' ? (
        <div>
          <p>변환 {usage.conversions_used}/{usage.conversions_limit}</p>
          <p>저장 {usage.files_used}/{usage.files_limit}</p>
          <button onClick={handleUpgrade} disabled={busy}>Pro로 업그레이드</button>
        </div>
      ) : (
        <div>
          <p>무제한</p>
          <button onClick={handleManage} disabled={busy}>구독 관리</button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: 테스트 실행 → 통과 확인**

Run: `npx vitest run src/__tests__/BillingPanel.test.tsx`
Expected: 4 passed

- [ ] **Step 5: App.tsx에 연동**

`frontend/src/App.tsx` — import 목록에 추가:

```tsx
import BillingPanel from './components/Billing/BillingPanel'
```

`{token && (<button onClick={logout} style={{ marginTop: 16, fontSize: 12 }}>로그아웃</button>)}` 블록 다음 줄에 추가:

```tsx
        {token && <BillingPanel />}
```

- [ ] **Step 6: 전체 프론트 회귀 확인**

Run: `npx vitest run`
Expected: 전부 통과 (`App.test.tsx`는 토큰 없는 기본 상태로 렌더링하므로 `BillingPanel`이 마운트조차 안 되어 영향 없음 — 확인 차 실행)

- [ ] **Step 7: 타입체크 + lint 확인**

Run: `npx tsc --noEmit -p tsconfig.app.json && npm run lint`
Expected: 새로 생긴 에러 없음 (기존 pre-existing 항목만 존재)

- [ ] **Step 8: 커밋**

```bash
git add frontend/src/components/Billing/BillingPanel.tsx frontend/src/App.tsx frontend/src/__tests__/BillingPanel.test.tsx
git commit -m "feat: BillingPanel 컴포넌트 — 사용량 표시 + 업그레이드/구독관리"
```

---

## 최종 검증 (전체 태스크 완료 후)

- [ ] Run: `python -m pytest -q` — 전체 백엔드 통과 (기존 183 + 신규 = Task1(3)+Task2(3)+Task3(4)+Task4(6)+Task5(3+5)=24 → 총 207)
- [ ] Run: `cd frontend && npx vitest run` — 전체 프론트 통과 (기존 137 + Task6(4)+Task7(4)=8 → 총 145)
- [ ] 수동 확인은 이번엔 생략 — Stripe 계정이 없어 실제 결제/웹훅은 테스트 불가. 계정 생성 후 `.env`에 `STRIPE_SECRET_KEY`/`STRIPE_WEBHOOK_SECRET`/`STRIPE_PRICE_ID_PRO`를 채우고, Stripe CLI(`stripe listen --forward-to localhost:8000/billing/webhook`)로 로컬 웹훅 테스트를 별도로 진행할 것
