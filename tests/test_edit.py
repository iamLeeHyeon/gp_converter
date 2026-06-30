import json
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app
from app.auth import create_access_token

client = TestClient(app)

VALID_SNAPSHOT = {
    "tracks": [{
        "measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "beats": [
                {"duration": 1, "dotted": False, "status": "rest",
                 "dynamic": "mf", "notes": []}
            ],
        }]
    }]
}


def _make_token(user_id: str) -> str:
    return create_access_token(user_id)


def test_sync_200(tmp_path):
    """정상 sync → 200 OK + GP5 파일 덮어씀."""
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    user = User(id="u1", email="a@b.com", provider="google", provider_id="x")
    gp5_path = str(tmp_path / "out.gp5")
    open(gp5_path, "wb").close()
    file = File(id="f1", user_id="u1", name="test", gp5_path=gp5_path)
    db.merge(user); db.merge(file); db.commit()
    db.close()

    token = _make_token("u1")
    with patch("app.routers.edit.snapshot_to_gp5") as mock_fn:
        mock_fn.return_value = gp5_path
        resp = client.post(
            "/files/f1/sync",
            content=json.dumps(VALID_SNAPSHOT),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json"},
        )
    assert resp.status_code == 200
    mock_fn.assert_called_once()


def test_sync_403_wrong_user():
    """타인 파일 접근 → 403."""
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    user2 = User(id="u2", email="b@b.com", provider="google", provider_id="y")
    db.merge(user2)
    # f1은 u1 소유 (test_sync_200에서 이미 생성)
    db.commit(); db.close()

    token = _make_token("u2")
    resp = client.post(
        "/files/f1/sync",
        content=json.dumps(VALID_SNAPSHOT),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_sync_404():
    """존재하지 않는 파일 → 404."""
    token = _make_token("u1")
    resp = client.post(
        "/files/nonexistent/sync",
        content=json.dumps(VALID_SNAPSHOT),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 404


def test_sync_422_bad_json():
    """빈 tracks → 422."""
    token = _make_token("u1")
    resp = client.post(
        "/files/f1/sync",
        content=json.dumps({"tracks": []}),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    assert resp.status_code == 422
