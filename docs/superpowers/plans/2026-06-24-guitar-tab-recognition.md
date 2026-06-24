# 기타 탭 PDF 인식 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 표준악보+탭보표가 함께 있는 디지털 PDF를 업로드하면, 탭에 명시된 정확한 (현,프렛)을 반영한 `.gp5`를 생성한다. 기존 표준악보 전용 MVP 동작은 그대로 유지한다.

**Architecture:** 기존 `Audiveris(표준악보→MusicXML) → music21 → PyGuitarPro` 파이프라인은 손대지 않는다. 신규 모듈 `app/pipeline/tab_reader.py`(pdfminer.six 기반)가 탭보표에서 (현,프렛) 순서열을 별도로 읽는다. `orchestrator.py`가 두 결과의 개수가 정확히 일치할 때만 1:1로 매칭해 `musicxml_to_gp5`에 명시적 힌트로 넘긴다. 불일치/예외 시 항상 기존 휴리스틱(최저프렛)으로 전체 폴백한다.

**Tech Stack:** 기존 스택(Python, music21, PyGuitarPro) + 신규 `pdfminer.six`(PDF 벡터선/글자 좌표 추출).

## Global Constraints

- 입력 범위: 디지털 탭 PDF만(스캔 이미지 제외), 표준악보(5선보)+탭보표(6선보)가 같은 시스템에 함께 있는 형태만 지원.
- 탭보표 감지는 **줄 개수(6줄)** 기준이며 절대 간격에 의존하지 않는다(소프트웨어마다 간격이 다름이 실측으로 확인됨).
- `X`(뮤트 표시)는 탭 순서열에서 스킵한다 — v1 한계.
- 표준악보 음표 개수와 탭 숫자 개수가 다르면 부분 매칭하지 않고 탭모드 전체를 포기, 휴리스틱으로 완전 폴백한다.
- 탭 인식 경로의 어떤 실패도 기존 변환 자체를 실패시키면 안 된다(항상 폴백).
- 설계 문서: `docs/superpowers/specs/2026-06-24-guitar-tab-recognition-design.md` (이미 커밋됨, 본 계획은 이 설계를 그대로 구현).

---

## 파일 구조

```
app/pipeline/
  tab_reader.py          # 신규: detect_tab_staves(), extract_tab_notes()
  musicxml_to_gp.py       # 수정: musicxml_to_gp5()에 tab_hints 파라미터 추가
  orchestrator.py         # 수정: tab_reader 결과를 musicxml_to_gp5에 연결
tests/
  test_tab_reader.py      # 신규
  test_musicxml_to_gp.py  # 수정: tab_hints override/fallback 테스트 추가
  test_orchestrator.py    # 수정: 탭 연동 모킹 테스트 추가
  test_integration.py     # 수정: 실제 Audiveris로 탭 우선 경로 검증 추가
  fixtures/
    tab_sample.ly          # 신규: LilyPond 소스(저작권 무관, 듀얼 표기)
    tab_sample.pdf          # 신규: 위 소스를 컴파일한 PDF
requirements.txt          # 수정: pdfminer.six 추가
README.md                  # 수정: "알려진 한계" 갱신
```

---

## Task 1: 의존성 추가 + 합성 탭 PDF 픽스처 생성

이후 모든 작업에서 쓸 실측 데이터를 만든다. 아래 LilyPond 소스는 이미 로컬에서 컴파일 → Audiveris(실제) → music21로 검증을 마쳤다(이 계획에 적힌 모든 좌표/숫자는 그 결과를 그대로 옮긴 것).

**Files:**
- Modify: `requirements.txt`
- Create: `tests/fixtures/tab_sample.ly`
- Create: `tests/fixtures/tab_sample.pdf`

- [ ] **Step 1: pdfminer.six 추가**

`requirements.txt`에 한 줄 추가:
```
pdfminer.six==20251107
```

- [ ] **Step 2: 설치 확인**

Run: `pip install -r requirements.txt && python -c "import pdfminer; print('ok')"`
Expected: `ok` 출력.

- [ ] **Step 3: LilyPond 픽스처 작성**

`tests/fixtures/tab_sample.ly` (C장조 음계 상행/하행을 2회 반복, 총 32음표. `e\2`는 LilyPond 문법으로 "이 음을 2번줄로 강제 운지"한다 — 표준 휴리스틱이라면 E4는 1번줄 0프렛을 고르지만, 탭에는 2번줄 5프렛으로 명시되어 있어 "탭 힌트가 실제로 휴리스틱을 덮어쓰는지"를 증명하는 데 쓴다):

