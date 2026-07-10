import os, pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("FRONTEND_URL", "http://localhost:5173")

from app.database import Base, get_db
from app.main import app

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_engine)
_Session = sessionmaker(bind=_engine)


def _override_db():
    s = _Session()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture(autouse=True)
def _set_db_override():
    app.dependency_overrides[get_db] = _override_db
    yield
    app.dependency_overrides.pop(get_db, None)


client = TestClient(app, follow_redirects=False)


def test_google_login_redirects():
    r = client.get("/auth/google")
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "accounts.google.com" in location
    assert "state=" in location
    assert "oauth_state" in r.cookies


def test_google_callback_missing_state():
    """state 쿠키 없이 callback → 400"""
    r = client.get("/auth/google/callback", params={"code": "anycode", "state": "somestate"})
    assert r.status_code == 400
    assert "invalid state" in r.json()["detail"]


def test_google_callback_state_mismatch():
    """state 불일치 → 400"""
    r = client.get(
        "/auth/google/callback",
        params={"code": "anycode", "state": "wrongstate"},
        cookies={"oauth_state": "correctstate"},
    )
    assert r.status_code == 400
    assert "invalid state" in r.json()["detail"]


def _mock_google_async_client(token_json, userinfo_json):
    tok_resp = MagicMock()
    tok_resp.raise_for_status = MagicMock()
    tok_resp.json = MagicMock(return_value=token_json)

    info_resp = MagicMock()
    info_resp.raise_for_status = MagicMock()
    info_resp.json = MagicMock(return_value=userinfo_json)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=tok_resp)
    mock_client.get = AsyncMock(return_value=info_resp)

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def test_google_callback_creates_new_user():
    """정상 콜백 경로: 새 구글 유저 생성 후 프론트로 토큰과 함께 리다이렉트."""
    # client는 파일 전체에서 공유되는 인스턴스라 앞선 테스트(test_google_login_redirects)가
    # 남긴 oauth_state 쿠키가 세션 쿠키jar에 남아있다 — per-request cookies와 병합돼
    # 값이 안 겹치면 "invalid state"로 새므로 먼저 비운다.
    client.cookies.clear()
    ctx = _mock_google_async_client(
        {"access_token": "tok"}, {"id": "111", "email": "newgoogle@example.com"},
    )
    with patch("app.routers.auth.httpx.AsyncClient", return_value=ctx):
        r = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": "s"},
            cookies={"oauth_state": "s"},
        )
    assert r.status_code in (302, 307)
    assert "access_token=" in r.headers["location"]


def test_google_callback_rejects_email_already_used_via_password():
    """비밀번호로 이미 가입된 이메일로 구글 로그인 시도 → 처리되지 않은 500(unique
    제약 위반) 대신 register()와 동일하게 400을 반환해야 한다."""
    client.post("/auth/register", json={"email": "dup@example.com", "password": "password123"})

    client.cookies.clear()
    ctx = _mock_google_async_client(
        {"access_token": "tok"}, {"id": "222", "email": "dup@example.com"},
    )
    with patch("app.routers.auth.httpx.AsyncClient", return_value=ctx):
        r = client.get(
            "/auth/google/callback",
            params={"code": "c", "state": "s"},
            cookies={"oauth_state": "s"},
        )
    assert r.status_code == 400
    assert "Password" in r.json()["detail"]


def test_refresh_invalid_token():
    r = client.post("/auth/refresh", json={"refresh_token": "bad.token.here"})
    assert r.status_code == 401


def test_refresh_wrong_type():
    from app.auth import create_access_token
    token = create_access_token("user1")  # access, not refresh
    r = client.post("/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401
