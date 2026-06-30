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
    location = r.headers["location"]
    assert "accounts.google.com" in location
    assert "state=" in location
    assert "oauth_state" in r.cookies


def test_github_login_redirects():
    r = client.get("/auth/github")
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "github.com/login/oauth/authorize" in location
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


def test_github_callback_missing_state():
    """state 쿠키 없이 callback → 400"""
    r = client.get("/auth/github/callback", params={"code": "anycode", "state": "somestate"})
    assert r.status_code == 400
    assert "invalid state" in r.json()["detail"]


def test_github_callback_state_mismatch():
    """state 불일치 → 400"""
    r = client.get(
        "/auth/github/callback",
        params={"code": "anycode", "state": "wrongstate"},
        cookies={"oauth_state": "correctstate"},
    )
    assert r.status_code == 400
    assert "invalid state" in r.json()["detail"]


def test_refresh_invalid_token():
    r = client.post("/auth/refresh", json={"refresh_token": "bad.token.here"})
    assert r.status_code == 401


def test_refresh_wrong_type():
    from app.auth import create_access_token
    token = create_access_token("user1")  # access, not refresh
    r = client.post("/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401