```lilypond
\version "2.26.0"
\header { title = "Tab Test" tagline = ##f }
music = \relative c' {
  c4 d e\2 f | g a b c | c b a g | f e\2 d c |
  c4 d e\2 f | g a b c | c b a g | f e\2 d c
}
\score {
  <<
    \new Staff { \clef "treble" \time 4/4 \music }
    \new TabStaff { \music }
  >>
  \layout { }
}
```

- [ ] **Step 4: PDF 생성 (LilyPond 필요: `brew install lilypond`)**

Run:
```bash
cd tests/fixtures
lilypond tab_sample.ly
rm -f tab_sample.log
cd ../..
```
Expected: `tests/fixtures/tab_sample.pdf` 생성됨 (`tab_sample.log`는 LilyPond가 같이 만드는 빌드 로그라 삭제).

- [ ] **Step 5: 생성된 PDF로 실측 데이터 재확인**

Run:
```bash
python - <<'PY'
from pdfminer.high_level import extract_pages
from pdfminer.layout import LTLine, LTRect, LTCurve
page = next(extract_pages("tests/fixtures/tab_sample.pdf"))
lines = []
def walk(o):
    if isinstance(o, (LTLine, LTRect, LTCurve)) and abs(o.y0-o.y1) < 0.5 and (o.x1-o.x0) >= 30:
        lines.append(round(o.y0, 1))
    for c in getattr(o, "_objs", []):
        walk(c)
walk(page)
print(sorted(set(lines)))
PY
```
Expected: 6개 탭보표 줄과 5개 표준악보 줄이 보임. 6줄 그룹의 y좌표가 `[693.6, 701.1, 708.6, 716.1, 723.5, 731.0]` 근방이어야 한다(LilyPond/폰트 버전이 동일하면 정확히 일치). **이 값이 Task 2의 테스트 기댓값이다.**

- [ ] **Step 6: 커밋**

```bash
git add requirements.txt tests/fixtures/tab_sample.ly tests/fixtures/tab_sample.pdf
git commit -m "test: 탭 인식용 합성 PDF 픽스처 + pdfminer.six 의존성 추가"
```

---

## Task 2: 탭보표 자동 감지 (`detect_tab_staves`)

**Files:**
- Create: `app/pipeline/tab_reader.py`
- Create: `tests/test_tab_reader.py`

**Interfaces:**
- Produces: `TabStaffRegion(page_index: int, line_ys: List[float])` — `line_ys`는 위(1번현)→아래(6번현) 순으로 정렬된 6개 y좌표. `detect_tab_staves(pdf_path: str) -> List[TabStaffRegion]`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_tab_reader.py`:
```python
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_tab_reader.py -v`
Expected: FAIL (`No module named 'app.pipeline.tab_reader'`).

- [ ] **Step 3: 구현**

`app/pipeline/tab_reader.py`:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_tab_reader.py -v`
Expected: 3개 테스트 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/tab_reader.py tests/test_tab_reader.py
git commit -m "feat: 탭보표 자동 감지(detect_tab_staves) 구현"
```

---

## Task 3: 프렛 숫자 추출 (`extract_tab_notes`)

실측 중 발견한 문제: pdfminer의 기본 `LTTextLineHorizontal`(줄 단위 텍스트 그룹화)을 그대로 쓰면, 숫자 바로 옆에 붙은 비숫자 글리프(타이/바코드 등 음악 폰트 심볼, `(cid:0)` 같은 매핑 안 된 글리프)가 같은 텍스트 줄로 묶여 `'0 (cid:0)'` 같은 오염된 문자열이 되고, 그 안의 유효한 숫자가 통째로 누락되는 사례가 실제로 발생했다(`isdigit()` 검사를 통과 못 함). 그래서 줄 단위 그룹화를 쓰지 않고, **글자(`LTChar`) 단위에서 숫자(0-9)/`X`만 먼저 거른 뒤, 가까운 숫자끼리만 직접 합쳐 다중 자릿수(예: "10")를 만든다.** 비숫자 글리프는 필터링 단계에서 이미 제외되므로 숫자를 오염시킬 수 없다.

**Files:**
- Modify: `app/pipeline/tab_reader.py`
- Modify: `tests/test_tab_reader.py`

**Interfaces:**
- Consumes: `TabStaffRegion`(Task 2).
- Produces: `TabNote(string: int, fret: int)`. `extract_tab_notes(pdf_path: str, regions: List[TabStaffRegion]) -> List[TabNote]`.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_tab_reader.py`에 추가:
```python
from app.pipeline.tab_reader import (
    TabStaffRegion,
    TabNote,
    _CharBox,
    _extract_region_notes,
    extract_tab_notes,
)

# Task 1에서 실측 확인한 전체 탭 순서열 (32개).
# 3,11,18,26번째 음(E4)은 LilyPond 소스에서 `e\2`로 2번줄을 강제 지정했다 —
# 휴리스틱(최저프렛)이라면 1번줄 0프렛을 고르지만 탭에는 2번줄 5프렛으로 적혀 있다.
EXPECTED_TAB_NOTES = [
    (2, 1), (2, 3), (2, 5), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8),
    (1, 8), (1, 7), (1, 5), (1, 3), (1, 1), (2, 5), (2, 3), (2, 1),
    (2, 1), (2, 3), (2, 5), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8),
    (1, 8), (1, 7), (1, 5), (1, 3), (1, 1), (2, 5), (2, 3), (2, 1),
]


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
```

