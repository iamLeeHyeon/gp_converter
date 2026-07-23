import pytest


SIMPLE_TOKEN_TEXT = """\
TS_4_4
BAR
BEAT DUR_4 DYN_MF BTECH_STRUM_DOWN N_S6_F7 N_S5_F8 N_S4_F0
BEAT DUR_8 N_S5_F8
BEAT DUR_8 N_S4_F0
BEAT DUR_4 N_S6_F5
BEAT DUR_4 N_S5_F3
END_BAR
"""

REST_TOKEN_TEXT = """\
TS_4_4
BAR
BEAT DUR_1 REST
END_BAR
"""

TWO_SYSTEM_TEXTS = [
    "TS_4_4\nBAR\nBEAT DUR_4 N_S1_F0\nBEAT DUR_4 N_S1_F2\nBEAT DUR_4 N_S1_F3\nBEAT DUR_4 N_S1_F5\nEND_BAR",
    "TS_4_4\nBAR\nBEAT DUR_4 N_S1_F7\nBEAT DUR_4 N_S1_F5\nBEAT DUR_4 N_S1_F3\nBEAT DUR_4 N_S1_F0\nEND_BAR",
]


def test_parse_time_signature():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts(["TS_3_4\nBAR\nBEAT DUR_4 N_S1_F0\nEND_BAR"])
    assert measures[0].time_sig_num == 3
    assert measures[0].time_sig_den == 4


def test_parse_single_measure_beat_count():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts([SIMPLE_TOKEN_TEXT])
    assert len(measures) == 1
    assert len(measures[0].beats) == 5


def test_parse_rest_beat():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts([REST_TOKEN_TEXT])
    assert len(measures) == 1
    beat = measures[0].beats[0]
    assert beat.is_rest is True
    assert beat.duration_value == 1


def test_parse_notes_in_beat():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts([SIMPLE_TOKEN_TEXT])
    first_beat = measures[0].beats[0]
    pairs = [(n.string, n.fret) for n in first_beat.notes]
    assert (6, 7) in pairs
    assert (5, 8) in pairs
    assert (4, 0) in pairs


def test_parse_dynamics():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts([SIMPLE_TOKEN_TEXT])
    assert measures[0].beats[0].velocity == 79  # mf


def test_parse_strum_down():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts([SIMPLE_TOKEN_TEXT])
    assert measures[0].beats[0].strum_down is True


def test_parse_two_systems_merges_measures():
    from app.pipeline.token_to_gp import _parse_token_texts

    measures = _parse_token_texts(TWO_SYSTEM_TEXTS)
    assert len(measures) == 2
    n0 = measures[0].beats[0].notes[0]
    assert n0.string == 1 and n0.fret == 0
    n1 = measures[1].beats[0].notes[0]
    assert n1.string == 1 and n1.fret == 7


def test_unknown_token_is_skipped(caplog):
    from app.pipeline.token_to_gp import _parse_token_texts
    import logging

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 UNKNOWN_TOKEN N_S1_F0\nEND_BAR"
    with caplog.at_level(logging.WARNING, logger="app.pipeline.token_to_gp"):
        measures = _parse_token_texts([token_text])

    assert len(measures) == 1
    n = measures[0].beats[0].notes[0]
    assert n.string == 1 and n.fret == 0
    assert any("UNKNOWN_TOKEN" in r.message for r in caplog.records)


def test_double_bar_does_not_break_measure():
    from app.pipeline.token_to_gp import _parse_token_texts

    token_text = "TS_4_4\nBAR\nBEAT DUR_1 REST\nDOUBLE_BAR\nEND_BAR"
    measures = _parse_token_texts([token_text])
    assert len(measures) == 1


def test_parse_dead_note():
    """N_S{n}_FX는 is_dead=True, fret=0인 _NoteData가 돼야 한다."""
    from app.pipeline.token_to_gp import _parse_token_texts

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 N_S1_FX N_S2_F3\nEND_BAR"
    measures = _parse_token_texts([token_text])
    notes = measures[0].beats[0].notes
    assert notes[0].is_dead is True
    assert notes[0].fret == 0
    assert notes[0].string == 1
    assert notes[1].is_dead is False
    assert notes[1].fret == 3


def test_parse_ntech_legato():
    """NTECH_LEGATO_ORIGIN은 직전 음표의 legato=True로 저장돼야 한다."""
    from app.pipeline.token_to_gp import _parse_token_texts

    token_text = "TS_4_4\nBAR\nBEAT DUR_8 N_S6_F5 NTECH_LEGATO_ORIGIN\nEND_BAR"
    measures = _parse_token_texts([token_text])
    note = measures[0].beats[0].notes[0]
    assert note.legato is True


