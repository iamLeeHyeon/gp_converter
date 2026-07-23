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


def test_list_files_excludes_unfinished_gp5_path(tmp_path):
    """gp5_path==""인(변환 진행 중이거나 영영 실패한) 예약 레코드는 목록에
    나오면 안 된다 — 안 그러면 클릭해도 다운로드 못 하는 깨진 항목이 "내
    파일" 목록에 영구 노출된다(worker.py는 변환 실패 시 File을 안 건드려서
    gp5_path가 계속 빈 채로 남기 때문)."""
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    db.merge(User(id="fu3", email="fu3@x.com", provider="google", provider_id="fu3"))
    ready_path = str(tmp_path / "ready.gp5")
    with open(ready_path, "wb") as f:
        f.write(b"GP5DATA")
    db.merge(File(id="ff3-ready", user_id="fu3", name="완료됨", gp5_path=ready_path))
    db.merge(File(id="ff3-orphan", user_id="fu3", name="실패함", gp5_path=""))
    db.commit()
    db.close()

    resp = client.get("/files", headers={"Authorization": f"Bearer {_tok('fu3')}"})

    assert resp.status_code == 200
    ids = [f["id"] for f in resp.json()]
    assert "ff3-ready" in ids
    assert "ff3-orphan" not in ids
