import os, pytest, io
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("GITHUB_CLIENT_ID", "gh-id")
os.environ.setdefault("GITHUB_CLIENT_SECRET", "gh-secret")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
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
