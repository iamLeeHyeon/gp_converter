import os

from app.pipeline.tab_reader import _group_evenly_spaced, detect_tab_staves

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
TAB_PDF = os.path.join(FIXTURE_DIR, "tab_sample.pdf")
STANDARD_ONLY_PDF = os.path.join(FIXTURE_DIR, "sample.pdf")

# Task 1에서 실측 확인한 탭보표 6줄 (위→아래)
EXPECTED_LINE_YS = [731.0, 723.5, 716.1, 708.6, 701.1, 693.6]


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
