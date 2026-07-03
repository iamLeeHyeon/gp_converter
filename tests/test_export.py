import copy
import os
import pytest
import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus
import mido
from fastapi.testclient import TestClient
from starlette.responses import Response
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
            with open(midi_out, "wb") as fh:
                fh.write(b"MThd")  # 최소 MIDI 헤더
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


# ── Bug Fix Tests ────────────────────────────────────────────────────────────

def _make_gp5_with_tie(tmp_path) -> str:
    """beat1=normal + beat2=tie 인 GP5 파일 생성."""
    song = guitarpro.Song()
    track = song.tracks[0]
    voice = track.measures[0].voices[0]
    voice.beats = []

    b1 = Beat(voice)
    b1.duration = gpm.Duration(); b1.duration.value = 4
    b1.status = BeatStatus.normal
    n1 = Note(b1); n1.string = 1; n1.value = 5; n1.type = NoteType.normal
    b1.notes = [n1]

    b2 = Beat(voice)
    b2.duration = gpm.Duration(); b2.duration.value = 4
    b2.status = BeatStatus.normal
    n2 = Note(b2); n2.string = 1; n2.value = 5; n2.type = NoteType.tie
    b2.notes = [n2]

    voice.beats = [b1, b2]
    path = str(tmp_path / "tie.gp5")
    guitarpro.write(song, path)
    return path


def _make_gp5_10_tracks(tmp_path) -> str:
    """10개 트랙(각 트랙에 음표 1개)인 GP5 파일 생성."""
    song = guitarpro.Song()
    base_track = song.tracks[0]

    # 첫 트랙 음표 추가
    v0 = base_track.measures[0].voices[0]
    v0.beats = []
    b = Beat(v0); b.duration = gpm.Duration(); b.duration.value = 4
    b.status = BeatStatus.normal
    n = Note(b); n.string = 1; n.value = 0; n.type = NoteType.normal
    b.notes = [n]; v0.beats = [b]

    # 트랙 9개 추가 (총 10개)
    for i in range(1, 10):
        t = copy.deepcopy(base_track)
        t.number = i + 1
        song.tracks.append(t)

    path = str(tmp_path / "tracks10.gp5")
    guitarpro.write(song, path)
    return path


def _make_gp5_short_voice0(tmp_path) -> str:
    """voice[0]이 2박만 있는 4/4 마디 + 2번째 마디에 음표 있는 GP5."""
    song = guitarpro.Song()
    track = song.tracks[0]
    mh0 = song.measureHeaders[0]
    mh0.timeSignature.numerator = 4
    mh0.timeSignature.denominator.value = 4

    measure1 = track.measures[0]
    v0 = measure1.voices[0]
    v0.beats = []
    for _ in range(2):  # 2박만 — voice[0] 합 = 1920 ticks (< 3840)
        rb = Beat(v0); rb.status = BeatStatus.rest
        rb.duration = gpm.Duration(); rb.duration.value = 4
        rb.notes = []; v0.beats.append(rb)

    # 2번째 마디: measure header가 올바른 start 보유
    mh1 = gpm.MeasureHeader()
    mh1.number = 2
    mh1.start = mh0.start + mh0.length  # 올바른 start
    mh1.timeSignature.numerator = 4
    mh1.timeSignature.denominator.value = 4
    song.measureHeaders.append(mh1)

    m2 = gpm.Measure(track, mh1)
    v1 = m2.voices[0]
    bm = Beat(v1); bm.duration = gpm.Duration(); bm.duration.value = 4
    bm.status = BeatStatus.normal
    nm = Note(bm); nm.string = 1; nm.value = 0; nm.type = NoteType.normal
    bm.notes = [nm]; v1.beats = [bm]
    track.measures.append(m2)

    path = str(tmp_path / "short_voice0.gp5")
    guitarpro.write(song, path)
    return path


def _note_off_ticks(mid: mido.MidiFile) -> dict[int, int]:
    """pitch → 마지막 note_off 절대 tick 맵."""
    result = {}
    for track in mid.tracks:
        abs_t = 0
        for msg in track:
            abs_t += msg.time
            if msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                result[msg.note] = abs_t
    return result


