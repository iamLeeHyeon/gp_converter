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


# sample.musicxml(EXPECTED_MIDI = [60,62,64,65,67,69,71,72])에서
# 기존 휴리스틱(최저프렛)이 실제로 고르는 (현,프렛)을 사람이 검증한 값:
#   60→(2,1) 62→(2,3) 64→(1,0) 65→(1,1) 67→(1,3) 69→(1,5) 71→(1,7) 72→(1,8)
# 탭 힌트 테스트에서는 이와 "다른" 가짜 값(전부 3번줄)을 줘서
# 힌트가 실제로 휴리스틱을 덮어쓰는지 증명한다.
FAKE_TAB_HINTS = [(3, 5), (3, 7), (3, 9), (3, 10), (3, 12), (3, 14), (3, 16), (3, 17)]


def test_tab_hints_override_heuristic_when_count_matches(tmp_path):
    """tab_hints 개수가 음표 개수와 일치하면 휴리스틱 대신 힌트를 그대로 써야 한다."""
    out = str(tmp_path / "tab_hint.gp5")
    musicxml_to_gp5(FIXTURE, out, tab_hints=FAKE_TAB_HINTS)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    actual = [
        (note.string, note.value)
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert actual == FAKE_TAB_HINTS


def test_tab_hints_ignored_when_count_mismatches(tmp_path):
    """tab_hints 개수가 음표 개수와 다르면 힌트를 무시하고 기존 휴리스틱을 써야 한다."""
    out = str(tmp_path / "tab_mismatch.gp5")
    mismatched_hints = FAKE_TAB_HINTS[:5]  # 8개 음표인데 5개만 줌
    musicxml_to_gp5(FIXTURE, out, tab_hints=mismatched_hints)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    actual = [
        (note.string, note.value)
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    # 휴리스틱(최저프렛) 결과와 같아야 하고, 가짜 힌트와는 달라야 한다.
    assert actual == [(2, 1), (2, 3), (1, 0), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8)]
    assert actual != FAKE_TAB_HINTS[:5] + actual[5:]
