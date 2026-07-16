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

_DYNAMICS_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
      <direction placement="above">
        <direction-type><dynamics><mf/></dynamics></direction-type>
      </direction>
      <note><pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <direction placement="above">
        <direction-type><dynamics><p/></dynamics></direction-type>
      </direction>
      <note><pitch><step>E</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


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


def test_dynamics_set_note_velocity_with_carry_forward(tmp_path):
    """다이나믹 기호가 이후 음표의 velocity를 바꾸고 carry-forward돼야 한다.

    mf(velocity=79) 이후 C5·D5는 79, p(velocity=47) 이후 E5·F5는 47.
    """
    xml_path = tmp_path / "dynamics.musicxml"
    xml_path.write_text(_DYNAMICS_XML, encoding="utf-8")
    out = str(tmp_path / "dynamics.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 4
    assert beats[0].notes[0].velocity == 79, "C5: mf=79"
    assert beats[1].notes[0].velocity == 79, "D5: mf carry-forward=79"
    assert beats[2].notes[0].velocity == 47, "E5: p=47"
    assert beats[3].notes[0].velocity == 47, "F5: p carry-forward=47"


_HAIRPIN_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <direction placement="below"><direction-type><dynamics><mp/></dynamics></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <direction placement="below"><direction-type><wedge type="crescendo" number="1"/></direction-type></direction>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <direction placement="below"><direction-type><wedge type="stop" number="1"/></direction-type></direction>
      <direction placement="below"><direction-type><dynamics><f/></dynamics></direction-type></direction>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_crescendo_hairpin_interpolates_velocity_toward_target_dynamic(tmp_path):
    """크레센도 구간의 음표들은 시작(mp=63)에서 도착 다이내믹(f=95)까지
    선형보간된 velocity를 가져야 한다 — 이전엔 하이핀이 완전히 무시돼
    도착 다이내믹이 찍히는 순간까지 velocity가 그냥 flat했다."""
    xml_path = tmp_path / "hairpin.musicxml"
    xml_path.write_text(_HAIRPIN_XML, encoding="utf-8")
    out = str(tmp_path / "hairpin.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 4
    assert beats[0].notes[0].velocity == 63, "C4: mp=63 (하이핀 이전)"
    assert beats[1].notes[0].velocity == 63, "D4: 하이핀 시작 지점 = 시작값"
    assert beats[2].notes[0].velocity == 95, "E4: 하이핀 끝 지점 = 도착값(f=95)"
    assert beats[3].notes[0].velocity == 95, "F4: f=95 (도착 다이내믹 그대로)"


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
            voices=[[NoteEvent(pitches=[30], ql=1.0, tied=[False]), NoteEvent(pitches=[60], ql=1.0, tied=[False])]],
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


_TEMPO_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
      <direction placement="above">
        <direction-type>
          <metronome><beat-unit>quarter</beat-unit><per-minute>140</per-minute></metronome>
        </direction-type>
        <sound tempo="140"/>
      </direction>
      <note><pitch><step>C</step><octave>4</octave></pitch>
        <duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_tempo_marking_propagated_to_gp5(tmp_path):
    """MusicXML의 템포 마킹(BPM)이 GP5 Song.tempo에 반영돼야 한다.

    지금까지는 이걸 안 읽어서 변환된 모든 곡이 무조건 기본값 120bpm으로
    재생됐다 — 원곡 템포와 무관하게.
    """
    xml_path = tmp_path / "tempo.musicxml"
    xml_path.write_text(_TEMPO_XML, encoding="utf-8")
    out = str(tmp_path / "tempo.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert song.tempo == 140


def test_tempo_defaults_to_120_when_no_marking(tmp_path):
    """템포 마킹이 없는 MusicXML은 기존처럼 기본값 120을 유지해야 한다."""
    out = str(tmp_path / "no_tempo.gp5")
    musicxml_to_gp5(FIXTURE, out)

    song = guitarpro.parse(out)
    assert song.tempo == 120


_METADATA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <work><work-title>My Song</work-title></work>
  <identification><creator type="composer">Jane Doe</creator></identification>
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_title_and_composer_propagated_to_gp5(tmp_path):
    """MusicXML의 곡 제목/작곡가가 GP5 title/artist에 반영돼야 한다."""
    xml_path = tmp_path / "metadata.musicxml"
    xml_path.write_text(_METADATA_XML, encoding="utf-8")
    out = str(tmp_path / "metadata.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert song.title == "My Song"
    assert song.artist == "Jane Doe"


def test_title_defaults_to_empty_when_no_metadata(tmp_path):
    """메타데이터 없는 MusicXML은 기존처럼 빈 제목/아티스트를 유지해야 한다."""
    out = str(tmp_path / "no_metadata.gp5")
    musicxml_to_gp5(FIXTURE, out)

    song = guitarpro.parse(out)
    assert song.title == ""
    assert song.artist == ""


_MIDI_INSTRUMENT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Distortion Guitar</part-name>
    <score-instrument id="P1-I1"><instrument-name>Distortion Guitar</instrument-name></score-instrument>
    <midi-instrument id="P1-I1"><midi-channel>1</midi-channel><midi-program>31</midi-program></midi-instrument>
  </score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_midi_program_propagated_to_gp5_track_instrument(tmp_path):
    """MusicXML의 <midi-program>이 GP5 트랙 악기 음색에 반영돼야 한다.

    MusicXML은 1-indexed(31=Distortion Guitar), music21/PyGuitarPro는
    0-indexed(30)라 music21이 이미 -1 변환해준 값을 그대로 쓰면 된다.
    """
    xml_path = tmp_path / "midi_instrument.musicxml"
    xml_path.write_text(_MIDI_INSTRUMENT_XML, encoding="utf-8")
    out = str(tmp_path / "midi_instrument.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert song.tracks[0].channel.instrument == 30


def test_midi_program_defaults_when_not_specified(tmp_path):
    """악기 정보 없는 MusicXML은 기존 기본값(어쿠스틱 기타, 25)을 유지해야 한다."""
    out = str(tmp_path / "no_instrument.gp5")
    musicxml_to_gp5(FIXTURE, out)

    song = guitarpro.parse(out)
    assert song.tracks[0].channel.instrument == 25


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


_MULTI_VOICE_THEN_SINGLE_VOICE_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
    <measure number="2">
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><voice>1</voice><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_second_voice_gets_full_rest_when_unused_in_later_measure(tmp_path):
    """마디1에서 실제로 쓰인 2번째 보이스가 마디2에서 안 쓰이면, 완전히 빈 배열이
    아니라 그 마디를 채우는 쉼표 비트 1개가 들어가야 한다.

    실사례로 재현된 버그: 이렇게 완전히 빈 voices[1].beats == []가 "한 번이라도
    그 보이스가 쓰인 뒤" 나오면 alphaTab이 로드 시
    "Cannot read properties of undefined (reading 'beats')"로 죽는다(자체 검증
    완료). PyGuitarPro/GP5 파일 자체는 문제 없이 파싱되므로 이 버그는 자동화
    테스트로 못 잡고 실제 alphaTab 로딩에서만 드러난다 — 그래서 "완전히 빈 보이스
    없음"을 우리 쪽에서 직접 보장해야 한다.
    """
    xml_path = tmp_path / "multivoice_then_single.musicxml"
    xml_path.write_text(_MULTI_VOICE_THEN_SINGLE_VOICE_XML, encoding="utf-8")
    out = str(tmp_path / "multivoice_then_single.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    measure2 = song.tracks[0].measures[1]

    assert len(measure2.voices[1].beats) >= 1, "2번째 보이스가 완전히 빈 배열로 남음"
    beat = measure2.voices[1].beats[0]
    assert beat.status == guitarpro.BeatStatus.rest
    assert beat.notes == []


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


_CHORD_MIXED_TIE_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
        <tie type="start"/>
        <notations><tied type="start"/></notations>
      </note>
      <note>
        <chord/>
        <pitch><step>B</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
        <tie type="stop"/>
        <notations><tied type="stop"/></notations>
      </note>
      <note>
        <chord/>
        <pitch><step>B</step><octave>5</octave></pitch>
        <duration>2</duration><type>half</type>
        <tie type="start"/>
        <notations><tied type="start"/></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_chord_tie_tracked_per_pitch_not_shared_across_whole_chord(tmp_path):
    """화음 안에서 음마다 이음줄 상태가 다르면, 음별로 정확히 따로 표시돼야 한다.

    2번째 비트 화음(G5+B5): G5는 1번째 비트에서 이어지는 음(tie stop, 안 쳐야
    함)이고 B5는 거기서 새로 시작하는 음(tie start, 처음 치는 음)이다.
    music21의 Chord.tie는 구성음 중 하나의 tie만 대표로 골라 화음 전체에
    적용하므로(실측: Flower of the Field 36마디), 이를 그대로 따르면 새로
    쳐야 할 B5까지 이어지는 음으로 잘못 표시된다. 음별로 따로 추적해야 한다.
    """
    xml_path = tmp_path / "chord_mixed_tie.musicxml"
    xml_path.write_text(_CHORD_MIXED_TIE_XML, encoding="utf-8")
    out = str(tmp_path / "chord_mixed_tie.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}
    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]

    assert len(beats) == 2, f"화음 2개(반음표씩)여야 하는데 {len(beats)}개"
    second_beat = beats[1]
    assert len(second_beat.notes) == 2

    by_midi = {string_val[n.string] + n.value: n for n in second_beat.notes}
    # 적힌 G5(79),B5(83) -1옥타브 = 67,71
    assert set(by_midi.keys()) == {67, 71}
    assert by_midi[67].type == guitarpro.NoteType.tie, "G5는 이어지는 음(tie stop)이어야 함"
    assert by_midi[71].type == guitarpro.NoteType.normal, "B5는 새로 치는 음(tie start)이어야 함"


_CHORD_TIE_STRING_CARRYOVER_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <tie type="start"/>
      </note>
      <note>
        <chord/>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <tie type="start"/>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <tie type="stop"/>
        <tie type="start"/>
      </note>
      <note>
        <chord/>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <tie type="stop"/>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <tie type="stop"/>
      </note>
      <note>
        <chord/>
        <pitch><step>B</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <tie type="start"/>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_tied_chord_note_keeps_same_string_across_beats(tmp_path):
    """화음 안 이어지는 음은 직전 비트와 같은 줄을 유지해야 한다(실측 36마디 버그).

    1·2비트: G5+C5 화음(둘 다 이어짐). 3비트: G5(이어짐)+B5(새 음, G5와 같은
    화음에 끼어들며 줄을 다툼). G5가 1~2비트에서 쓰던 줄을 그대로 못 지키면,
    GP5 포맷은 이어지는 음의 프렛 값을 직전 비트의 같은 줄 값으로 덮어써서
    엉뚱한 음높이가 된다(여기서는 C5 자리를 베껴 깨진다). 그래서 G5는 3비트
    에서도 1~2비트와 같은 줄에 있어야 하고, B5는 남은 줄에 새로 배정돼야
    한다.
    """
    xml_path = tmp_path / "chord_tie_carryover.musicxml"
    xml_path.write_text(_CHORD_TIE_STRING_CARRYOVER_XML, encoding="utf-8")
    out = str(tmp_path / "chord_tie_carryover.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}
    beats = [beat for voice in track.measures[0].voices for beat in voice.beats]
    assert len(beats) == 3

    def _string_of(beat, midi):
        for n in beat.notes:
            if string_val[n.string] + n.value == midi:
                return n.string
        raise AssertionError(f"비트에 MIDI {midi} 음이 없음: {beat.notes}")

    # 적힌 G5(79) -1옥타브 = 67
    g5_string_beat1 = _string_of(beats[0], 67)
    g5_string_beat2 = _string_of(beats[1], 67)
    g5_string_beat3 = _string_of(beats[2], 67)
    assert g5_string_beat1 == g5_string_beat2 == g5_string_beat3, (
        "이어지는 G5가 비트마다 줄이 바뀌면 안 됨"
    )

    # 적힌 B5(83) -1옥타브 = 71, G5와 다른 줄이어야 함
    b5_string_beat3 = _string_of(beats[2], 71)
    assert b5_string_beat3 != g5_string_beat3


def test_note_event_new_fields_have_correct_defaults():
    """NoteEvent의 새 필드가 올바른 기본값을 가져야 한다."""
    ev = NoteEvent(pitches=[60], ql=1.0, tied=[False])
    assert ev.tuplet is None
    assert ev.velocity is None
    assert ev.hammer is False
    assert ev.articulations == []
    assert ev.grace is None


_TRIPLET_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>6</divisions>
        <time><beats>2</beats><beat-type>4</beat-type></time>
      </attributes>
      <note>
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>2</duration><type>eighth</type>
        <time-modification>
          <actual-notes>3</actual-notes>
          <normal-notes>2</normal-notes>
        </time-modification>
        <notations><tuplet type="start" number="1" placement="above"/></notations>
      </note>
      <note>
        <pitch><step>D</step><octave>5</octave></pitch>
        <duration>2</duration><type>eighth</type>
        <time-modification>
          <actual-notes>3</actual-notes>
          <normal-notes>2</normal-notes>
        </time-modification>
      </note>
      <note>
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>2</duration><type>eighth</type>
        <time-modification>
          <actual-notes>3</actual-notes>
          <normal-notes>2</normal-notes>
        </time-modification>
        <notations><tuplet type="stop" number="1"/></notations>
      </note>
      <note><rest/><duration>6</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_triplet_eighth_notes_have_tuplet_duration(tmp_path):
    """셋잇단 8분음표 3개가 GP5에서 Tuplet(enters=3, times=2)으로 표시돼야 한다."""
    xml_path = tmp_path / "triplet.musicxml"
    xml_path.write_text(_TRIPLET_XML, encoding="utf-8")
    out = str(tmp_path / "triplet.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 3, f"셋잇단 3음이 있어야 하는데 {len(beats)}개"
    for i, beat in enumerate(beats):
        assert beat.duration.tuplet.enters == 3, f"beat {i}: enters != 3"
        assert beat.duration.tuplet.times == 2, f"beat {i}: times != 2"


_ARTICULATION_XML = """<?xml version="1.0" encoding="UTF-8"?>
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
        <pitch><step>C</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><staccato/></articulations></notations>
      </note>
      <note>
        <pitch><step>D</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><accent/></articulations></notations>
      </note>
      <note>
        <pitch><step>E</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><strong-accent/></articulations></notations>
      </note>
      <note>
        <pitch><step>F</step><octave>5</octave></pitch>
        <duration>1</duration><type>quarter</type>
        <notations><articulations><tenuto/></articulations></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_articulations_applied_to_note_effect(tmp_path):
    """스타카토/악센트/강악센트/테누토가 각각 NoteEffect에 정확히 매핑돼야 한다."""
    xml_path = tmp_path / "articulation.musicxml"
    xml_path.write_text(_ARTICULATION_XML, encoding="utf-8")
    out = str(tmp_path / "articulation.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 4
    assert beats[0].notes[0].effect.staccato is True, "C5: staccato"
    assert beats[1].notes[0].effect.accentuatedNote is True, "D5: accent"
    assert beats[2].notes[0].effect.heavyAccentuatedNote is True, "E5: strong-accent"
    assert beats[3].notes[0].effect.letRing is True, "F5: tenuto"


_GRACE_NOTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list>
    <score-part id="P1"><part-name>Guitar</part-name></score-part>
  </part-list>
  <part id="P1">
    <measure number="1">
      <attributes>
        <divisions>1</divisions>
        <time><beats>2</beats><beat-type>2</beat-type></time>
      </attributes>
      <!-- 오름 꾸밈음: F5(적힌) → G5(적힌). 소리는 F4→G4(각각 -1옥타브). F4<G4이므로 hammer -->
      <note>
        <grace slash="yes"/>
        <pitch><step>F</step><octave>5</octave></pitch>
        <type>eighth</type>
        <stem>up</stem>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>half</type>
      </note>
      <!-- 내림 꾸밈음: A5(적힌) → G5(적힌). 소리는 A4→G4. A4>G4이므로 slide -->
      <note>
        <grace slash="yes"/>
        <pitch><step>A</step><octave>5</octave></pitch>
        <type>eighth</type>
        <stem>up</stem>
      </note>
      <note>
        <pitch><step>G</step><octave>5</octave></pitch>
        <duration>1</duration><type>half</type>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_grace_notes_set_hammer_or_slide_transition(tmp_path):
    """오름 꾸밈음은 hammer, 내림 꾸밈음은 slide transition이어야 한다.

    적힌 음에 -1옥타브 보정: F5→F4(MIDI65), G5→G4(MIDI67), A5→A4(MIDI69).
    F4(65) < G4(67) → hammer. A4(69) > G4(67) → slide.
    """
    xml_path = tmp_path / "grace.musicxml"
    xml_path.write_text(_GRACE_NOTE_XML, encoding="utf-8")
    out = str(tmp_path / "grace.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 2

    grace0 = beats[0].notes[0].effect.grace
    assert grace0 is not None, "첫 번째 음(G4)에 꾸밈음이 있어야 함"
    assert grace0.transition == guitarpro.GraceEffectTransition.hammer, "오름→hammer"

    grace1 = beats[1].notes[0].effect.grace
    assert grace1 is not None, "두 번째 음(G4)에 꾸밈음이 있어야 함"
    assert grace1.transition == guitarpro.GraceEffectTransition.slide, "내림→slide"


_SLIDE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <notations><slide type="start" number="1"/></notations>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <notations><slide type="stop" number="1"/></notations>
      </note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_slide_marks_origin_note_not_destination(tmp_path):
    """표준악보의 <slide>가 GP5에 반영돼야 한다 — 시작 음표에만 slides가
    붙고 도착 음표에는 안 붙어야 한다(지금까지는 표준악보 경로에 슬라이드
    파싱 자체가 없어서 조용히 사라졌었다)."""
    xml_path = tmp_path / "slide.musicxml"
    xml_path.write_text(_SLIDE_XML, encoding="utf-8")
    out = str(tmp_path / "slide.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 3

    origin, dest, other = beats[0].notes[0], beats[1].notes[0], beats[2].notes[0]
    assert origin.effect.slides == [guitarpro.SlideType.shiftSlideTo]
    assert dest.effect.slides == []
    assert other.effect.slides == []


_REPEAT_VOLTA_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <barline location="left"><bar-style>heavy-light</bar-style><repeat direction="forward"/></barline>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <barline location="left"><ending number="1" type="start"/></barline>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
      <barline location="right"><bar-style>light-heavy</bar-style><ending number="1" type="stop"/><repeat direction="backward" times="3"/></barline>
    </measure>
    <measure number="3">
      <barline location="left"><ending number="2" type="start"/></barline>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
      <barline location="right"><ending number="2" type="discontinue"/></barline>
    </measure>
  </part>
</score-partwise>"""


def test_repeat_and_volta_mapped_to_gp5_measure_headers(tmp_path):
    """반복표 시작/닫힘(횟수)과 1·2번 엔딩이 GP5 마디 헤더에 반영돼야 한다."""
    xml_path = tmp_path / "repeat_volta.musicxml"
    xml_path.write_text(_REPEAT_VOLTA_XML, encoding="utf-8")
    out = str(tmp_path / "repeat_volta.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    measures = song.tracks[0].measures

    assert measures[0].isRepeatOpen is True
    assert measures[1].repeatClose == 2, "MusicXML times=3 → GP5 repeatClose=2(3-1)"
    assert measures[1].header.repeatAlternative == 0b01, "1번 엔딩 → bit0"
    assert measures[2].header.repeatAlternative == 0b10, "2번 엔딩 → bit1"


_DC_AL_FINE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <direction placement="above"><direction-type><coda/></direction-type></direction>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
    <measure number="2">
      <direction placement="above"><direction-type><words>D.C. al Fine</words></direction-type></direction>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_coda_and_da_capo_al_fine_mapped_to_gp5_directions(tmp_path):
    """<coda/> 심볼과 "D.C. al Fine" 텍스트가 각각 GP5 direction/fromDirection에
    반영돼야 한다 — 이전엔 이런 곡 구조 지시가 전부 무시돼 사라졌었다."""
    xml_path = tmp_path / "dc_al_fine.musicxml"
    xml_path.write_text(_DC_AL_FINE_XML, encoding="utf-8")
    out = str(tmp_path / "dc_al_fine.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    measures = song.tracks[0].measures

    assert measures[0].header.direction == guitarpro.DirectionSign('Coda')
    assert measures[1].header.fromDirection == guitarpro.DirectionSign('Da Capo al Fine')


_CHORD_SYMBOL_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <harmony><root><root-step>A</root-step></root><kind>minor-seventh</kind></harmony>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_chord_symbol_name_attached_to_first_beat(tmp_path):
    """<harmony> 코드 심볼 이름이 그 마디 첫 비트에 붙어야 한다(다이어그램 없이 이름만)."""
    xml_path = tmp_path / "chordsym.musicxml"
    xml_path.write_text(_CHORD_SYMBOL_XML, encoding="utf-8")
    out = str(tmp_path / "chordsym.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    assert beat.effect.chord is not None
    assert beat.effect.chord.name == "Am7"


_LYRICS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>begin</syllabic><text>Hel</text></lyric>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>end</syllabic><text>lo</text></lyric>
      </note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>single</syllabic><text>world</text></lyric>
      </note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_lyrics_joined_with_plus_for_syllable_continuation(tmp_path):
    """가사 음절이 이어지면(middle/end) '+'로 붙고, 새 단어는 공백으로 구분돼야 한다."""
    xml_path = tmp_path / "lyrics.musicxml"
    xml_path.write_text(_LYRICS_XML, encoding="utf-8")
    out = str(tmp_path / "lyrics.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert song.lyrics.lines[0].lyrics == "Hel+lo world"
    assert song.lyrics.lines[0].startingMeasure == 1


_MULTI_VERSE_LYRICS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric number="1"><syllabic>single</syllabic><text>first</text></lyric>
        <lyric number="2"><syllabic>single</syllabic><text>second</text></lyric>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric number="1"><syllabic>single</syllabic><text>verse</text></lyric>
        <lyric number="2"><syllabic>single</syllabic><text>verse</text></lyric>
      </note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>F</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""


def test_lyrics_verse_2_filtered_out_only_verse_1_used(tmp_path):
    """여러 절이 섞인 MusicXML에서 1절(number='1')만 골라야 하고 2절은 무시돼야 한다."""
    xml_path = tmp_path / "multiverse.musicxml"
    xml_path.write_text(_MULTI_VERSE_LYRICS_XML, encoding="utf-8")
    out = str(tmp_path / "multiverse.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    # 1절만: "first verse"
    assert song.lyrics.lines[0].lyrics == "first verse"
    # 2절 텍스트("second verse")가 섞여 들어가면 안 됨
    assert "second" not in song.lyrics.lines[0].lyrics


def test_lyrics_pickup_measure_zero_not_miscast_to_one(tmp_path):
    """첫 가사가 0번 마디(pickup/anacrusis)에 있으면 startingMeasure=0 유지돼야 한다.

    버그였던 동작: 0 or 1이 1로 평가되면서 마디 번호가 틀어졌다.
    """
    # anacrusis가 0번으로 표기되는 MusicXML (음악이론 관례)
    anacrusis_xml = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="0">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <lyric><syllabic>single</syllabic><text>Up</text></lyric>
      </note>
    </measure>
    <measure number="1">
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>whole</type></note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "anacrusis.musicxml"
    xml_path.write_text(anacrusis_xml, encoding="utf-8")
    out = str(tmp_path / "anacrusis.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    assert song.lyrics.lines[0].startingMeasure == 0, "마디 0(anacrusis)이 1로 오류 변환돼선 안 됨"


def test_lyrics_extraction_failure_does_not_fail_entire_conversion(tmp_path):
    """_collect_lyrics가 예외를 던져도 변환 전체가 실패하면 안 되고, GP5가 정상 생성돼야 한다."""
    out = str(tmp_path / "out.gp5")

    with patch("app.pipeline.musicxml_to_gp._collect_lyrics", side_effect=RuntimeError("boom")):
        result = musicxml_to_gp5(FIXTURE, out)

    # 변환이 성공하고 파일이 생성돼야 한다 (가사만 빠짐)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0

    # 파일 자체는 유효한 GP5여야 한다
    song = guitarpro.parse(out)
    assert len(song.tracks) > 0


_TREMOLO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><ornaments><tremolo type="single">2</tremolo></ornaments></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_tremolo_picking_mapped_to_sixteenth_duration(tmp_path):
    """트레몰로 표기(2슬래시)가 GP5 tremoloPicking(16분음표 속도)로 매핑돼야 한다."""
    xml_path = tmp_path / "tremolo.musicxml"
    xml_path.write_text(_TREMOLO_XML, encoding="utf-8")
    out = str(tmp_path / "tremolo.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.tremoloPicking is not None
    assert note.effect.tremoloPicking.duration.value == guitarpro.models.Duration.sixteenth


_HARMONIC_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><technical><harmonic><natural/></harmonic></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_natural_harmonic_mapped_to_gp5_natural_harmonic(tmp_path):
    """자연 하모닉 표기가 GP5 NaturalHarmonic으로 매핑돼야 한다."""
    xml_path = tmp_path / "harmonic.musicxml"
    xml_path.write_text(_HARMONIC_XML, encoding="utf-8")
    out = str(tmp_path / "harmonic.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert isinstance(note.effect.harmonic, guitarpro.models.NaturalHarmonic)


def test_scan_raw_technicals_finds_bend_and_palm_mute_by_ordinal(tmp_path):
    """단일 보이스 안에서 (마디, 보이스, 순번)별로 벤드/팜뮤트를 찾아야 한다.

    쉼표·화음 연속음(<chord/>)·꾸밈음(<grace/>)은 순번에서 제외해야 한다
    (_extract_events가 이들을 건너뛰거나 따로 처리하는 것과 동일한 순서 유지).
    """
    from app.pipeline.musicxml_to_gp import _scan_raw_technicals

    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <notations><technical><bend><bend-alter>2</bend-alter></bend></technical></notations>
      </note>
      <note><rest/><duration>1</duration><type>quarter</type></note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type>
        <notations><technical><palm-mute type="start"/></technical></notations>
      </note>
      <note><pitch><step>E</step><octave>4</octave></pitch><duration>1</duration><type>quarter</type></note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "raw_technicals.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")

    result = _scan_raw_technicals(str(xml_path))

    # 순번: C(0)=bend(2반음), [쉼표는 순번 안 씀], D(1)=palm_mute, E(2)=없음
    assert result == {
        (1, 0, 0): {"bend": 2.0},
        (1, 0, 1): {"palm_mute": None},
    }


_BEND_PALM_MUTE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type>
        <notations><technical><bend><bend-alter>2</bend-alter></bend></technical></notations>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type>
        <notations><technical><palm-mute type="start"/></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""


def test_bend_and_palm_mute_mapped_via_raw_xml_correlation(tmp_path):
    """<bend>/<palm-mute>가 순번 상관관계로 올바른 음표에 매핑돼야 한다."""
    xml_path = tmp_path / "bend_palm_mute.musicxml"
    xml_path.write_text(_BEND_PALM_MUTE_XML, encoding="utf-8")
    out = str(tmp_path / "bend_palm_mute.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 2

    note0 = beats[0].notes[0]
    note1 = beats[1].notes[0]
    assert note0.effect.bend is not None and len(note0.effect.bend.points) >= 2
    assert note0.effect.palmMute is False
    assert note1.effect.palmMute is True
    assert note1.effect.bend is None


def test_bend_alter_value_propagated_not_hardcoded(tmp_path):
    """<bend-alter>가 1(반음)이면 GP5 벤드도 반음이어야 한다 — 이전엔 값과
    무관하게 항상 2반음(1음) 고정 모양이었다."""
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>whole</type>
        <notations><technical><bend><bend-alter>1</bend-alter></bend></technical></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "bend_alter.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")
    out = str(tmp_path / "bend_alter.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beat = next(b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes)
    note = beat.notes[0]
    assert note.effect.bend is not None
    assert note.effect.bend.points[-1].value == 1


def test_parenthesized_notehead_mapped_to_ghost_note(tmp_path):
    """<notehead parentheses="yes">(고스트/뮤트 노트 표기)가 GP5
    NoteEffect.ghostNote로 반영돼야 한다 — 이전엔 표준악보 경로에서
    이 표기를 감지하는 코드 자체가 없어 조용히 사라졌다."""
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type>
        <notehead parentheses="yes">normal</notehead>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "ghost.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")
    out = str(tmp_path / "ghost.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 2
    assert beats[0].notes[0].effect.ghostNote is True
    assert beats[1].notes[0].effect.ghostNote is False


def test_vibrato_mapped_via_raw_xml_scan(tmp_path):
    """<notations><technical><vibrato/>가 GP5 NoteEffect.vibrato로 반영돼야 한다."""
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time></attributes>
      <note><pitch><step>C</step><octave>4</octave></pitch><duration>2</duration><type>half</type>
        <notations><technical><vibrato/></technical></notations>
      </note>
      <note><pitch><step>D</step><octave>4</octave></pitch><duration>2</duration><type>half</type></note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "vibrato.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")
    out = str(tmp_path / "vibrato.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beats = [b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes]
    assert len(beats) == 2
    assert beats[0].notes[0].effect.vibrato is True
    assert beats[1].notes[0].effect.vibrato is False


def test_trill_mark_resolves_key_aware_alt_pitch_to_fret_offset(tmp_path):
    """<trill-mark>가 조표를 반영한 대체음(온음/반음)의 프렛 오프셋으로
    GP5 TrillEffect에 반영돼야 한다 — 이전엔 트릴이 완전히 무시됐다.

    C장조에서 C의 온음 위 이웃음은 D(2프렛 위) — 어떤 현에 배정되든
    트릴 프렛은 항상 main_fret + 2여야 한다.
    """
    xml_text = """<?xml version="1.0" encoding="UTF-8"?>
<score-partwise version="3.1">
  <part-list><score-part id="P1"><part-name>Guitar</part-name></score-part></part-list>
  <part id="P1">
    <measure number="1">
      <attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type></time>
      <key><fifths>0</fifths></key></attributes>
      <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>whole</type>
        <notations><ornaments><trill-mark/></ornaments></notations>
      </note>
    </measure>
  </part>
</score-partwise>"""
    xml_path = tmp_path / "trill.musicxml"
    xml_path.write_text(xml_text, encoding="utf-8")
    out = str(tmp_path / "trill.gp5")

    musicxml_to_gp5(str(xml_path), out)

    song = guitarpro.parse(out)
    beat = next(b for v in song.tracks[0].measures[0].voices for b in v.beats if b.notes)
    note = beat.notes[0]
    assert note.effect.trill is not None
    assert note.effect.trill.fret == note.value + 2, "C 위 온음 이웃음 D = 2프렛 위"


def test_scan_raw_technicals_failure_does_not_fail_entire_conversion(tmp_path):
    """_scan_raw_technicals가 예외를 던져도 변환 전체가 실패하면 안 되고, GP5가 정상 생성돼야 한다."""
    out = str(tmp_path / "out.gp5")

    with patch("app.pipeline.musicxml_to_gp._scan_raw_technicals", side_effect=RuntimeError("boom")):
        result = musicxml_to_gp5(FIXTURE, out)

    # 변환이 성공하고 파일이 생성돼야 한다 (벤드/팜뮤트만 빠짐)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0

    # 파일 자체는 유효한 GP5여야 한다
    song = guitarpro.parse(out)
    assert len(song.tracks) > 0
