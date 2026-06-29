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