def test_parse_ntech_slide_out():
    """NTECH_SLIDE_OUT_1은 직전 음표의 slides에 SlideType.shiftSlideTo가 추가돼야 한다."""
    from app.pipeline.token_to_gp import _parse_token_texts
    from guitarpro.models import SlideType

    token_text = "TS_4_4\nBAR\nBEAT DUR_16 N_S6_F5 NTECH_SLIDE_OUT_1\nEND_BAR"
    measures = _parse_token_texts([token_text])
    note = measures[0].beats[0].notes[0]
    assert SlideType.shiftSlideTo in note.slides


def test_parse_dots_1():
    """DOTS_1은 비트의 is_dotted=True로 저장돼야 한다."""
    from app.pipeline.token_to_gp import _parse_token_texts

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 DOTS_1 N_S1_F0\nEND_BAR"
    measures = _parse_token_texts([token_text])
    beat = measures[0].beats[0]
    assert beat.is_dotted is True


def test_gp5_dead_note_type(tmp_path):
    """dead note는 GP5에서 NoteType.dead로 저장돼야 한다."""
    import guitarpro
    from guitarpro import NoteType
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 N_S1_FX\nEND_BAR"
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.type == NoteType.dead


def test_gp5_slide_effect(tmp_path):
    """slide note는 GP5에서 effect.slides가 비어있지 않아야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = "TS_4_4\nBAR\nBEAT DUR_16 N_S6_F5 NTECH_SLIDE_OUT_1\nEND_BAR"
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.slides  # 비어있지 않음


def test_gp5_hammer_on(tmp_path):
    """NTECH_LEGATO_ORIGIN은 GP5에서 effect.hammer=True로 저장돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = "TS_4_4\nBAR\nBEAT DUR_8 N_S6_F5 NTECH_LEGATO_ORIGIN\nEND_BAR"
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.hammer is True


def test_gp5_dotted_duration(tmp_path):
    """DOTS_1은 GP5에서 isDotted=True인 Duration으로 저장돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 DOTS_1 N_S1_F0\nEND_BAR"
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    assert beat.duration.isDotted is True


def test_gp5_strum_direction(tmp_path):
    """BTECH_STRUM_DOWN/UP은 GP5 beat.effect.pickStroke로 저장돼야 한다."""
    import guitarpro
    from guitarpro.models import BeatStrokeDirection
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = (
        "TS_4_4\nBAR\n"
        "BEAT DUR_4 BTECH_STRUM_DOWN N_S6_F5\n"
        "BEAT DUR_4 BTECH_STRUM_UP N_S6_F5\n"
        "END_BAR"
    )
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    beats = song.tracks[0].measures[0].voices[0].beats
    assert beats[0].effect.pickStroke == BeatStrokeDirection.down
    assert beats[1].effect.pickStroke == BeatStrokeDirection.up


def test_token_texts_to_gp5_creates_file(tmp_path):
    """GP5 파일이 생성돼야 한다."""
    from app.pipeline.token_to_gp import token_texts_to_gp5

    out_path = str(tmp_path / "out.gp5")
    token_texts_to_gp5([SIMPLE_TOKEN_TEXT], out_path)

    assert (tmp_path / "out.gp5").exists()
    assert (tmp_path / "out.gp5").stat().st_size > 0


def test_token_texts_to_gp5_parseable(tmp_path):
    """생성된 GP5 파일이 guitarpro.parse로 재파싱 가능해야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    out_path = str(tmp_path / "out.gp5")
    token_texts_to_gp5([SIMPLE_TOKEN_TEXT], out_path)

    song = guitarpro.parse(out_path)
    assert song is not None
    assert len(song.tracks) >= 1


def test_token_texts_to_gp5_note_values(tmp_path):
    """변환된 GP5의 첫 마디 첫 비트에 올바른 프렛/현 값이 있어야 한다.

    guitar-tab-omr 컨벤션: S1=low E(하단), S6=high E(상단)
    PyGuitarPro 컨벤션: string 1=high E(상단), string 6=low E(하단)
    변환식: gp_string = 7 - omr_string
    """
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    # S6(high E)->GP string 1, S5(B)->GP string 2, S4(G)->GP string 3
    token_text = "TS_4_4\nBAR\nBEAT DUR_4 N_S6_F7 N_S5_F8 N_S4_F0\nEND_BAR"
    out_path = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out_path)

    song = guitarpro.parse(out_path)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    notes_by_string = {n.string: n.value for n in beat.notes}
    assert notes_by_string[1] == 7   # S6_F7 → GP string 1 (high E), fret 7
    assert notes_by_string[2] == 8   # S5_F8 → GP string 2 (B), fret 8
    assert notes_by_string[3] == 0   # S4_F0 → GP string 3 (G), fret 0


