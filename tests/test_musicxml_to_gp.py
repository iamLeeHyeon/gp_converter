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
    _assign_chord_strings,
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
            voices=[[NoteEvent(pitches=[30], ql=1.0, tied=False), NoteEvent(pitches=[60], ql=1.0, tied=False)]],
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


_REST_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
      <note><rest/><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_rest_represented_as_silent_beat(tmp_path):
    """쉼표는 그냥 건너뛰지 말고 소리 없는(rest) 비트로 들어가야 한다.

    버그였던 동작: music21 Stream.notes는 Rest를 제외하므로 쉼표가 통째로
    빠져, 그 뒤 음표들이 마디 박자 총합을 못 채워 GP5가 깨졌다(스샷에서
    쉼표·음표 글리프가 겹쳐 보이는 증상).
    """
    xml_path = tmp_path / "rest.musicxml"
    xml_path.write_text(_REST_XML, encoding="utf-8")
    out = str(tmp_path / "rest.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}

    beats = [
        beat
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
    ]

    assert len(beats) == 4, f"쉼표 1개 + 음표 3개 = 비트 4개여야 하는데 {len(beats)}개"
    assert beats[0].status == guitarpro.models.BeatStatus.rest
    assert beats[0].notes == []

    rest_pitches = [string_val[n.string] + n.value for b in beats[1:] for n in b.notes]
    assert rest_pitches == [48, 50, 52]  # C4 D4 E4(적힌 음) -1옥타브 = C3 D3 E3


_MULTI_VOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><voice>1</voice><type>quarter</type></note>
      <backup><duration>4</duration></backup>
      <note><pitch><step>G</step><octave>4</octave></pitch><duration>4</duration><voice>2</voice><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_second_voice_preserved_as_separate_gp5_voice(tmp_path):
    """여러 보이스(다성)면 버리지 말고 GP5의 두 번째 보이스에 그대로 넣는다.

    이전 버그였던 동작: recurse()가 보이스 구분 없이 한 줄로 펴버려서 마디당
    박자 총합이 배가 됨 → 보이스1만 쓰고 보이스2는 버리는 것으로 1차 수정.
    근데 실제 곡에서 보이스2가 동시에 울리는 실제 음(쉼표 옆 지속음)이라 그냥
    버리면 음이 통째로 빠진다. GP5 Measure가 보이스를 2개까지 지원하므로
    보이스2도 그대로 살려서 둘째 보이스에 넣어야 한다.
    """
    xml_path = tmp_path / "multivoice.musicxml"
    xml_path.write_text(_MULTI_VOICE_XML, encoding="utf-8")
    out = str(tmp_path / "multivoice.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}
    measure = track.measures[0]

    voice0_midi = [
        string_val[n.string] + n.value for b in measure.voices[0].beats for n in b.notes
    ]
    voice1_midi = [
        string_val[n.string] + n.value for b in measure.voices[1].beats for n in b.notes
    ]

    # voice1(C,D,E,F → -1옥타브 후 48,50,52,53)
    assert voice0_midi == [48, 50, 52, 53]
    # voice2(G → -1옥타브 후 55)도 버려지지 않고 살아있어야 함
    assert voice1_midi == [55], f"voice2(동시에 울리는 음)가 빠짐: {voice1_midi}"


_DOTTED_DURATIONS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>8</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>24</duration><type>half</type><dot/></note>
      <note><pitch><step>D</step><octave>5</octave></pitch><duration>6</duration><type>eighth</type><dot/></note>
      <note><pitch><step>E</step><octave>5</octave></pitch><duration>2</duration><type>16th</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_dotted_durations_preserve_real_length(tmp_path):
    """점음표 길이가 실제보다 2배로 늘어나면 안 된다.

    버그였던 동작: _DOTTED_QL_TO_GPV가 한 단계 더 큰 음표 모양의 GP value를
    써서(예: 점8분음표 0.75ql인데 점4분음표 모양 value=4로 인코딩), GP5에
    실제로 쓰이는 길이가 1.5ql(정확히 2배)이 됐다. 점온음표(3.0)·점8분음표
    (0.75)·16분음표(0.25) 합이 정확히 4/4 한 마디(4.0ql)를 채워야 한다.
    """
    xml_path = tmp_path / "dotted.musicxml"
    xml_path.write_text(_DOTTED_DURATIONS_XML, encoding="utf-8")
    out = str(tmp_path / "dotted.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]

    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]
    actual_qls = [beat.duration.time / guitarpro.models.Duration.quarterTime for beat in beats]

    assert actual_qls == [3.0, 0.75, 0.25], f"점음표 길이가 틀어짐: {actual_qls}"
    assert sum(actual_qls) == 4.0, f"마디 박자 총합이 4.0이어야 하는데 {sum(actual_qls)}"


_PHANTOM_LEADING_REST_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>2</divisions>
        <time><beats>4</beats><beat-type>4</beat-type></time>
      </attributes>
      <note><rest/><duration>1</duration><type>eighth</type></note>
      <note><pitch><step>E</step><octave>6</octave></pitch><duration>8</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_phantom_leading_rest_dropped_when_it_overflows_measure(tmp_path, caplog):
    """Audiveris가 실제로 없는 선행 쉼표를 만들어내 마디가 넘치면 제거해야 한다.

    실측(Flower of the Field, 마디27): 원본 페이지에는 온음표 하나(이전 마디에서
    이음줄로 이어짐)만 있는데, Audiveris가 그 앞에 존재하지 않는 8분쉼표를
    만들어내 마디 박자합이 4.5(>4.0)가 됐다. 빼면 정확히 4.0이 되는 선행
    쉼표만 좁게 제거한다(실제로 있는 쉼표를 잘못 지우면 안 되므로
    test_rest_represented_as_silent_beat가 그 회귀를 막아준다).
    """
    xml_path = tmp_path / "phantom_rest.musicxml"
    xml_path.write_text(_PHANTOM_LEADING_REST_XML, encoding="utf-8")
    out = str(tmp_path / "phantom_rest.gp5")

    with caplog.at_level("WARNING", logger="app.pipeline.musicxml_to_gp"):
        musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}

    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]
    assert len(beats) == 1, f"유령 쉼표가 제거 안 됨: {len(beats)}개 비트"
    assert beats[0].status == guitarpro.models.BeatStatus.normal
    midi = string_val[beats[0].notes[0].string] + beats[0].notes[0].value
    assert midi == 76  # E6(88) -1옥타브 = 76
    assert beats[0].duration.time / guitarpro.models.Duration.quarterTime == 4.0

    assert len(caplog.records) == 1
    assert "유령" in caplog.records[0].message or "초과" in caplog.records[0].message


