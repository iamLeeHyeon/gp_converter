import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user_file(db, tmp_path, uid="u1", fid="f1", gp5_bytes=b"GP5DATA"):
    from app.models import User, File
    path = str(tmp_path / f"{fid}.gp5")
    with open(path, "wb") as f:
        f.write(gp5_bytes)
    user = User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid)
    file = File(id=fid, user_id=uid, name="my_song", gp5_path=path)
    db.merge(user); db.merge(file); db.commit()
    return path


# ── Task 1 ──────────────────────────────────────────────────────────────────

class TestGP5Download:
    def test_200_returns_gp5_file(self, tmp_path):
        from app.database import SessionLocal
        db = SessionLocal()
        path = _setup_user_file(db, tmp_path)
        db.close()

        resp = client.get("/files/f1/download",
                          headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 200
        assert resp.content == b"GP5DATA"
        assert "attachment" in resp.headers.get("content-disposition", "")

    def test_403_wrong_user(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        _setup_user_file(db, tmp_path, uid="u1", fid="f1")
        db.merge(User(id="u2", email="u2@x.com", provider="google", provider_id="u2"))
        db.commit(); db.close()

        resp = client.get("/files/f1/download",
                          headers={"Authorization": f"Bearer {_tok('u2')}"})
        assert resp.status_code == 403

    def test_404_file_not_found(self):
        resp = client.get("/files/nonexistent/download",
                          headers={"Authorization": f"Bearer {_tok('u1')}"})
        assert resp.status_code == 404

    def test_404_gp5_path_missing_on_disk(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User, File
        db = SessionLocal()
        db.merge(User(id="u3", email="u3@x.com", provider="google", provider_id="u3"))
        db.merge(File(id="f3", user_id="u3", name="gone", gp5_path="/nonexistent/path.gp5"))
        db.commit(); db.close()

        resp = client.get("/files/f3/download",
                          headers={"Authorization": f"Bearer {_tok('u3')}"})
        assert resp.status_code == 404