def test_token_texts_to_gp5_two_systems(tmp_path):
    """두 시스템 → 두 마디로 변환돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    out_path = str(tmp_path / "out.gp5")
    token_texts_to_gp5(TWO_SYSTEM_TEXTS, out_path)

    song = guitarpro.parse(out_path)
    assert len(song.tracks[0].measures) == 2


def test_token_texts_to_gp5_rest(tmp_path):
    """쉼표 마디도 정상 변환돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    out_path = str(tmp_path / "out.gp5")
    token_texts_to_gp5([REST_TOKEN_TEXT], out_path)

    song = guitarpro.parse(out_path)
    assert song is not None


def test_token_texts_to_gp5_empty_raises(tmp_path):
    """파싱된 마디가 없으면 ValueError가 발생해야 한다."""
    from app.pipeline.token_to_gp import token_texts_to_gp5

    with pytest.raises(ValueError, match="마디"):
        token_texts_to_gp5([""], str(tmp_path / "out.gp5"))


# ---------------------------------------------------------------------------
# snapshot_to_gp5() 테스트
# ---------------------------------------------------------------------------

SIMPLE_SNAPSHOT = {
    "tracks": [{
        "measures": [{
            "timeSignature": {"num": 4, "den": 4},
            "beats": [
                {
                    "duration": 4, "dotted": False, "status": "normal",
                    "dynamic": "mf", "strumDown": True,
                    "notes": [
                        {"string": 1, "fret": 7, "effect": None},
                        {"string": 2, "fret": 8},
                    ],
                },
                {
                    "duration": 4, "dotted": False, "status": "normal",
                    "dynamic": "f",
                    "notes": [{"string": 1, "fret": 5, "effect": "hammer-on"}],
                },
                {
                    "duration": 4, "dotted": False, "status": "rest",
                    "dynamic": "mf", "notes": [],
                },
                {
                    "duration": 4, "dotted": False, "status": "normal",
                    "dynamic": "mp",
                    "notes": [{"string": 3, "fret": 0, "effect": "ghost"}],
                },
            ],
        }]
    }]
}

REST_SNAPSHOT = {
    "tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 1, "dotted": False, "status": "rest", "notes": []}]}]}]
}


def test_snapshot_to_gp5_creates_file(tmp_path):
    """snapshot_to_gp5가 파일을 생성해야 한다."""
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    result = snapshot_to_gp5(SIMPLE_SNAPSHOT, out)
    assert result == out
    assert (tmp_path / "out.gp5").exists()
    assert (tmp_path / "out.gp5").stat().st_size > 0


def test_snapshot_to_gp5_parseable(tmp_path):
    """생성된 GP5가 guitarpro.parse로 재파싱 가능해야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(SIMPLE_SNAPSHOT, out)
    song = guitarpro.parse(out)
    assert len(song.tracks) >= 1
    assert len(song.tracks[0].measures) == 1


def test_snapshot_to_gp5_note_fret(tmp_path):
    """첫 비트 첫 음표 프렛이 7이어야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(SIMPLE_SNAPSHOT, out)
    song = guitarpro.parse(out)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    frets = {n.value for n in beat.notes}
    assert 7 in frets
    assert 8 in frets