def test_assign_chord_strings_no_conflict():
    """충돌 없는 화음은 각 음마다 가장 낮은 프렛의 현을 받아야 한다."""
    from app.pipeline.musicxml_to_gp import _STANDARD_STRINGS

    # E5(65) C5(60) A4(57) F4(53) — MIDI 내림차순
    result = _assign_chord_strings([65, 60, 57, 53], _STANDARD_STRINGS)

    assert result == [(1, 1), (2, 1), (3, 2), (4, 3)]


def test_assign_chord_strings_falls_back_when_first_choice_taken():
    """1순위 현이 이미 다른 음에 쓰였으면 그 다음 후보 현으로 넘어가야 한다.

    MIDI 65(F4)와 64(E4 옥타브 위... 실제로는 두 음 다 string1을 1순위로
    원하는 상황): 65는 string1 fret1을, 64는 string1 fret0을 1순위로
    원한다. 65가 먼저(내림차순) string1을 차지하면 64는 string2 fret5로
    밀려나야 한다.
    """
    from app.pipeline.musicxml_to_gp import _STANDARD_STRINGS

    result = _assign_chord_strings([65, 64], _STANDARD_STRINGS)

    assert result == [(1, 1), (2, 5)]


def test_assign_chord_strings_skips_unplaceable_note_only():
    """화음 안 한 음이 어떤 현으로도 표현 못 하면 그 음만 None, 나머지는 살아야 한다."""
    from app.pipeline.musicxml_to_gp import _STANDARD_STRINGS

    # 100: 모든 현에서 프렛이 24 초과(범위 밖) / 64: 정상(string1 fret0)
    result = _assign_chord_strings([100, 64], _STANDARD_STRINGS)

    assert result == [None, (1, 0)]


_CHORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>A</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>F</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_chord_all_notes_placed_on_distinct_strings(tmp_path):
    """화음의 모든 음이 한 비트 안에, 서로 다른 현에 살아있어야 한다(최고음만 X)."""
    xml_path = tmp_path / "chord.musicxml"
    xml_path.write_text(_CHORD_XML, encoding="utf-8")
    out = str(tmp_path / "chord.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}

    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]
    assert len(beats) == 1, f"화음은 비트 1개여야 하는데 {len(beats)}개"

    notes = beats[0].notes
    assert len(notes) == 4, f"화음 음 4개가 다 살아있어야 하는데 {len(notes)}개"

    strings_used = [n.string for n in notes]
    assert len(strings_used) == len(set(strings_used)), "같은 현을 두 음이 동시에 씀"

    # 적힌 E5,C5,A4,F4(76,72,69,65) -1옥타브 = 64,60,57,53
    actual_midi = sorted(string_val[n.string] + n.value for n in notes)
    assert actual_midi == [53, 57, 60, 64]


_CHORD_PLUS_SINGLE_NOTES_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
      </note>
      <note>
        <chord/>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
      </note>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_tab_hints_apply_only_to_single_note_events_when_chord_present(tmp_path):
    """화음이 섞인 마디에서 tab_hints 개수는 단일음 이벤트 개수만 따져야 한다.

    이 마디는 화음(half, 2음) 1개 + 단일음(quarter) 2개다. tab_hints를
    단일음 2개에 맞춰 주면(화음은 세지 않음) 화음은 휴리스틱으로, 단일음
    2개는 힌트로 그대로 들어가야 한다.
    """
    xml_path = tmp_path / "chord_plus_single.musicxml"
    xml_path.write_text(_CHORD_PLUS_SINGLE_NOTES_XML, encoding="utf-8")
    out = str(tmp_path / "chord_plus_single.gp5")

    # 단일음 2개(C4,D4)에 대한 가짜 힌트 — 휴리스틱이면 다른 값이 나오게 일부러 6번줄로
    fake_hints = [(6, 20), (6, 21)]
    musicxml_to_gp5(str(xml_path), out, tab_hints=fake_hints)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]

    assert len(beats) == 3  # 화음 1비트 + 단일음 2비트
    chord_beat, single1, single2 = beats

    assert len(chord_beat.notes) == 2  # 화음은 힌트 무시, 2음 다 살아있음
    assert (single1.notes[0].string, single1.notes[0].value) == (6, 20)
    assert (single2.notes[0].string, single2.notes[0].value) == (6, 21)


_ALL_UNPLACEABLE_CHORD_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>C</step><octave>9</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>E</step><octave>9</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
      <note>
        <chord/>
        <pitch><step>G</step><octave>9</octave></pitch>
        <duration>4</duration><type>whole</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_chord_all_notes_unplaceable_becomes_rest_beat(tmp_path):
    """화음의 모든 음이 범위 밖이면 빈 normal 비트가 아니라 rest 비트가 돼야 한다.

    적힌 C9,E9,G9(120,124,127) -1옥타브 = 108,112,115 — 표준 튜닝 6현 중
    어디에도 0~24 프렛으로 못 들어간다(1번줄 최대 MIDI 64+24=88). 모든 음이
    None으로 배정되면 beat.notes는 비어야 하지만, status는 normal이 아니라
    rest여야 한다(빈 normal 비트는 의미상 잘못된 상태).
    """
    xml_path = tmp_path / "unplaceable_chord.musicxml"
    xml_path.write_text(_ALL_UNPLACEABLE_CHORD_XML, encoding="utf-8")
    out = str(tmp_path / "unplaceable_chord.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]

    assert len(beats) == 1, f"화음은 비트 1개여야 하는데 {len(beats)}개"
    assert beats[0].status == guitarpro.BeatStatus.rest
    assert len(beats[0].notes) == 0
