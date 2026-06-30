import os
import pytest
import json

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


def test_sse_unknown_job_returns_failed_event():
    with client.stream("GET", "/jobs/nonexistent-job/stream") as r:
        assert r.status_code == 200
        line = next(r.iter_lines())
        data = json.loads(line.replace("data: ", ""))
        assert data["status"] == "failed"


def test_sse_done_job_streams_done():
    from app.jobs import JobStore, JobStatus
    from app.routers.jobs_sse import _get_store
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        store = JobStore(d)
        job = store.create()
        store.update(job.id, status=JobStatus.DONE, progress_pct=100)

        # SSE 엔드포인트가 같은 store 인스턴스를 바라보도록 override
        app.dependency_overrides[_get_store] = lambda: store
        try:
            with client.stream("GET", f"/jobs/{job.id}/stream") as r:
                for line in r.iter_lines():
                    if line.startswith("data:"):
                        data = json.loads(line[6:])
                        assert data["status"] == "done"
                        assert data["pct"] == 100
                        break
        finally:
            del app.dependency_overrides[_get_store]
