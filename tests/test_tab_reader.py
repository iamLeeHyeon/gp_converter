import os

from app.pipeline.tab_reader import (
    TabStaffRegion,
    TabNote,
    _CharBox,
    _extract_region_notes,
    _group_evenly_spaced,
    detect_tab_staves,
    extract_tab_notes,
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


def test_extract_tab_notes_full_fixture():
    regions = detect_tab_staves(TAB_PDF)
    notes = extract_tab_notes(TAB_PDF, regions)

    actual = [(n.string, n.fret) for n in notes]
    assert actual == EXPECTED_TAB_NOTES