def _note_on_events(mid: mido.MidiFile) -> list[tuple[int, int, int]]:
    """(pitch, abs_tick, channel) 리스트."""
    events = []
    for track in mid.tracks:
        abs_t = 0
        for msg in track:
            abs_t += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                events.append((msg.note, abs_t, msg.channel))
    return events


class TestMidiExportBugFixes:
    def test_tie_note_extends_note_off(self, tmp_path):
        """타이 음표: note_off가 1920 tick(2박) 위치여야 함(960 아님)."""
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = _make_gp5_with_tie(tmp_path)
        midi_path = str(tmp_path / "tie.mid")
        gp5_to_midi(gp5_path, midi_path)

        mid = mido.MidiFile(midi_path)
        offs = _note_off_ticks(mid)
        assert offs.get(69) == 1920, f"note_off(69) 예상 1920, 실제 {offs.get(69)}"

    def test_channel_9_skipped(self, tmp_path):
        """10번째 트랙(ti=9)은 GM 퍼커션 채널 9를 피해 채널 10을 써야 함."""
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = _make_gp5_10_tracks(tmp_path)
        midi_path = str(tmp_path / "ch9.mid")
        gp5_to_midi(gp5_path, midi_path)

        mid = mido.MidiFile(midi_path)
        channels_used = {msg.channel for track in mid.tracks for msg in track
                         if hasattr(msg, 'channel')}
        assert 9 not in channels_used, f"채널 9가 사용됨: {channels_used}"

    def test_multivoice_measure_start_uses_header_length(self, tmp_path):
        """voice[0]이 짧아도 2번째 마디 음표는 3840 tick(4/4 마디 전체) 이후여야 함."""
        from app.pipeline.midi_export import gp5_to_midi

        gp5_path = _make_gp5_short_voice0(tmp_path)
        midi_path = str(tmp_path / "voice0.mid")
        gp5_to_midi(gp5_path, midi_path)

        mid = mido.MidiFile(midi_path)
        events = _note_on_events(mid)
        ticks = [t for _, t, _ in events]
        assert 3840 in ticks, f"마디 2 음표가 3840 tick에 없음: {ticks}"


# ── Task 3 ──────────────────────────────────────────────────────────────────

class TestStorageDelegation:
    def test_download_gp5_delegates_to_storage(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        fake_storage = MagicMock()
        fake_storage.exists.return_value = True
        fake_storage.response_for.return_value = Response(
            content=b"FAKE", media_type="application/octet-stream"
        )

        with patch("app.routers.export.get_storage", return_value=fake_storage):
            resp = client.get("/files/f1/download",
                              headers={"Authorization": f"Bearer {_tok('u1')}"})

        assert resp.status_code == 200
        fake_storage.exists.assert_called_once()
        fake_storage.response_for.assert_called_once()

    def test_export_midi_delegates_to_storage_load_to_temp(self, tmp_path):
        from unittest.mock import MagicMock, patch
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user_file(db, tmp_path)
        db.close()

        # load_to_temp는 실제로는 항상 새로 만든 사본을 반환한다(원본을 건드리면 안 됨) —
        # 엔드포인트가 다 쓰고 os.unlink로 지우므로, mock도 반드시 별도 파일을 줘야 한다.
        fake_gp5_copy = tmp_path / "fake_copy.gp5"
        fake_gp5_copy.write_bytes(b"GP5DATA")

        fake_storage = MagicMock()
        fake_storage.exists.return_value = True
        fake_storage.load_to_temp.return_value = str(fake_gp5_copy)

        with patch("app.routers.export.get_storage", return_value=fake_storage):
            resp = client.get("/files/f1/export/midi",
                              headers={"Authorization": f"Bearer {_tok('u1')}"})

        assert resp.status_code == 422  # 가짜 GP5DATA라 MIDI 변환은 실패하지만, 위임 자체는 확인됨
        fake_storage.load_to_temp.assert_called_once()
