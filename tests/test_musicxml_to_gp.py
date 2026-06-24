"""
tests/test_musicxml_to_gp.py

musicxml_to_gp5 변환기 테스트.
fixture: tests/fixtures/sample.musicxml (C장조 음계: C4~C5, 8분음표 8개)
"""

import os
import pytest
import guitarpro

from app.pipeline.musicxml_to_gp import musicxml_to_gp5, GpConvertError

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.musicxml")
EXPECTED_MIDI = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 D4 E4 F4 G4 A4 B4 C5


def test_converts_fixture_to_valid_gp5(tmp_path):
    """fixture를 변환하면 유효한 .gp5 파일이 생성돼야 한다."""
    out = str(tmp_path / "out.gp5")
    result = musicxml_to_gp5(FIXTURE, out)

    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0

    # GP5 파일 헤더에 "GUITAR PRO" 포함 여부 확인
    with open(out, "rb") as f:
        header = f.read(64)
    assert b"GUITAR PRO" in header, f"GP5 헤더 없음: {header!r}"


def test_roundtrip_preserves_pitches(tmp_path):
    """변환 후 파싱하면 원래 MIDI 시퀀스와 일치해야 한다."""
    out = str(tmp_path / "roundtrip.gp5")
    musicxml_to_gp5(FIXTURE, out)

    song = guitarpro.parse(out)
    track = song.tracks[0]

    # string.number → string.value 매핑
    string_val = {s.number: s.value for s in track.strings}

    actual_midi = []
    for measure in track.measures:
        for voice in measure.voices:
            for beat in voice.beats:
                for note in beat.notes:
                    midi = string_val[note.string] + note.value
                    actual_midi.append(midi)

    assert actual_midi == EXPECTED_MIDI, (
        f"MIDI 시퀀스 불일치\n예상: {EXPECTED_MIDI}\n실제: {actual_midi}"
    )


def test_roundtrip_preserves_beat_structure(tmp_path):
    """각 음표는 별개의 순차 비트여야 한다 (동시발음 화음으로 합쳐지면 안 됨).

    버그 재현: Beat.status를 설정하지 않으면(기본값 BeatStatus.empty) GP5 writer가
    같은 마디의 모든 빈 status 비트를 하나로 합치고 그 안의 음표를 전부
    동시발음 화음으로 몰아넣는다. fixture는 단음(monophonic) 음계이므로
    비트마다 음표가 정확히 1개씩, 총 8개 비트여야 한다.
    """
    out = str(tmp_path / "roundtrip_structure.gp5")
    musicxml_to_gp5(FIXTURE, out)

    song = guitarpro.parse(out)
    track = song.tracks[0]

    beats_with_notes = [
        beat
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        if beat.notes
    ]

    assert len(beats_with_notes) == len(EXPECTED_MIDI), (
        f"비트 개수 불일치(화음으로 합쳐졌을 가능성): "
        f"예상 {len(EXPECTED_MIDI)}개 비트, 실제 {len(beats_with_notes)}개"
    )
    for beat in beats_with_notes:
        assert len(beat.notes) == 1, (
            f"비트당 음표가 1개여야 하는데 {len(beat.notes)}개 (동시발음 화음으로 합쳐짐)"
        )


def test_empty_musicxml_raises(tmp_path):
    """음표 없는 MusicXML에서 GpConvertError('변환할 음표 없음')를 발생시켜야 한다."""
    empty_xml = tmp_path / "empty.musicxml"
    empty_xml.write_text(
        '<score-partwise version="3.1">'
        "<part-list>"
        '<score-part id="P1"><part-name>x</part-name></score-part>'
        "</part-list>"
        '<part id="P1"><measure number="1"></measure></part>'
        "</score-partwise>",
        encoding="utf-8",
    )
    out = str(tmp_path / "out.gp5")

    with pytest.raises(GpConvertError, match="변환할 음표 없음"):
        musicxml_to_gp5(str(empty_xml), out)
