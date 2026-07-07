"""
PDF → .gp5 엔드투엔드 통합 테스트.

실제 Audiveris(Java)와 PyGuitarPro를 사용한다(서브프로세스 모킹 없음).
기본 pytest 실행(`-m 'not integration'`)에서는 제외되며,
`pytest -m integration`으로만 실행된다.

픽스처(tests/fixtures/sample.pdf, sample.ly)는 LilyPond로 생성한
저작권 무관 C장조 음계(C4~C5, 4분음표 8개)이다.
"""
import os

import guitarpro
import pytest

from app.pipeline.orchestrator import run_conversion

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample.pdf")
EXPECTED_MIDI = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 D4 E4 F4 G4 A4 B4 C5

# 로컬 개발 환경(이 머신)의 기본 설치 경로. CI/Docker에서는
# GPC_AUDIVERIS_CMD 환경변수로 덮어쓴다.
_DEFAULT_AUDIVERIS_CMD = "/Applications/Audiveris.app/Contents/MacOS/Audiveris"


@pytest.mark.integration
def test_pdf_to_gp5_real(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()

    gp5_path = run_conversion(
        FIXTURE,
        str(workdir),
        audiveris_cmd=os.environ.get("GPC_AUDIVERIS_CMD", _DEFAULT_AUDIVERIS_CMD),
        timeout=300,
    )

    assert os.path.exists(gp5_path)
    assert os.path.getsize(gp5_path) > 0

    with open(gp5_path, "rb") as f:
        head = f.read(40)
    assert b"GUITAR PRO" in head

    song = guitarpro.parse(gp5_path)
    track = song.tracks[0]
    string_val = {s.number: s.value for s in track.strings}

    actual_midi = [
        string_val[note.string] + note.value
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert actual_midi == EXPECTED_MIDI, (
        f"음정 시퀀스 불일치(OMR 인식 오차 가능)\n예상: {EXPECTED_MIDI}\n실제: {actual_midi}"
    )


TAB_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "tab_sample.pdf")

# Task 3에서 실측 확인한 탭 (현,프렛) 순서열. 휴리스틱과 다른 지점(E4→(2,5))이
# 그대로 살아있어야 탭 힌트가 실제로 쓰였다고 볼 수 있다.
EXPECTED_TAB_STRING_FRET = [
    (2, 1), (2, 3), (2, 5), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8),
    (1, 8), (1, 7), (1, 5), (1, 3), (1, 1), (2, 5), (2, 3), (2, 1),
    (2, 1), (2, 3), (2, 5), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8),
    (1, 8), (1, 7), (1, 5), (1, 3), (1, 1), (2, 5), (2, 3), (2, 1),
]


@pytest.mark.integration
def test_pdf_with_tab_uses_tab_hints_not_heuristic(tmp_path):
    workdir = tmp_path / "work"
    workdir.mkdir()

    gp5_path = run_conversion(
        TAB_FIXTURE,
        str(workdir),
        audiveris_cmd=os.environ.get("GPC_AUDIVERIS_CMD", _DEFAULT_AUDIVERIS_CMD),
        timeout=300,
    )

    song = guitarpro.parse(gp5_path)
    track = song.tracks[0]

    actual = [
        (note.string, note.value)
        for measure in track.measures
        for voice in measure.voices
        for beat in voice.beats
        for note in beat.notes
    ]

    assert actual == EXPECTED_TAB_STRING_FRET, (
        f"탭 힌트가 적용되지 않았을 가능성(휴리스틱으로 폴백됐는지 확인)\n"
        f"예상: {EXPECTED_TAB_STRING_FRET}\n실제: {actual}"
    )
