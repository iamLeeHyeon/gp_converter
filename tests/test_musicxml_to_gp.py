"""
tests/test_musicxml_to_gp.py

musicxml_to_gp5 변환기 테스트.
fixture: tests/fixtures/sample.musicxml (C장조 음계: C4~C5, 8분음표 8개로 "적힌" 악보.
실제 클래식/핑거스타일 기타 표준악보 관행상 적힌 음보다 1옥타브 낮게 소리난다 —
그래서 변환 결과의 실제(sounding) MIDI는 적힌 값에서 12를 뺀 것이어야 한다.)
"""

import os
from unittest.mock import patch

import pytest
import guitarpro

from app.pipeline.musicxml_to_gp import (
    musicxml_to_gp5,
    GpConvertError,
    _build_song,
    MeasureData,
    NoteEvent,
)

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.musicxml")
# fixture에 "적힌" 음(WRITTEN_MIDI)과, 기타 표기 관행(1옥타브 낮게 소리남) 적용 후
# 실제(sounding) MIDI. GP5에는 실제 소리나는 음이 들어가야 한다.
WRITTEN_MIDI = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 D4 E4 F4 G4 A4 B4 C5 (적힌 음)
EXPECTED_MIDI = [m - 12 for m in WRITTEN_MIDI]  # C3 D3 E3 F3 G3 A3 B3 C4 (실제 소리)


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


# sample.musicxml(실제 소리나는 EXPECTED_MIDI = [48,50,52,53,55,57,59,60])에서
# 기존 휴리스틱(최저프렛)이 실제로 고르는 (현,프렛)을 사람이 검증한 값:
#   48→(5,3) 50→(4,0) 52→(4,2) 53→(4,3) 55→(3,0) 57→(3,2) 59→(2,0) 60→(2,1)
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
    assert actual == [(5, 3), (4, 0), (4, 2), (4, 3), (3, 0), (3, 2), (2, 0), (2, 1)]
    assert actual != FAKE_TAB_HINTS[:5] + actual[5:]


