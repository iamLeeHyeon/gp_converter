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
from pdfminer.layout import LTLine, LTPage, LTCurve, LTRect

_MIN_LINE_WIDTH = 30.0  # 보표선으로 볼 최소 폭(짧은 장식선/빔 제외)
_GROUP_TOLERANCE_MIN = 1.0  # 등간격 판정 최소 허용오차(pt)
_GROUP_TOLERANCE_RATIO = 0.3  # 첫 간격 기준 허용오차 비율
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


def detect_tab_staves(pdf_path: str) -> List[TabStaffRegion]:
    """PDF에서 탭보표(연속 6줄) 영역을 찾는다. 없으면 빈 리스트."""
    regions: List[TabStaffRegion] = []
    for page_index, page in enumerate(extract_pages(pdf_path)):
        lines = _horizontal_lines(page)
        ys = sorted(set(round(line.y0, 1) for line in lines))
        groups = [g for g in _group_evenly_spaced(ys) if len(g) == _TAB_STRING_COUNT]
        # 페이지 내 읽는 순서(위→아래) = 그룹의 최상단 y좌표 내림차순
        groups.sort(key=lambda g: g[-1], reverse=True)
        for group in groups:
            line_ys = sorted(group, reverse=True)  # [위, ..., 아래]
            regions.append(TabStaffRegion(page_index=page_index, line_ys=line_ys))
    return regions
