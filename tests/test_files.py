from fastapi.testclient import TestClient
from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user_file(db, tmp_path, uid="fu1", fid="ff1"):
    from app.models import User, File
    path = str(tmp_path / f"{fid}.gp5")
    with open(path, "wb") as f:
        f.write(b"GP5DATA")
    db.merge(User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid))
    db.merge(File(id=fid, user_id=uid, name="test", gp5_path=path))
    db.commit()
    return path


def test_delete_file_204(tmp_path):
    from app.database import SessionLocal
    db = SessionLocal()
    _setup_user_file(db, tmp_path)
    db.close()

    resp = client.delete("/files/ff1", headers={"Authorization": f"Bearer {_tok('fu1')}"})
    assert resp.status_code == 204


def test_delete_file_delegates_to_storage(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.database import SessionLocal
    db = SessionLocal()
    _setup_user_file(db, tmp_path, uid="fu2", fid="ff2")
    db.close()

    fake_storage = MagicMock()
    fake_storage.exists.return_value = True

    with patch("app.routers.files.get_storage", return_value=fake_storage):
        resp = client.delete("/files/ff2", headers={"Authorization": f"Bearer {_tok('fu2')}"})

    assert resp.status_code == 204
    fake_storage.exists.assert_called_once()
    fake_storage.delete.assert_called_once()


def test_delete_file_404_missing():
    resp = client.delete("/files/nonexistent", headers={"Authorization": f"Bearer {_tok('fu1')}"})
    assert resp.status_code == 404