def test_tab_hints_ignored_when_fret_out_of_range(tmp_path):
    """힌트의 프렛이 0~24 범위를 벗어나면 전체를 무시하고 휴리스틱으로 폴백해야 한다."""
    out = str(tmp_path / "tab_invalid_fret.gp5")
    invalid_hints = [(3, 5), (3, 7), (3, 9), (3, 10), (3, 12), (3, 14), (3, 99), (3, 17)]
    musicxml_to_gp5(FIXTURE, out, tab_hints=invalid_hints)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    actual = [
        (note.string, note.value)
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert actual == [(5, 3), (4, 0), (4, 2), (4, 3), (3, 0), (3, 2), (2, 0), (2, 1)]


def test_out_of_range_note_is_logged_and_skipped(caplog):
    """기타 어떤 현으로도 표현 못 하는 음(MIDI 범위 밖)은 건너뛰되, 경고 로그를 남겨야 한다."""
    # 30: 모든 현에서 프렛이 음수(범위 밖) / 60: 정상
    measures_data = [
        MeasureData(
            numerator=4,
            denominator=4,
            key_fifths=0,
            events=[NoteEvent(midi=30, ql=1.0, tied=False), NoteEvent(midi=60, ql=1.0, tied=False)],
        )
    ]

    with caplog.at_level("WARNING", logger="app.pipeline.musicxml_to_gp"):
        song = _build_song(measures_data)

    track = song.tracks[0]
    actual = [
        (note.string, note.value)
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]
    assert actual == [(2, 1)]  # 30은 스킵되고 60(string2 fret1)만 남음

    assert len(caplog.records) == 1
    assert "30" in caplog.records[0].message


def test_tab_hints_ignored_when_string_number_invalid(tmp_path):
    """힌트의 현 번호가 트랙에 존재하지 않으면 전체를 무시하고 휴리스틱으로 폴백해야 한다."""
    out = str(tmp_path / "tab_invalid_string.gp5")
    invalid_hints = [(7, 5), (3, 7), (3, 9), (3, 10), (3, 12), (3, 14), (3, 16), (3, 17)]
    musicxml_to_gp5(FIXTURE, out, tab_hints=invalid_hints)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    actual = [
        (note.string, note.value)
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert actual == [(5, 3), (4, 0), (4, 2), (4, 3), (3, 0), (3, 2), (2, 0), (2, 1)]


def test_parse_failure_has_specific_message(tmp_path):
    """MusicXML 파싱 자체가 실패하면 그 사실이 메시지에 드러나야 한다."""
    out = str(tmp_path / "out.gp5")

    with pytest.raises(GpConvertError, match="MusicXML 파싱 실패"):
        musicxml_to_gp5("/nonexistent/path/bad.musicxml", out)


def test_collect_notes_failure_has_specific_message(tmp_path):
    """음표 수집 단계 실패는 파싱 실패와 다른 메시지여야 한다."""
    out = str(tmp_path / "out.gp5")

    with patch("app.pipeline.musicxml_to_gp._collect_notes", side_effect=RuntimeError("boom")):
        with pytest.raises(GpConvertError, match="음표 추출 실패"):
            musicxml_to_gp5(FIXTURE, out)


def test_write_failure_has_specific_message(tmp_path):
    """GP5 파일 쓰기 실패는 앞 두 단계와 다른 메시지여야 한다."""
    out = str(tmp_path / "out.gp5")

    with patch("app.pipeline.musicxml_to_gp.guitarpro.write", side_effect=RuntimeError("boom")):
        with pytest.raises(GpConvertError, match="GP5 쓰기 실패"):
            musicxml_to_gp5(FIXTURE, out)


# 실제 박자(3/4 + 3/4)로 이루어진 합성 MusicXML.
# 두 번째 마디는 <attributes>가 없어 첫 마디 박자를 그대로 이어받는다(carry-forward).
# 기존 버그(4/4 고정 청크)에서는 마디1의 음표 3개 + 마디2의 음표 1개가 한 마디로
# 묶여버린다(quarterLength 합 4.0에서 끊기 때문). 올바른 구현은 실제 마디 경계대로
# [C,D,E] / [F,G,A]로 나뉘어야 한다.
_METER_CHANGE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>3</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
    <measure number="2">
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>A</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_measure_grouping_follows_real_measure_boundaries(tmp_path):
    """마디 그룹화는 4/4 고정 청크가 아니라 실제 마디 경계를 따라야 한다."""
    xml_path = tmp_path / "meter.musicxml"
    xml_path.write_text(_METER_CHANGE_XML, encoding="utf-8")
    out = str(tmp_path / "meter.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]

    assert len(track.measures) == 2, f"마디 2개여야 하는데 {len(track.measures)}개"

    string_val = {s.number: s.value for s in track.strings}
    per_measure_midi = [
        [string_val[note.string] + note.value for voice in measure.voices for beat in voice.beats for note in beat.notes]
        for measure in track.measures
    ]
    # 기타 표기 관행(1옥타브 낮게 소리남)으로 적힌 C4D4E4/F4G4A4(60,62,64/65,67,69)는
    # 실제로 C3D3E3/F3G3A3(48,50,52/53,55,57)로 소리난다.
    assert per_measure_midi == [[48, 50, 52], [53, 55, 57]], (
        f"마디 경계가 밀림: {per_measure_midi}"
    )

    # 두 번째 마디도 (carry-forward로) 3/4 박자를 유지해야 한다.
    assert track.measures[0].timeSignature.numerator == 3
    assert track.measures[1].timeSignature.numerator == 3


_KEY_SIGNATURE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <key><fifths>2</fifths></key>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_key_signature_propagated_to_gp5(tmp_path):
    """MusicXML의 조표(fifths)가 GP5 마디 헤더에 반영돼야 한다."""
    xml_path = tmp_path / "keysig.musicxml"
    xml_path.write_text(_KEY_SIGNATURE_XML, encoding="utf-8")
    out = str(tmp_path / "keysig.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]

    assert track.measures[0].keySignature == guitarpro.KeySignature.DMajor


_TIE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>2</duration><type>half</type>
        <tie type="start"/>
        <notations><tied type="start"/></notations>
      </note>
      <note>
        <pitch><step>C</step><octave>4</octave></pitch>
        <duration>2</duration><type>half</type>
        <tie type="stop"/>
        <notations><tied type="stop"/></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_tied_note_marked_as_tie_type_not_normal(tmp_path):
    """이음줄로 이어지는 두 번째 음은 NoteType.tie로 표시돼야 한다(새 발음이 아님)."""
    xml_path = tmp_path / "tie.musicxml"
    xml_path.write_text(_TIE_XML, encoding="utf-8")
    out = str(tmp_path / "tie.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    notes = [
        note
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert len(notes) == 2
    assert notes[0].type == guitarpro.NoteType.normal, "이음줄 시작 음은 새 발음이어야 함"
    assert notes[1].type == guitarpro.NoteType.tie, "이음줄로 이어지는 음은 tie 타입이어야 함"


_WRITTEN_C5_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_standard_notation_pitch_shifted_down_one_octave(tmp_path):
    """클래식/핑거스타일 기타 표준악보는 적힌 음보다 1옥타브 낮게 소리난다.

    적힌 C5(MIDI 72)는 실제로는 C4(MIDI 60)로 소리나야 한다. 탭보표가 아닌
    표준 5선 악보를 OMR로 읽은 경우에만 적용되는 관행이며, 탭 힌트가 있을
    때는 이미 정확한 (현,프렛)이라 이 보정과 무관하다.
    """
    xml_path = tmp_path / "written_c5.musicxml"
    xml_path.write_text(_WRITTEN_C5_XML, encoding="utf-8")
    out = str(tmp_path / "written_c5.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}
    actual_midi = [
        string_val[note.string] + note.value
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert actual_midi == [60], f"적힌 C5(72)가 1옥타브 낮은 C4(60)로 소리나야 하는데: {actual_midi}"
