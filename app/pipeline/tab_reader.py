"""
PDF 탭(TAB) 보표 인식 — 디지털 탭 PDF에서 (현, 프렛) 정보를 추출한다.

설계 결정:
- 탭보표 감지: 수평 벡터선을 y좌표로 등간격 클러스터링해 "연속 6줄" 그룹을 찾는다.
  절대 간격은 소프트웨어마다 다르므로(실측: 10.2pt vs 7.5pt) 줄 개수만 본다.
- 프렛 숫자 추출: pdfminer 기본 텍스트 그룹화(LTTextLineHorizontal)에 의존하지 않는다.
  바코드/타이 등 비숫자 글리프가 숫자 옆에 붙으면 그룹화가 숫자를 오염시켜
  추출에서 빠뜨리는 사례가 실측으로 확인됐다(Task 3에서 상세 설명).
"""
from __future__ import annotations

import dataclasses
from typing import List, Optional

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTChar, LTLine, LTPage, LTCurve, LTRect

_MIN_LINE_WIDTH = 30.0  # 보표선으로 볼 최소 폭(짧은 장식선/빔 제외)
_GROUP_TOLERANCE_MIN = 0.5  # 등간격 판정 최소 허용오차(pt)
_GROUP_TOLERANCE_RATIO = 0.15  # 첫 간격 기준 허용오차 비율 (0.3→0.15: 5선보 오탐지 방지)
_TAB_STRING_COUNT = 6


@dataclasses.dataclass
class TabStaffRegion:
    page_index: int
    line_ys: List[float]  # 위→아래 6개 (1번현~6번현 순)


def _horizontal_lines(page: LTPage) -> List[object]:
    lines = []

    def walk(obj):
        if isinstance(obj, (LTLine, LTRect, LTCurve)):
            if abs(obj.y0 - obj.y1) < 0.5 and (obj.x1 - obj.x0) >= _MIN_LINE_WIDTH:
                lines.append(obj)
        for child in getattr(obj, "_objs", []):
            walk(child)

    walk(page)
    return lines


def _group_evenly_spaced(ys: List[float]) -> List[List[float]]:
    """오름차순 y좌표 목록을 등간격 그룹으로 묶는다."""
    if not ys:
        return []
    groups: List[List[float]] = [[ys[0]]]
    first_gap: Optional[float] = None
    for y in ys[1:]:
        group = groups[-1]
        gap = y - group[-1]
        if len(group) == 1:
            group.append(y)
            first_gap = gap
            continue
        tol = max(_GROUP_TOLERANCE_MIN, _GROUP_TOLERANCE_RATIO * first_gap)
        if abs(gap - first_gap) <= tol:
            group.append(y)
        else:
            groups.append([y])
            first_gap = None
    return groups


def _try_extend_to_six(group: List[float], all_ys: List[float]) -> List[float]:
    """5줄 등간격 그룹을 6줄로 확장 시도.

    노이즈 라인이 실제 6번째 탭선을 가로채 5줄만 남았을 때,
    예상 위치(위 또는 아래로 spacing 거리)에 y가 있으면 그룹에 추가한다.
    """
    if len(group) != 5:
        return group
    spacing = (group[-1] - group[0]) / 4
    tol = max(_GROUP_TOLERANCE_MIN, _GROUP_TOLERANCE_RATIO * spacing)
    for expected in (group[-1] + spacing, group[0] - spacing):
        for y in all_ys:
            if y not in group and abs(y - expected) <= tol:
                return sorted(group + [y])
    return group


def detect_tab_staves(pdf_path: str) -> List[TabStaffRegion]:
    """PDF에서 탭보표(연속 6줄) 영역을 찾는다. 없으면 빈 리스트."""
    regions: List[TabStaffRegion] = []
    for page_index, page in enumerate(extract_pages(pdf_path)):
        lines = _horizontal_lines(page)
        ys = sorted(set(round(line.y0, 1) for line in lines))
        raw_groups = _group_evenly_spaced(ys)
        # 5줄 그룹은 노이즈로 탈취된 6번째 줄 복구 시도
        groups = [_try_extend_to_six(g, ys) if len(g) == 5 else g for g in raw_groups]
        groups = [g for g in groups if len(g) == _TAB_STRING_COUNT]
        # 페이지 내 읽는 순서(위→아래) = 그룹의 최상단 y좌표 내림차순
        groups.sort(key=lambda g: g[-1], reverse=True)
        for group in groups:
            line_ys = sorted(group, reverse=True)  # [위, ..., 아래]
            regions.append(TabStaffRegion(page_index=page_index, line_ys=line_ys))
    return regions


_DIGIT_MERGE_GAP = 4.0  # 같은 프렛 숫자로 합칠 최대 글자 간격(pt)
_DIGITS = set("0123456789")


@dataclasses.dataclass
class TabNote:
    string: int
    fret: int


@dataclasses.dataclass
class _CharBox:
    text: str
    x0: float
    x1: float
    y0: float


def _nearest_string(y: float, line_ys: List[float]) -> int:
    """y좌표에 가장 가까운 줄의 현 번호(1~6)를 반환한다."""
    distances = [abs(y - ly) for ly in line_ys]
    return distances.index(min(distances)) + 1


def _merge_digit_chars(chars: List[_CharBox]) -> List[List[_CharBox]]:
    """x좌표 순 숫자 글자를 인접한 것끼리 합쳐 토큰으로 만든다.

    'X'는 숫자가 아니므로 합쳐지지 않고 항상 단독 토큰이 된다.
    """
    tokens: List[List[_CharBox]] = []
    for ch in chars:
        if tokens:
            prev = tokens[-1][-1]
            gap = ch.x0 - prev.x1
            same_line = abs(ch.y0 - prev.y0) < 0.5
            if (
                same_line
                and gap < _DIGIT_MERGE_GAP
                and prev.text in _DIGITS
                and ch.text in _DIGITS
            ):
                tokens[-1].append(ch)
                continue
        tokens.append([ch])
    return tokens


def _extract_region_notes(chars: List[_CharBox], region: TabStaffRegion) -> List[TabNote]:
    """영역 안 글자 목록(정렬 불필요)에서 좌→우 (현,프렛) 순서열을 만든다.

    'X'(뮤트)는 결과에서 제외한다.
    """
    ordered = sorted(chars, key=lambda c: c.x0)
    notes: List[TabNote] = []
    for token in _merge_digit_chars(ordered):
        text = "".join(c.text for c in token)
        if text == "X":
            continue
        string = _nearest_string(token[0].y0, region.line_ys)
        notes.append(TabNote(string=string, fret=int(text)))
    return notes


def extract_tab_notes(pdf_path: str, regions: List[TabStaffRegion]) -> List[TabNote]:
    """탭보표 영역에서 (현, 프렛) 순서열을 보표 순서대로 추출한다."""
    notes: List[TabNote] = []
    pages = list(extract_pages(pdf_path))
    for region in regions:
        page = pages[region.page_index]
        margin = (region.line_ys[0] - region.line_ys[-1]) * _GROUP_TOLERANCE_RATIO
        y_min = region.line_ys[-1] - margin
        y_max = region.line_ys[0] + margin

        chars: List[_CharBox] = []

        def walk(obj):
            if isinstance(obj, LTChar):
                text = obj.get_text()
                if y_min <= obj.y0 <= y_max and (text in _DIGITS or text == "X"):
                    chars.append(_CharBox(text=text, x0=obj.x0, x1=obj.x1, y0=obj.y0))
            for child in getattr(obj, "_objs", []):
                walk(child)

        walk(page)
        notes.extend(_extract_region_notes(chars, region))

    return notes