(파일 위쪽의 `from app.pipeline.tab_reader import _group_evenly_spaced, detect_tab_staves` 줄도 위 import로 합쳐서 한 번만 import하도록 정리한다.)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_tab_reader.py -v`
Expected: FAIL (`ImportError: cannot import name 'TabNote'`).

- [ ] **Step 3: 구현**

`app/pipeline/tab_reader.py`에 추가(파일 맨 위 import 줄에 `LTChar` 추가 필요):
```python
from pdfminer.layout import LTChar, LTLine, LTPage, LTCurve, LTRect
```

파일 끝에 추가:
```python
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
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_tab_reader.py -v`
Expected: 5개 테스트 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/tab_reader.py tests/test_tab_reader.py
git commit -m "feat: 탭 프렛 숫자 추출(extract_tab_notes) 구현"
```

---

## Task 4: `musicxml_to_gp5`에 탭 힌트 파라미터 추가

탭에서 뽑은 (현,프렛) 순서열이 음정 개수와 정확히 일치하면 휴리스틱 대신 그 값을 그대로 쓴다. 개수가 다르면 힌트를 무시하고 기존 동작과 완전히 동일하게 휴리스틱을 쓴다.

**Files:**
- Modify: `app/pipeline/musicxml_to_gp.py`
- Modify: `tests/test_musicxml_to_gp.py`