def test_snapshot_to_gp5_rest(tmp_path):
    """쉼표 스냅샷도 정상 변환돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(REST_SNAPSHOT, out)
    song = guitarpro.parse(out)
    assert song is not None


def test_snapshot_to_gp5_no_string_reversal(tmp_path):
    """GP 컨벤션 스트링 번호 — 반전 없이 그대로 저장돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    snap = {"tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf",
                   "notes": [{"string": 1, "fret": 5}]}]}]}]}
    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(snap, out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.string == 1


def test_snapshot_to_gp5_trill_effect(tmp_path):
    """effect='trill' + trillFret이 GP5 TrillEffect로 반영돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    snap = {"tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf",
                   "notes": [{"string": 1, "fret": 5, "effect": "trill", "trillFret": 7}]}]}]}]}
    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(snap, out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.trill is not None
    assert note.effect.trill.fret == 7


def test_snapshot_to_gp5_vibrato_effect(tmp_path):
    """effect='vibrato'가 GP5 NoteEffect.vibrato로 반영돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    snap = {"tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf",
                   "notes": [{"string": 1, "fret": 5, "effect": "vibrato"}]}]}]}]}
    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(snap, out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.vibrato is True


def test_snapshot_to_gp5_right_hand_finger(tmp_path):
    """rightHandFinger가 GP5 NoteEffect.rightHandFinger로 반영돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import snapshot_to_gp5

    snap = {"tracks": [{"measures": [{"timeSignature": {"num": 4, "den": 4},
        "beats": [{"duration": 4, "dotted": False, "status": "normal",
                   "dynamic": "mf",
                   "notes": [{"string": 1, "fret": 5, "rightHandFinger": 1}]}]}]}]}
    out = str(tmp_path / "out.gp5")
    snapshot_to_gp5(snap, out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert note.effect.rightHandFinger == guitarpro.Fingering.index


def test_snapshot_to_gp5_empty_raises(tmp_path):
    """트랙 없으면 ValueError가 발생해야 한다."""
    from app.pipeline.token_to_gp import snapshot_to_gp5

    with pytest.raises(ValueError, match="트랙"):
        snapshot_to_gp5({"tracks": []}, str(tmp_path / "out.gp5"))


def test_gp5_harmonic_type_preserved(tmp_path):
    """NTECH_HARMONIC_{NATURAL|ARTIFICIAL|PINCH|SEMI|TAP} 타입 토큰에 맞는
    PyGuitarPro 하모닉 클래스로 저장돼야 한다 — 이전엔 타입 토큰 자체를
    아예 처리하지 않아서(알 수 없는 NTECH 토큰으로 스킵됨) 어떤 하모닉
    기법이든 전부 NaturalHarmonic으로 뭉개져 저장됐다(핀치/아티피셜 하모닉
    정보 소실)."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = (
        "TS_4_4\nBAR\n"
        "BEAT DUR_4 N_S3_F12 NTECH_HARMONIC_ARTIFICIAL NTECH_HARMONIC_VALUE_12\n"
        "BEAT DUR_4 N_S3_F12 NTECH_HARMONIC_PINCH NTECH_HARMONIC_VALUE_12\n"
        "BEAT DUR_4 N_S3_F12 NTECH_HARMONIC_NATURAL NTECH_HARMONIC_VALUE_12\n"
        "END_BAR\n"
    )
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    beats = song.tracks[0].measures[0].voices[0].beats
    assert isinstance(beats[0].notes[0].effect.harmonic, guitarpro.models.ArtificialHarmonic)
    assert isinstance(beats[1].notes[0].effect.harmonic, guitarpro.models.PinchHarmonic)
    assert isinstance(beats[2].notes[0].effect.harmonic, guitarpro.models.NaturalHarmonic)


def test_pad_voice_fills_exact_64th_remainder():
    """남은 용량이 정확히 1/64분음표 하나뿐이면(64분음표 fill_units=1),
    그 자리도 64분쉼표로 채워야 한다 — _DUR_FILL_ORDER에 64가 빠져있으면
    이 마지막 1유닛을 못 채우고 마디 길이가 미세하게 부족해진다."""
    import guitarpro.models as gpm
    from guitarpro.models import BeatStatus
    from guitarpro import Beat
    from app.pipeline.token_to_gp import _pad_voice_with_rests

    song = gpm.Song()
    voice = song.tracks[0].measures[0].voices[0]
    b = Beat(voice)
    b.status = BeatStatus.normal
    b.duration = gpm.Duration()
    b.duration.value = 4
    voice.beats = [b]

    _pad_voice_with_rests(voice, 1.0)

    assert [bt.duration.value for bt in voice.beats] == [4, 64]
    assert voice.beats[1].status == BeatStatus.rest


def test_measure_overflow_skips_only_offending_beat(tmp_path):
    """마디 용량을 초과하는 비트 하나 때문에 그 뒤에 이어지는 정상 비트들까지
    통째로 버려지면 안 된다 — OMR이 비트 하나의 길이를 잘못 읽어도(예:
    4분음표를 온음표로 오인식), 그 비트 하나만 건너뛰고 나머지는 그대로
    반영해야 한다(이전엔 그 비트에서 break해서 뒤가 전부 사라졌다)."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = (
        "TS_4_4\nBAR\n"
        "BEAT DUR_4 N_S1_F0\n"
        "BEAT DUR_4 N_S1_F1\n"
        "BEAT DUR_4 N_S1_F2\n"
        "BEAT DUR_1 N_S1_F9\n"  # 48/64 용량 초과 온음표 — 잘못 인식된 비트
        "BEAT DUR_4 N_S1_F3\n"  # 이 비트는 살아남아야 함
        "END_BAR\n"
    )
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    beats = song.tracks[0].measures[0].voices[0].beats
    frets = [b.notes[0].value for b in beats if b.notes]
    assert frets == [0, 1, 2, 3]


def test_gp5_harmonic_value_only_falls_back_to_natural(tmp_path):
    """타입 토큰 없이 NTECH_HARMONIC_VALUE_*만 있으면(회귀 없음 확인)
    지금까지처럼 NaturalHarmonic으로 대체돼야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 N_S3_F12 NTECH_HARMONIC_VALUE_12\nEND_BAR\n"
    out = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out)
    song = guitarpro.parse(out)
    note = song.tracks[0].measures[0].voices[0].beats[0].notes[0]
    assert isinstance(note.effect.harmonic, guitarpro.models.NaturalHarmonic)
