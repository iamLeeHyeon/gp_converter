import os
import pytest
import mido
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


# ── Task 2 ──────────────────────────────────────────────────────────────────

class TestMidiExport:
    def test_gp5_to_midi_produces_valid_midi(self, tmp_path):
        """실제 GP5 → MIDI 변환 후 mido로 파싱 가능 여부 확인."""
        from app.pipeline.token_to_gp import snapshot_to_gp5
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = str(tmp_path / "test.gp5")
        snapshot_to_gp5({
            "tracks": [{
                "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "beats": [
                        {"duration": 4, "dotted": False, "status": "normal",
                         "dynamic": "mf", "notes": [{"string": 1, "fret": 5}]},
                        {"duration": 4, "dotted": False, "status": "rest",
                         "dynamic": "mf", "notes": []},
                    ],
                }]
            }]
        }, gp5_path)

        midi_path = str(tmp_path / "out.mid")
        result = gp5_to_midi(gp5_path, midi_path)

        assert result == midi_path
        assert os.path.exists(midi_path)
        mid = mido.MidiFile(midi_path)
        assert mid.ticks_per_beat == 960
        # 템포 트랙 포함 최소 2개 트랙
        assert len(mid.tracks) >= 2
        # 음표가 있는 트랙에 note_on 메시지 존재
        note_ons = [m for t in mid.tracks for m in t if m.type == 'note_on' and m.velocity > 0]
        assert len(note_ons) >= 1

    def test_gp5_to_midi_correct_pitch(self, tmp_path):
        """현 1, 프렛 5 → MIDI pitch 69 (E4 string open=64, +5=69)."""
        from app.pipeline.token_to_gp import snapshot_to_gp5
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = str(tmp_path / "pitch.gp5")
        snapshot_to_gp5({
            "tracks": [{
                "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "beats": [
                        {"duration": 4, "dotted": False, "status": "normal",
                         "dynamic": "mf", "notes": [{"string": 1, "fret": 5}]},
                    ],
                }]
            }]
        }, gp5_path)

        midi_path = str(tmp_path / "pitch.mid")
        gp5_to_midi(gp5_path, midi_path)
        mid = mido.MidiFile(midi_path)
        note_ons = [m for t in mid.tracks for m in t if m.type == 'note_on' and m.velocity > 0]
        assert any(m.note == 69 for m in note_ons)

    def test_midi_endpoint_200(self, tmp_path):
        """MIDI 엔드포인트 — 200 + audio/midi Content-Type."""
        from app.database import SessionLocal
        with patch("app.routers.export.gp5_to_midi") as mock_fn:
            midi_out = str(tmp_path / "mock.mid")
            open(midi_out, "wb").write(b"MThd")  # 최소 MIDI 헤더
            mock_fn.return_value = midi_out

            db = SessionLocal()
            _setup_user_file(db, tmp_path, uid="u4", fid="f4")
            db.close()

            resp = client.get("/files/f4/export/midi",
                              headers={"Authorization": f"Bearer {_tok('u4')}"})
        assert resp.status_code == 200
        assert "midi" in resp.headers.get("content-type", "")

    def test_midi_endpoint_403(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        _setup_user_file(db, tmp_path, uid="u5", fid="f5")
        db.merge(User(id="u6", email="u6@x.com", provider="google", provider_id="u6"))
        db.commit(); db.close()

        resp = client.get("/files/f5/export/midi",
                          headers={"Authorization": f"Bearer {_tok('u6')}"})
        assert resp.status_code == 403