**Interfaces:**
- Consumes: 없음(자체 완결).
- Produces: `musicxml_to_gp5(xml_path: str, gp5_path: str, timeout: int = 0, tab_hints: Optional[List[Tuple[int, int]]] = None) -> str`. `tab_hints`는 `(현 번호, 프렛)` 튜플 목록이며, 음표 순서와 1:1 대응이어야 한다. Task 5(orchestrator)가 이 파라미터를 채워서 호출한다.

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_musicxml_to_gp.py`에 추가(파일 위쪽 import에 `Tuple` 불필요, 기존대로 둠):
```python
# sample.musicxml(EXPECTED_MIDI = [60,62,64,65,67,69,71,72])에서
# 기존 휴리스틱(최저프렛)이 실제로 고르는 (현,프렛)을 사람이 검증한 값:
#   60→(2,1) 62→(2,3) 64→(1,0) 65→(1,1) 67→(1,3) 69→(1,5) 71→(1,7) 72→(1,8)
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
    assert actual == [(2, 1), (2, 3), (1, 0), (1, 1), (1, 3), (1, 5), (1, 7), (1, 8)]
    assert actual != FAKE_TAB_HINTS[:5] + actual[5:]
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_musicxml_to_gp.py -v`
Expected: FAIL (`TypeError: musicxml_to_gp5() got an unexpected keyword argument 'tab_hints'`).

- [ ] **Step 3: 구현**

`app/pipeline/musicxml_to_gp.py`의 `_build_song`과 `musicxml_to_gp5`를 아래처럼 바꾼다(전체 교체):

```python
def _build_song(
    note_data: List[Tuple[int, float]],
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> guitarpro.Song:
    """(MIDI, quarterLength) 목록으로 GP Song 객체를 생성한다.

    tab_hints가 note_data와 길이가 같으면 각 음표에 명시적 (현,프렛)을 쓴다.
    길이가 다르면 tab_hints를 무시하고 기존 휴리스틱(최저프렛)을 쓴다.
    """
    if tab_hints is not None and len(tab_hints) != len(note_data):
        tab_hints = None

    song = gpm.Song()
    track = song.tracks[0]
    strings = [(s.number, s.value) for s in track.strings]

    hints = tab_hints if tab_hints is not None else [None] * len(note_data)
    items = list(zip(note_data, hints))

    # (음표,힌트) 쌍을 4/4 마디 단위로 그룹화
    measures_items: List[List[Tuple[Tuple[int, float], Optional[Tuple[int, int]]]]] = []
    current_bar: List[Tuple[Tuple[int, float], Optional[Tuple[int, int]]]] = []
    current_ql = 0.0

    for (midi, ql), hint in items:
        current_bar.append(((midi, ql), hint))
        current_ql += ql
        if current_ql >= _BAR_QL:
            measures_items.append(current_bar)
            current_bar = []
            current_ql = 0.0

    if current_bar:
        measures_items.append(current_bar)

    if not measures_items:
        return song

    first_mh = song.measureHeaders[0]
    first_measure = track.measures[0]

    def _fill_measure(measure: gpm.Measure, bar_items) -> None:
        voice = measure.voices[0]
        beats: List[Beat] = []
        for (midi, ql), hint in bar_items:
            if hint is not None:
                snum, fret = hint
            else:
                sf = _midi_to_string_fret(midi, strings)
                if sf is None:
                    # 범위 밖 음표는 건너뜀
                    continue
                snum, fret = sf
            gp_val, is_dotted = _ql_to_gp_duration(ql)

            beat = Beat(voice=voice)
            beat.status = BeatStatus.normal
            beat.duration.value = gp_val
            beat.duration.isDotted = is_dotted

            gnote = Note(beat=beat)
            gnote.value = fret
            gnote.string = snum
            gnote.type = NoteType.normal
            beat.notes = [gnote]
            beats.append(beat)
        voice.beats = beats

    _fill_measure(first_measure, measures_items[0])

    start = first_mh.start + first_mh.length
    for i, bar_items in enumerate(measures_items[1:], start=2):
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        song.measureHeaders.append(mh)

        m = gpm.Measure(track, mh)
        _fill_measure(m, bar_items)
        track.measures.append(m)

        start += mh.length

    return song


def musicxml_to_gp5(
    xml_path: str,
    gp5_path: str,
    timeout: int = 0,
    tab_hints: Optional[List[Tuple[int, int]]] = None,
) -> str:
    """MusicXML을 .gp5로 변환하고 출력 경로를 반환한다.

    Parameters
    ----------
    xml_path:
        입력 MusicXML(.musicxml 또는 .mxl) 파일 경로.
    gp5_path:
        출력 .gp5 파일 경로.
    timeout:
        오케스트레이터 호환용 파라미터. 순수 Python 구현이므로 사용하지 않는다.
    tab_hints:
        탭보표에서 읽은 (현 번호, 프렛) 목록. 음표 개수와 정확히 일치할 때만
        휴리스틱(최저프렛) 대신 그대로 쓴다. None이거나 개수가 다르면 무시한다.

    Returns
    -------
    str
        생성된 .gp5 파일의 경로.

    Raises
    ------
    GpConvertError
        음표가 없거나 파일 생성에 실패한 경우.
    """
    try:
        score = converter.parse(xml_path)
    except Exception as e:
        raise GpConvertError("gp 생성 실패") from e

    try:
        note_data = _collect_notes(score)
    except Exception as e:
        raise GpConvertError("gp 생성 실패") from e

    if not note_data:
        raise GpConvertError("변환할 음표 없음")

    try:
        song = _build_song(note_data, tab_hints=tab_hints)
        guitarpro.write(song, gp5_path)
    except Exception as e:
        raise GpConvertError("gp 생성 실패") from e

    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise GpConvertError("gp 생성 실패")

    return gp5_path
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_musicxml_to_gp.py -v`
Expected: 6개 테스트 모두 PASS(기존 4개 + 신규 2개).

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/musicxml_to_gp.py tests/test_musicxml_to_gp.py
git commit -m "feat: musicxml_to_gp5에 tab_hints 파라미터 추가(개수 불일치 시 폴백)"
```

---

## Task 5: orchestrator에 탭 인식 연동

**Files:**
- Modify: `app/pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `detect_tab_staves`, `extract_tab_notes`(Task 2/3), `musicxml_to_gp5(..., tab_hints=...)`(Task 4).
- Produces: `run_conversion(pdf_path, workdir, audiveris_cmd, tuxguitar_cmd, timeout) -> str` — 시그니처는 기존과 동일하게 유지(워커/API 변경 불필요).

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_orchestrator.py`에 추가:
```python
from app.pipeline.tab_reader import TabStaffRegion, TabNote


def test_tab_hints_passed_when_regions_detected(tmp_path):
    """탭보표가 검출되면 musicxml_to_gp5에 tab_hints가 채워져 전달돼야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])
    fake_notes = [TabNote(string=1, fret=0), TabNote(string=2, fret=1)]

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.extract_tab_notes", return_value=fake_notes), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as gp:
        run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    _, kwargs = gp.call_args
    assert kwargs["tab_hints"] == [(1, 0), (2, 1)]


def test_tab_hints_none_when_no_regions_detected(tmp_path):
    """탭보표가 검출되지 않으면 기존 동작과 동일하게 tab_hints=None으로 호출돼야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as gp:
        run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    _, kwargs = gp.call_args
    assert kwargs["tab_hints"] is None


def test_tab_reader_exception_falls_back_to_none(tmp_path):
    """tab_reader가 예외를 던져도 변환 자체는 실패하지 않고 tab_hints=None으로 폴백해야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.detect_tab_staves", side_effect=RuntimeError("pdfminer 파싱 실패")), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as gp:
        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    assert result == str(workdir / "out.gp5")
    _, kwargs = gp.call_args
    assert kwargs["tab_hints"] is None
```

(파일 위쪽에 이미 있는 `from unittest.mock import patch` 등 기존 import는 그대로 둔다.)

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_orchestrator.py -v`
Expected: FAIL (`ModuleNotFoundError` 또는 `AttributeError: <module 'app.pipeline.orchestrator'> does not have the attribute 'detect_tab_staves'` — patch 대상이 아직 없음).

- [ ] **Step 3: 구현**

`app/pipeline/orchestrator.py` 전체를 아래로 교체:
```python
import os
from app.pipeline.audiveris import pdf_to_musicxml
from app.pipeline.musicxml_to_gp import musicxml_to_gp5
from app.pipeline.tab_reader import detect_tab_staves, extract_tab_notes


def run_conversion(pdf_path: str, workdir: str, audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> str:
    """PDF→MusicXML→.gp5 전 과정을 실행하고 .gp5 경로를 반환한다.

    탭보표가 검출되면 탭에서 읽은 (현,프렛)을 휴리스틱 대신 사용한다.
    탭 인식 경로의 어떤 실패(검출 실패/추출 예외)도 변환 자체를 막지 않고
    tab_hints=None으로 폴백한다(기존 휴리스틱 동작과 동일하게 진행).
    """
    xml_dir = os.path.join(workdir, "xml")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)

    tab_hints = None
    try:
        regions = detect_tab_staves(pdf_path)
        if regions:
            tab_notes = extract_tab_notes(pdf_path, regions)
            tab_hints = [(n.string, n.fret) for n in tab_notes]
    except Exception:
        tab_hints = None

    gp5_path = os.path.join(workdir, "output.gp5")
    return musicxml_to_gp5(xml_path, gp5_path, timeout=timeout, tab_hints=tab_hints)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_orchestrator.py -v`
Expected: 6개 테스트 모두 PASS(기존 3개 + 신규 3개).

- [ ] **Step 5: 전체 단위테스트 회귀 확인**

Run: `pytest -v`
Expected: 모두 PASS(`-m integration`은 기본 제외이므로 실행 안 됨).

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator에 탭 인식 연동(검출 실패 시 항상 휴리스틱 폴백)"
```

---

## Task 6: 실제 Audiveris 통합 테스트 — 탭 우선 경로 검증

지금까지는 전부 모킹된 테스트다. 이 태스크는 `tab_sample.pdf`로 **실제** Audiveris를 돌려 전체 파이프라인이 탭 힌트를 실제로 사용하는지(휴리스틱이 아니라) 증명한다. `tab_sample.ly`의 E4 음들이 `e\2`(2번줄 강제)로 적혀 있어, 휴리스틱이라면 1번줄 0프렛을 골랐을 자리에 탭은 2번줄 5프렛을 명시한다 — 이 차이가 곧 "탭 힌트가 실제로 적용됐다"는 증거다.

**Files:**
- Modify: `tests/test_integration.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_integration.py`에 추가:
```python
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
        tuxguitar_cmd="unused",
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
```

- [ ] **Step 2: 실패 확인**

Run: `pytest -m integration tests/test_integration.py::test_pdf_with_tab_uses_tab_hints_not_heuristic -v`
Expected: FAIL (`AttributeError`/`NameError: TAB_FIXTURE`/`pytest.mark.integration` 자체는 있지만 fixture 경로나 import가 아직 안 맞을 수 있음 — Task 1~5가 이미 끝나 있으므로 보통은 이 자체로 PASS할 수도 있다. PASS하면 그대로 다음 단계로 진행).

- [ ] **Step 3: 실제 Audiveris로 실행해 결과 확인**

Run: `pytest -m integration tests/test_integration.py::test_pdf_with_tab_uses_tab_hints_not_heuristic -v`
Expected: PASS. 만약 `actual`이 `[(1,0),(1,2),(1,4),...]`처럼 전부 1번줄 휴리스틱 패턴으로 나오면 탭 인식이 폴백된 것이므로, Task 1~5 구현을 다시 점검한다(이 계획서에 적힌 좌표/숫자는 로컬 LilyPond 2.26.0 기준 실측값이라 LilyPond 버전이 다르면 `tab_sample.pdf`를 다시 생성해 Task 1 Step 5처럼 좌표를 재확인해야 한다).

- [ ] **Step 4: 전체 통합 테스트 회귀 확인**

Run: `pytest -m integration -v`
Expected: 기존 `test_pdf_to_gp5_real`과 신규 테스트 모두 PASS.

- [ ] **Step 5: 커밋**

```bash
git add tests/test_integration.py
git commit -m "test: 실제 Audiveris로 탭 힌트 우선 적용 통합 테스트 추가"
```

---

## Task 7: README 갱신

**Files:**
- Modify: `README.md`

- [ ] **Step 1: "동작 원리"에 탭 인식 한 줄 추가**

`README.md`의 입력 설명(현재 11번째 줄 "**입력:**") 바로 아래에 추가:
```markdown
- **탭(TAB) 인식:** 표준악보(5선보)와 탭보표(6선보)가 같은 시스템에 함께 있는 디지털 PDF라면, 탭에 적힌 정확한 현/프렛을 읽어 사용한다(휴리스틱 추정보다 정확). 탭보표가 없거나 숫자 추출 결과가 표준악보 음표 개수와 다르면 자동으로 기존 휴리스틱(최저프렛)으로 폴백한다.
```

- [ ] **Step 2: "알려진 한계" 갱신**

현재(109번째 줄 근처):
```markdown
- 기타 탭(TAB) 전용 PDF는 인식 정확도가 떨어진다(Audiveris는 표준 오선보 인식기). 별도 인식 경로는 추후 과제.
```
다음으로 교체:
```markdown
- 탭 인식은 디지털 PDF 한정이며, 표준악보 없이 탭보표만 있는 PDF, 스캔 이미지 탭, 화음(동시발음) 탭, 해머링/슬라이드 등 기법 기호는 지원하지 않는다(`X` 뮤트 표시는 스킵됨). 자세한 한계는 `docs/superpowers/specs/2026-06-24-guitar-tab-recognition-design.md` 참고.
```

- [ ] **Step 3: 커밋**

```bash
git add README.md
git commit -m "docs: 탭 인식 기능 README 반영"
```

---

## 셀프 리뷰 체크

- 설계 문서의 모든 컴포넌트(`detect_tab_staves`, `extract_tab_notes`, 정렬 매칭, orchestrator 연동, 에러 처리 폴백)에 대응하는 태스크가 있음 — Task 2,3,4,5.
- 설계 문서의 "한계" 섹션(X 스킵, 화음 범위 밖, 탭전용 PDF 미지원, 스캔 이미지 미지원)이 README에도 반영됨 — Task 7.
- 모든 좌표/숫자/MIDI 값은 실제 LilyPond 컴파일 + 실제 Audiveris 실행 + 실제 pdfminer.six 파싱으로 검증된 값이며, 추측치 없음.
- 타입/시그니처 일관성: `TabStaffRegion`, `TabNote`(Task 2,3) → `(n.string, n.fret)` 튜플 변환(Task 5) → `tab_hints: Optional[List[Tuple[int,int]]]`(Task 4) 흐름이 전 태스크에서 동일하게 유지됨.
