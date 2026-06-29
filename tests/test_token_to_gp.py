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
    assert (6, 7) in first_beat.notes
    assert (5, 8) in first_beat.notes
    assert (4, 0) in first_beat.notes


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
    assert measures[0].beats[0].notes == [(1, 0)]
    assert measures[1].beats[0].notes == [(1, 7)]


def test_unknown_token_is_skipped(caplog):
    from app.pipeline.token_to_gp import _parse_token_texts
    import logging

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 UNKNOWN_TOKEN N_S1_F0\nEND_BAR"
    with caplog.at_level(logging.WARNING, logger="app.pipeline.token_to_gp"):
        measures = _parse_token_texts([token_text])

    assert len(measures) == 1
    assert measures[0].beats[0].notes == [(1, 0)]
    assert any("UNKNOWN_TOKEN" in r.message for r in caplog.records)


def test_double_bar_does_not_break_measure():
    from app.pipeline.token_to_gp import _parse_token_texts

    token_text = "TS_4_4\nBAR\nBEAT DUR_1 REST\nDOUBLE_BAR\nEND_BAR"
    measures = _parse_token_texts([token_text])
    assert len(measures) == 1


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
    """변환된 GP5의 첫 마디 첫 비트에 올바른 프렛 값이 있어야 한다."""
    import guitarpro
    from app.pipeline.token_to_gp import token_texts_to_gp5

    token_text = "TS_4_4\nBAR\nBEAT DUR_4 N_S6_F7 N_S5_F8 N_S4_F0\nEND_BAR"
    out_path = str(tmp_path / "out.gp5")
    token_texts_to_gp5([token_text], out_path)

    song = guitarpro.parse(out_path)
    beat = song.tracks[0].measures[0].voices[0].beats[0]
    frets = {n.value for n in beat.notes}
    assert 7 in frets
    assert 8 in frets
    assert 0 in frets


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
