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
