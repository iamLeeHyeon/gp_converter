import os
import pytest
import guitarpro as gpm

from app.pipeline.token_to_gp import snapshot_to_gp5


def _snap_1track_1measure(**measure_kwargs):
    """단일 트랙, 단일 마디 스냅샷 생성 헬퍼."""
    base = {
        "timeSignature": {"num": 4, "den": 4},
        "voices": [[
            {"duration": 4, "dotted": False, "status": "normal",
             "dynamic": "mf", "notes": [{"string": 1, "fret": 0}]},
        ]],
    }
    base.update(measure_kwargs)
    return {"tracks": [{"measures": [base]}]}


class TestSnapshotV2MeasureAttrs:
    def test_keySignature_1_written(self, tmp_path):
        """keySignature=1 → GP5 MeasureHeader.keySignature value[0]=1 (1 sharp = GMajor)."""
        snap = _snap_1track_1measure(keySignature=1)
        path = str(tmp_path / "key1.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].keySignature.value[0] == 1

    def test_keySignature_default_0(self, tmp_path):
        """keySignature 없으면 0(C장조)."""
        snap = _snap_1track_1measure()
        path = str(tmp_path / "key0.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].keySignature.value[0] == 0

    def test_sectionMarker_written(self, tmp_path):
        """sectionMarker='Intro' → GP5 MeasureHeader.marker.title='Intro'."""
        snap = _snap_1track_1measure(sectionMarker="Intro")
        path = str(tmp_path / "marker.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].marker is not None
        assert song.measureHeaders[0].marker.title == "Intro"

    def test_no_sectionMarker_no_marker(self, tmp_path):
        """sectionMarker 없으면 marker=None."""
        snap = _snap_1track_1measure()
        path = str(tmp_path / "nomarker.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert song.measureHeaders[0].marker is None

    def test_voices_fallback_to_beats(self, tmp_path):
        """v1 호환: voices 없고 beats 있으면 정상 변환."""
        snap = {"tracks": [{"measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "beats": [
                {"duration": 4, "dotted": False, "status": "normal",
                 "dynamic": "mf", "notes": [{"string": 1, "fret": 5}]},
            ],
        }]}]}
        path = str(tmp_path / "v1compat.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        note_ons = [n for t in song.tracks for m in t.measures
                    for v in m.voices for b in v.beats
                    for n in b.notes if n.type == gpm.NoteType.normal]
        assert len(note_ons) >= 1


class TestSnapshotV2MultiTrack:
    def test_two_tracks_written(self, tmp_path):
        """2개 트랙 스냅샷 → GP5에 2개 트랙."""
        snap = {
            "tracks": [
                {"name": "Guitar", "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "voices": [[{"duration": 4, "dotted": False, "status": "normal",
                                  "dynamic": "mf", "notes": [{"string": 1, "fret": 0}]}]],
                }]},
                {"name": "Bass", "measures": [{
                    "timeSignature": {"num": 4, "den": 4},
                    "voices": [[{"duration": 4, "dotted": False, "status": "normal",
                                  "dynamic": "mf", "notes": [{"string": 1, "fret": 3}]}]],
                }]},
            ]
        }
        path = str(tmp_path / "two_tracks.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        assert len(song.tracks) == 2
        assert song.tracks[1].name == "Bass"

    def test_drop_d_tuning_applied(self, tmp_path):
        """Drop D 튜닝 → 6번현 38(D2) 저장."""
        snap = {"tracks": [{
            "name": "Guitar",
            "tuning": [64, 59, 55, 50, 45, 38],
            "measures": [{"timeSignature": {"num": 4, "den": 4},
                          "voices": [[{"duration": 4, "dotted": False, "status": "rest",
                                        "dynamic": "mf", "notes": []}]]}],
        }]}
        path = str(tmp_path / "dropd.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        # GuitarString.value: string 1=index0(high E=64), string 6=index5(low=38)
        assert song.tracks[0].strings[5].value == 38

    def test_voice1_beats_written(self, tmp_path):
        """voices[1] beats → GP5 measure voice[1]에 음표 존재."""
        snap = {"tracks": [{"measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "voices": [
                [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf", "notes": [{"string": 1, "fret": 0}]}],
                [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf", "notes": [{"string": 2, "fret": 3}]}],
            ],
        }]}]}
        path = str(tmp_path / "voice1.gp5")
        snapshot_to_gp5(snap, path)
        song = gpm.parse(path)
        # voice[1]에 음표 확인
        v1_notes = [n for b in song.tracks[0].measures[0].voices[1].beats
                    for n in b.notes if b.status == gpm.BeatStatus.normal]
        assert len(v1_notes) >= 1
