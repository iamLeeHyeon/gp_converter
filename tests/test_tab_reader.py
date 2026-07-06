import os

from app.pipeline.tab_reader import (
    TabStaffRegion,
    TabNote,
    _CharBox,
    _extract_region_notes,
    _group_evenly_spaced,
    _try_extend_to_six,
    detect_tab_staves,
    extract_tab_notes,
    has_multiple_strings,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
TAB_PDF = os.path.join(FIXTURE_DIR, "tab_sample.pdf")
STANDARD_ONLY_PDF = os.path.join(FIXTURE_DIR, "sample.pdf")

# Task 1에서 실측 확인한 탭보표 6줄 (위→아래)
EXPECTED_LINE_YS = [731.0, 723.5, 716.1, 708.6, 701.1, 693.6]

# Task 1에서 실측 확인한 전체 탭 순서열 (32개).
# 3,11,18,26번째 음(E4)은 LilyPond 소스에서 `e\2`로 2번줄을 강제 지정했다 —
# 휴리스틱(최저프렛)이라면 1번줄 0프렛을 고르지만 탭에는 2번줄 5프렛으로 적혀 있다.
EXPECTED_TAB_NOTES = [
    (2, 1), (2, 3), (2, 5), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8),
    (1, 8), (1, 7), (1, 5), (1, 3), (1, 1), (2, 5), (2, 3), (2, 1),
    (2, 1), (2, 3), (2, 5), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8),
    (1, 8), (1, 7), (1, 5), (1, 3), (1, 1), (2, 5), (2, 3), (2, 1),
]


def test_try_extend_to_six_recovers_stolen_line():
    """노이즈 라인이 6번째 탭선을 탈취한 경우, 예상 위치의 y를 추가해 6줄로 복구해야 한다.

    santa tell me PDF 실사례 재현:
      5줄 그룹 [570.9, 581.1, 591.3, 601.6, 611.8] + 노이즈 615.8 → [615.8, 622.0]으로 탈취
      expected 6번째 = 611.8 + 10.2 ≈ 622.0 이 all_ys에 있으면 그룹에 추가해야 한다.
    """
    group = [570.9, 581.1, 591.3, 601.6, 611.8]
    all_ys = [570.9, 581.1, 591.3, 601.6, 611.8, 615.8, 622.0, 626.0]
    result = _try_extend_to_six(group, all_ys)
    assert result == [570.9, 581.1, 591.3, 601.6, 611.8, 622.0]


def test_try_extend_to_six_no_match_stays_five():
    """5줄 표준보표처럼 예상 위치에 y가 없으면 그대로 5줄이어야 한다."""
    group = [393.6, 400.4, 407.2, 414.0, 420.8]
    # 다음 y가 570.9 (gap 150pt, 예상 6th=427.6과 전혀 다름)
    all_ys = [393.6, 400.4, 407.2, 414.0, 420.8, 570.9]
    result = _try_extend_to_six(group, all_ys)
    assert result == [393.6, 400.4, 407.2, 414.0, 420.8]


def test_group_evenly_spaced_groups_by_line_count_not_absolute_gap():
    """간격이 서로 다른(10pt, 7.5pt) 두 그룹이 섞여 있어도 개수로만 묶여야 한다."""
    ys = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 100.0, 107.5, 115.0, 122.5, 130.0]
    groups = _group_evenly_spaced(ys)
    six_line_groups = [g for g in groups if len(g) == 6]
    five_line_groups = [g for g in groups if len(g) == 5]

    assert len(six_line_groups) == 1
    assert six_line_groups[0] == [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
    assert len(five_line_groups) == 1
    assert five_line_groups[0] == [100.0, 107.5, 115.0, 122.5, 130.0]


def test_detect_tab_staves_finds_six_line_staff():
    regions = detect_tab_staves(TAB_PDF)

    assert len(regions) == 1
    assert regions[0].page_index == 0
    assert regions[0].line_ys == EXPECTED_LINE_YS


def test_detect_tab_staves_empty_when_no_tab_staff():
    """표준악보만 있는 기존 MVP 픽스처에서는 탭보표가 검출되지 않아야 한다."""
    regions = detect_tab_staves(STANDARD_ONLY_PDF)

    assert regions == []


def test_extract_region_notes_merges_multidigit_and_skips_mute():
    """인접한 숫자(gap<4pt)는 다중 자릿수로 합치고, 'X'는 결과에서 제외해야 한다."""
    region = TabStaffRegion(page_index=0, line_ys=[100.0, 90.0, 80.0, 70.0, 60.0, 50.0])
    chars = [
        _CharBox(text="1", x0=10.0, x1=15.0, y0=100.0),
        _CharBox(text="0", x0=16.0, x1=21.0, y0=100.0),  # "10"으로 합쳐짐 (gap=1.0)
        _CharBox(text="X", x0=40.0, x1=45.0, y0=90.0),   # 뮤트, 결과에서 제외
        _CharBox(text="3", x0=70.0, x1=75.0, y0=80.0),    # 별개 음표
    ]

    notes = _extract_region_notes(chars, region)

    assert notes == [TabNote(string=1, fret=10), TabNote(string=3, fret=3)]


def test_extract_region_notes_does_not_merge_digit_with_adjacent_mute():
    """gap이 작아도(<4pt) 숫자와 'X'는 절대 같은 토큰으로 합쳐지면 안 된다."""
    region = TabStaffRegion(page_index=0, line_ys=[100.0, 90.0, 80.0, 70.0, 60.0, 50.0])
    chars = [
        _CharBox(text="5", x0=10.0, x1=15.0, y0=50.0),
        _CharBox(text="X", x0=16.0, x1=21.0, y0=50.0),  # gap=1.0 (<4.0), 그래도 병합되면 안 됨
    ]

    notes = _extract_region_notes(chars, region)

    assert notes == [TabNote(string=6, fret=5)]


def test_extract_tab_notes_full_fixture():
    regions = detect_tab_staves(TAB_PDF)
    notes = extract_tab_notes(TAB_PDF, regions)

    actual = [(n.string, n.fret) for n in notes]
    assert actual == EXPECTED_TAB_NOTES


def test_has_multiple_strings_true_for_real_tab_fixture():
    """진짜 탭 픽스처는 여러 현에 걸쳐 프렛 숫자가 분포해야 한다."""
    regions = detect_tab_staves(TAB_PDF)
    notes = extract_tab_notes(TAB_PDF, regions)
    assert has_multiple_strings(notes)


def test_has_multiple_strings_false_when_all_same_string():
    """마디번호 등 오탐지로 숫자가 전부 같은 한 현에만 배정되면 False여야 한다.

    Rêverie PDF 실사례 재현: 5선보 위 마디번호("48")가 우연히 보표 줄 간격과
    같은 위치에 있어 6번째 탭선으로 오탐지됨 — 추출된 숫자가 전부 같은
    (가장 가까운) 한 줄에만 배정된다.
    """
    notes = [TabNote(string=1, fret=4), TabNote(string=1, fret=8)]
    assert has_multiple_strings(notes) is False


def test_has_multiple_strings_false_when_empty():
    """숫자가 아예 없으면(오탐지 or 문자추출 불가) False여야 한다."""
    assert has_multiple_strings([]) is False


def test_has_multiple_strings_true_when_two_distinct_strings():
    notes = [TabNote(string=1, fret=0), TabNote(string=1, fret=2), TabNote(string=3, fret=5)]
    assert has_multiple_strings(notes) is True
