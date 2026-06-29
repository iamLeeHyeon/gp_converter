# guitar-tab-omr 통합 구현 플랜

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PDF에 탭 보표가 감지되면 Audiveris 대신 guitar-tab-omr subprocess로 OMR 처리하고 tokenText를 직접 GP5로 변환한다.

**Architecture:** `orchestrator.py`가 `detect_tab_staves`로 탭 감지 시 새 경로(`omr_tab.py` → `token_to_gp.py`)로 분기한다. 탭 없으면 기존 Audiveris 경로 그대로 유지한다. guitar-tab-omr은 subprocess로 실행하며 JSON I/O로 통신한다.

**Tech Stack:** PyMuPDF(fitz), PyGuitarPro 0.10.x, subprocess, Python 3.11+

## Global Constraints

- `GUITAR_OMR_DIR` 환경변수: guitar-tab-omr 레포 루트 경로 (필수)
- `GUITAR_OMR_MODEL_DIR` 환경변수: 로컬 모델 디렉토리 (선택, 없으면 HuggingFace 자동 다운)
- PyGuitarPro API: `Beat(voice=voice)`, `beat.status = BeatStatus.normal/rest` 필수 설정
- 기존 Audiveris 경로 변경 없음
- 알 수 없는 토큰은 경고 로그 후 스킵 (변환 중단 금지)
- 모든 clip 실패 시만 `GpConvertError` 발생

---

## File Map

| 상태 | 경로 | 역할 |
|------|------|------|
| 신규 | `app/pipeline/omr_tab.py` | PDF→이미지 crop→subprocess→tokenText 리스트 |
| 신규 | `app/pipeline/token_to_gp.py` | tokenText 파싱→PyGuitarPro Song→.gp5 저장 |
| 신규 | `tests/test_omr_tab.py` | omr_tab 단위 테스트 |
| 신규 | `tests/test_token_to_gp.py` | token_to_gp 단위 테스트 |
| 수정 | `requirements.txt` | pymupdf 추가 |
| 수정 | `app/pipeline/orchestrator.py` | 탭 감지 시 omr 경로 분기 |
| 수정 | `tests/test_orchestrator.py` | 새 분기 테스트 추가 |

---

## Task 1: pymupdf 추가 + omr_tab.py PDF→이미지 crop

**Files:**
- Modify: `requirements.txt`
- Create: `app/pipeline/omr_tab.py`
- Test: `tests/test_omr_tab.py`

**Interfaces:**
- Produces:
  - `crop_tab_systems(pdf_path: str, regions: List[TabStaffRegion], clips_dir: str) -> List[str]`
  - `OmrTabError(Exception)`

- [ ] **Step 1: requirements.txt에 pymupdf 추가**

```
# requirements.txt 끝에 추가
pymupdf>=1.24.0
```

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_omr_tab.py` 생성:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from app.pipeline.tab_reader import TabStaffRegion


def _make_regions():
    return [
        TabStaffRegion(page_index=0, line_ys=[700.0, 690.0, 680.0, 670.0, 660.0, 650.0]),
        TabStaffRegion(page_index=0, line_ys=[500.0, 490.0, 480.0, 470.0, 460.0, 450.0]),
    ]


def test_crop_tab_systems_saves_pngs(tmp_path):
    """각 region마다 PNG 파일이 생성돼야 한다."""
    from app.pipeline.omr_tab import crop_tab_systems

    regions = _make_regions()
    clips_dir = str(tmp_path / "clips")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_pixmap = MagicMock()
    mock_page.get_pixmap.return_value = mock_pixmap
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc):
        paths = crop_tab_systems("dummy.pdf", regions, clips_dir)

    assert len(paths) == 2
    assert paths[0].endswith("clip-1.png")
    assert paths[1].endswith("clip-2.png")
    assert mock_pixmap.save.call_count == 2


def test_crop_tab_systems_clips_dir_created(tmp_path):
    """clips_dir가 없어도 자동 생성돼야 한다."""
    from app.pipeline.omr_tab import crop_tab_systems

    clips_dir = str(tmp_path / "nonexistent" / "clips")
    regions = _make_regions()

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc):
        crop_tab_systems("dummy.pdf", regions, clips_dir)

    assert Path(clips_dir).exists()


def test_crop_uses_correct_page_index(tmp_path):
    """region.page_index로 올바른 페이지를 가져와야 한다."""
    from app.pipeline.omr_tab import crop_tab_systems

    regions = [
        TabStaffRegion(page_index=2, line_ys=[700.0, 690.0, 680.0, 670.0, 660.0, 650.0]),
    ]
    clips_dir = str(tmp_path / "clips")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc):
        crop_tab_systems("dummy.pdf", regions, clips_dir)

    mock_doc.__getitem__.assert_called_once_with(2)
```

- [ ] **Step 3: 테스트 실패 확인**

```bash
cd /Users/leehyeon/Desktop/projects/gp_converter
pytest tests/test_omr_tab.py -v
```
예상: `ImportError: cannot import name 'crop_tab_systems'`

- [ ] **Step 4: omr_tab.py 구현 (crop 부분)**

`app/pipeline/omr_tab.py` 생성:

```python
"""
PDF 탭 시스템 → guitar-tab-omr → tokenText 변환

guitar-tab-omr을 subprocess로 실행한다.
환경변수:
  GUITAR_OMR_DIR      (필수) guitar-tab-omr 레포 루트
  GUITAR_OMR_MODEL_DIR (선택) 로컬 모델 디렉토리
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import List

import fitz

from app.pipeline.tab_reader import TabStaffRegion

logger = logging.getLogger(__name__)


class OmrTabError(Exception):
    """guitar-tab-omr 처리 중 발생하는 오류."""


def _get_omr_dir() -> Path:
    omr_dir = os.environ.get("GUITAR_OMR_DIR")
    if not omr_dir:
        raise OmrTabError(
            "GUITAR_OMR_DIR 환경변수가 설정되지 않았습니다. "
            "guitar-tab-omr 레포 루트 경로를 지정하세요."
        )
    return Path(omr_dir)


def crop_tab_systems(
    pdf_path: str,
    regions: List[TabStaffRegion],
    clips_dir: str,
) -> List[str]:
    """각 TabStaffRegion을 PNG crop 이미지로 저장하고 경로 리스트를 반환한다.

    pdfminer y좌표(좌하단 원점) → pymupdf y좌표(좌상단 원점) 변환:
        y_mupdf = page_height - y_pdfminer
    """
    Path(clips_dir).mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_paths: List[str] = []

    try:
        for idx, region in enumerate(regions):
            page = doc[region.page_index]
            page_height = page.rect.height

            y_top_pm = max(region.line_ys)
            y_bot_pm = min(region.line_ys)
            staff_height = y_top_pm - y_bot_pm
            margin = staff_height * 0.5

            # pymupdf: y0=위(작은 값), y1=아래(큰 값)
            rect_y0 = page_height - (y_top_pm + margin)
            rect_y1 = page_height - (y_bot_pm - margin)

            rect = fitz.Rect(0, rect_y0, page.rect.width, rect_y1)
            rect = rect.intersect(page.rect)

            mat = fitz.Matrix(2.0, 2.0)  # 2x 해상도로 렌더링
            pix = page.get_pixmap(matrix=mat, clip=rect)

            img_path = str(Path(clips_dir) / f"clip-{idx + 1}.png")
            pix.save(img_path)
            image_paths.append(img_path)
    finally:
        doc.close()

    return image_paths
```

- [ ] **Step 5: 테스트 통과 확인**

```bash
pytest tests/test_omr_tab.py::test_crop_tab_systems_saves_pngs \
       tests/test_omr_tab.py::test_crop_tab_systems_clips_dir_created \
       tests/test_omr_tab.py::test_crop_uses_correct_page_index -v
```
예상: 3 passed

- [ ] **Step 6: 커밋**

```bash
git add requirements.txt app/pipeline/omr_tab.py tests/test_omr_tab.py
git commit -m "feat: omr_tab - PDF 탭 시스템 PNG crop (pymupdf)"
```

---

## Task 2: omr_tab.py subprocess 실행 + tokenText 반환

**Files:**
- Modify: `app/pipeline/omr_tab.py`
- Modify: `tests/test_omr_tab.py`

**Interfaces:**
- Consumes:
  - `crop_tab_systems(pdf_path, regions, clips_dir) -> List[str]` (Task 1)
- Produces:
  - `run_omr_tab(pdf_path: str, regions: List[TabStaffRegion], workdir: str) -> List[str]`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_omr_tab.py`에 추가:

```python
def _fake_predictions_json(tmp_path, token_texts):
    """predictions.json 내용을 반환하는 헬퍼."""
    return {
        "predictions": [
            {"clipId": f"clip-{i+1}", "tokenText": tt, "warnings": []}
            for i, tt in enumerate(token_texts)
        ]
    }


def _mock_subprocess_ok(tmp_path, token_texts):
    """subprocess.run 성공 mock: output_path에 predictions.json을 써준다."""
    def _side_effect(cmd, **kwargs):
        # cmd에서 --output-json 다음 인자가 output_path
        out_idx = cmd.index("--output-json") + 1
        out_path = cmd[out_idx]
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(_fake_predictions_json(tmp_path, token_texts)),
            encoding="utf-8",
        )
        result = MagicMock()
        result.returncode = 0
        return result
    return _side_effect


def test_run_omr_tab_returns_token_texts(tmp_path, monkeypatch):
    """OMR 성공 시 tokenText 리스트를 반환해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab

    monkeypatch.setenv("GUITAR_OMR_DIR", str(tmp_path / "omr_repo"))
    (tmp_path / "omr_repo" / "scripts").mkdir(parents=True)
    (tmp_path / "omr_repo" / "scripts" / "guitar_omr_infer.py").write_text("")

    regions = _make_regions()
    expected = ["TS_4_4\nBAR\nBEAT DUR_4 REST\nEND_BAR", "TS_4_4\nBAR\nBEAT DUR_4 N_S1_F0\nEND_BAR"]

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc), \
         patch("subprocess.run", side_effect=_mock_subprocess_ok(tmp_path, expected)):
        result = run_omr_tab("dummy.pdf", regions, str(tmp_path / "work"))

    assert result == expected


def test_run_omr_tab_missing_env_raises(tmp_path, monkeypatch):
    """GUITAR_OMR_DIR 미설정 시 OmrTabError가 발생해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab, OmrTabError

    monkeypatch.delenv("GUITAR_OMR_DIR", raising=False)
    with pytest.raises(OmrTabError, match="GUITAR_OMR_DIR"):
        run_omr_tab("dummy.pdf", _make_regions(), str(tmp_path))


def test_run_omr_tab_subprocess_failure_raises(tmp_path, monkeypatch):
    """subprocess 비정상 종료 시 OmrTabError가 발생해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab, OmrTabError

    monkeypatch.setenv("GUITAR_OMR_DIR", str(tmp_path / "omr_repo"))
    (tmp_path / "omr_repo" / "scripts").mkdir(parents=True)
    (tmp_path / "omr_repo" / "scripts" / "guitar_omr_infer.py").write_text("")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "model not found"

    with patch("fitz.open", return_value=mock_doc), \
         patch("subprocess.run", return_value=mock_result):
        with pytest.raises(OmrTabError, match="실패"):
            run_omr_tab("dummy.pdf", _make_regions(), str(tmp_path))


def test_run_omr_tab_all_clips_fail_raises(tmp_path, monkeypatch):
    """모든 clip이 tokenText 없으면 OmrTabError가 발생해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab, OmrTabError

    monkeypatch.setenv("GUITAR_OMR_DIR", str(tmp_path / "omr_repo"))
    (tmp_path / "omr_repo" / "scripts").mkdir(parents=True)
    (tmp_path / "omr_repo" / "scripts" / "guitar_omr_infer.py").write_text("")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc), \
         patch("subprocess.run", side_effect=_mock_subprocess_ok(tmp_path, ["", ""])):
        with pytest.raises(OmrTabError, match="모든 clip"):
            run_omr_tab("dummy.pdf", _make_regions(), str(tmp_path))
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_omr_tab.py::test_run_omr_tab_returns_token_texts -v
```
예상: `ImportError: cannot import name 'run_omr_tab'`

- [ ] **Step 3: omr_tab.py에 subprocess 기능 추가**

`app/pipeline/omr_tab.py`에 추가 (파일 끝에):

```python
def _write_manifest(clips_dir: str, image_paths: List[str]) -> str:
    manifest = {
        "clips": [
            {"id": f"clip-{i + 1}", "imagePath": p}
            for i, p in enumerate(image_paths)
        ]
    }
    manifest_path = str(Path(clips_dir) / "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    return manifest_path


def _run_inference(manifest_path: str, output_path: str, omr_dir: Path) -> None:
    infer_script = omr_dir / "scripts" / "guitar_omr_infer.py"
    if not infer_script.exists():
        raise OmrTabError(f"guitar_omr_infer.py not found: {infer_script}")

    cmd = [
        sys.executable,
        str(infer_script),
        "--input-json", manifest_path,
        "--output-json", output_path,
        "--device", "auto",
    ]

    model_dir = os.environ.get("GUITAR_OMR_MODEL_DIR")
    if model_dir:
        cmd += ["--model-dir", model_dir]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise OmrTabError(
            f"guitar_omr_infer.py 실패 (exit {result.returncode}): {result.stderr[:500]}"
        )


def run_omr_tab(
    pdf_path: str,
    regions: List[TabStaffRegion],
    workdir: str,
) -> List[str]:
    """PDF 탭 시스템 전체를 OMR로 처리해 tokenText 리스트를 반환한다.

    Parameters
    ----------
    pdf_path:
        입력 PDF 경로.
    regions:
        detect_tab_staves가 반환한 TabStaffRegion 리스트 (전 페이지).
    workdir:
        작업 디렉토리. clips/ 서브디렉토리에 이미지가 저장된다.

    Returns
    -------
    List[str]
        시스템 순서대로 정렬된 tokenText 리스트.

    Raises
    ------
    OmrTabError
        환경변수 미설정, subprocess 실패, 모든 clip 인식 실패 시.
    """
    omr_dir = _get_omr_dir()
    clips_dir = str(Path(workdir) / "clips")

    image_paths = crop_tab_systems(pdf_path, regions, clips_dir)
    if not image_paths:
        raise OmrTabError("크롭된 탭 시스템 이미지가 없습니다.")

    manifest_path = _write_manifest(clips_dir, image_paths)
    output_path = str(Path(workdir) / "predictions.json")
    _run_inference(manifest_path, output_path, omr_dir)

    with open(output_path, encoding="utf-8") as f:
        predictions_json = json.load(f)

    token_texts: List[str] = []
    for pred in predictions_json.get("predictions", []):
        token_text = pred.get("tokenText")
        if not token_text:
            logger.warning("clip %s tokenText 없음, 스킵", pred.get("clipId"))
            continue
        for w in pred.get("warnings", []):
            logger.warning("clip %s: %s", pred.get("clipId"), w)
        token_texts.append(token_text)

    if not token_texts:
        raise OmrTabError("모든 clip OMR 실패: 변환 불가")

    return token_texts
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_omr_tab.py -v
```
예상: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/omr_tab.py tests/test_omr_tab.py
git commit -m "feat: omr_tab - subprocess 실행 및 tokenText 반환"
```

---

## Task 3: token_to_gp.py 토큰 파서

**Files:**
- Create: `app/pipeline/token_to_gp.py`
- Create: `tests/test_token_to_gp.py`

**Interfaces:**
- Produces:
  - `_BeatData` dataclass: `duration_value: int`, `is_rest: bool`, `velocity: int`, `strum_down: Optional[bool]`, `notes: List[Tuple[int,int]]`
  - `_MeasureData` dataclass: `time_sig_num: int`, `time_sig_den: int`, `beats: List[_BeatData]`
  - `_parse_token_texts(token_texts: List[str]) -> List[_MeasureData]`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_token_to_gp.py` 생성:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_token_to_gp.py -v
```
예상: `ImportError: cannot import name '_parse_token_texts'`

- [ ] **Step 3: token_to_gp.py 파서 구현**

`app/pipeline/token_to_gp.py` 생성:

```python
"""
guitar-tab-omr tokenText → Guitar Pro 5 변환기

토큰 포맷:
  TS_4_4                           박자표 (분자_분모)
  BAR / END_BAR                    마디 경계
  DOUBLE_BAR                       겹세로줄 (무시)
  BEAT DUR_N [REST] [DYN_X] [BTECH_STRUM_DOWN|UP] [N_Ss_Ff ...]  비트
  DUR_{1|2|4|8|16|32}             음표 길이
  REST                             쉼표
  N_S{1-6}_F{0-24}                음표 (현, 프렛)
  DYN_{ppp|pp|p|mp|mf|f|ff|fff}  다이나믹
  BTECH_STRUM_{DOWN|UP}           스트럼 방향
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import guitarpro
import guitarpro.models as gpm
from guitarpro import Beat, Note, NoteType
from guitarpro.models import BeatStatus

logger = logging.getLogger(__name__)

_DUR_MAP = {"1": 1, "2": 2, "4": 4, "8": 8, "16": 16, "32": 32}
_DYN_MAP = {
    "ppp": 15, "pp": 31, "p": 47, "mp": 63,
    "mf": 79, "f": 95, "ff": 111, "fff": 127,
}
_NOTE_RE = re.compile(r"N_S(\d+)_F(\d+)$")


@dataclass
class _BeatData:
    duration_value: int = 4
    is_rest: bool = False
    velocity: int = 95
    strum_down: Optional[bool] = None
    notes: List[Tuple[int, int]] = field(default_factory=list)


@dataclass
class _MeasureData:
    time_sig_num: int = 4
    time_sig_den: int = 4
    beats: List[_BeatData] = field(default_factory=list)


def _parse_token_texts(token_texts: List[str]) -> List[_MeasureData]:
    """tokenText 리스트를 파싱해 마디 데이터 리스트를 반환한다."""
    measures: List[_MeasureData] = []
    current_ts_num, current_ts_den = 4, 4
    current_measure: Optional[_MeasureData] = None
    current_beat: Optional[_BeatData] = None

    def flush_beat() -> None:
        nonlocal current_beat
        if current_beat is not None and current_measure is not None:
            current_measure.beats.append(current_beat)
            current_beat = None

    def flush_measure() -> None:
        nonlocal current_measure
        if current_measure is not None:
            flush_beat()
            measures.append(current_measure)
            current_measure = None

    for token_text in token_texts:
        for line in token_text.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("TS_"):
                parts = line.split("_")
                if len(parts) == 3:
                    try:
                        current_ts_num = int(parts[1])
                        current_ts_den = int(parts[2])
                    except ValueError:
                        logger.warning("박자표 파싱 실패: %s", line)

            elif line == "BAR":
                flush_measure()
                current_measure = _MeasureData(
                    time_sig_num=current_ts_num,
                    time_sig_den=current_ts_den,
                )

            elif line == "END_BAR":
                flush_measure()

            elif line == "DOUBLE_BAR":
                pass

            elif line.startswith("BEAT"):
                flush_beat()
                if current_measure is None:
                    current_measure = _MeasureData(
                        time_sig_num=current_ts_num,
                        time_sig_den=current_ts_den,
                    )
                current_beat = _BeatData()
                tokens = line.split()[1:]
                for token in tokens:
                    if token.startswith("DUR_"):
                        val = token[4:]
                        if val in _DUR_MAP:
                            current_beat.duration_value = _DUR_MAP[val]
                        else:
                            logger.warning("알 수 없는 DUR 토큰: %s", token)

                    elif token == "REST":
                        current_beat.is_rest = True

                    elif token.startswith("DYN_"):
                        dyn = token[4:].lower()
                        if dyn in _DYN_MAP:
                            current_beat.velocity = _DYN_MAP[dyn]
                        else:
                            logger.warning("알 수 없는 DYN 토큰: %s", token)

                    elif token == "BTECH_STRUM_DOWN":
                        current_beat.strum_down = True

                    elif token == "BTECH_STRUM_UP":
                        current_beat.strum_down = False

                    else:
                        m = _NOTE_RE.match(token)
                        if m:
                            current_beat.notes.append((int(m.group(1)), int(m.group(2))))
                        else:
                            logger.warning("알 수 없는 토큰 스킵: %s", token)

    flush_measure()
    return measures
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_token_to_gp.py -v
```
예상: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/token_to_gp.py tests/test_token_to_gp.py
git commit -m "feat: token_to_gp - tokenText 파서 구현"
```

---

## Task 4: token_to_gp.py PyGuitarPro GP5 조립

**Files:**
- Modify: `app/pipeline/token_to_gp.py`
- Modify: `tests/test_token_to_gp.py`

**Interfaces:**
- Consumes:
  - `_parse_token_texts(token_texts) -> List[_MeasureData]` (Task 3)
- Produces:
  - `token_texts_to_gp5(token_texts: List[str], out_path: str) -> str`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_token_to_gp.py`에 추가:

```python
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
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_token_to_gp.py::test_token_texts_to_gp5_creates_file -v
```
예상: `ImportError: cannot import name 'token_texts_to_gp5'`

- [ ] **Step 3: token_to_gp.py에 GP5 조립 함수 추가**

`app/pipeline/token_to_gp.py` 끝에 추가:

```python
def _build_gp5_song(measures: List[_MeasureData]) -> guitarpro.Song:
    song = gpm.Song()
    track = song.tracks[0]
    track.name = "Guitar"

    def _fill_measure(measure: gpm.Measure, mdata: _MeasureData) -> None:
        voice = measure.voices[0]
        voice.beats = []
        for bdata in mdata.beats:
            beat = Beat(voice)
            beat.duration = gpm.Duration()
            beat.duration.value = bdata.duration_value

            if bdata.is_rest or not bdata.notes:
                beat.status = BeatStatus.rest
                beat.notes = []
            else:
                beat.status = BeatStatus.normal
                for string_num, fret_num in bdata.notes:
                    gnote = Note(beat)
                    gnote.value = fret_num
                    gnote.string = string_num
                    gnote.type = NoteType.normal
                    gnote.velocity = bdata.velocity
                    beat.notes.append(gnote)

            voice.beats.append(beat)

        if not voice.beats:
            beat = Beat(voice)
            beat.status = BeatStatus.rest
            beat.duration = gpm.Duration()
            beat.duration.value = 4
            beat.notes = []
            voice.beats.append(beat)

    first_mh = song.measureHeaders[0]
    first_mh.number = 1
    first_mh.timeSignature.numerator = measures[0].time_sig_num
    first_mh.timeSignature.denominator.value = measures[0].time_sig_den
    _fill_measure(track.measures[0], measures[0])

    start = first_mh.start + first_mh.length
    for i, mdata in enumerate(measures[1:], start=2):
        mh = gpm.MeasureHeader()
        mh.number = i
        mh.start = start
        mh.timeSignature.numerator = mdata.time_sig_num
        mh.timeSignature.denominator.value = mdata.time_sig_den
        song.measureHeaders.append(mh)

        m = gpm.Measure(track, mh)
        _fill_measure(m, mdata)
        track.measures.append(m)

        start += mh.length

    return song


def token_texts_to_gp5(token_texts: List[str], out_path: str) -> str:
    """tokenText 리스트를 파싱해 .gp5 파일로 저장하고 경로를 반환한다.

    Raises
    ------
    ValueError
        파싱된 마디가 없는 경우.
    """
    measures = _parse_token_texts(token_texts)
    if not measures:
        raise ValueError("파싱된 마디가 없습니다.")
    song = _build_gp5_song(measures)
    guitarpro.write(song, out_path)
    return out_path
```

- [ ] **Step 4: 테스트 통과 확인**

```bash
pytest tests/test_token_to_gp.py -v
```
예상: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add app/pipeline/token_to_gp.py tests/test_token_to_gp.py
git commit -m "feat: token_to_gp - PyGuitarPro GP5 조립 완성"
```

---

## Task 5: orchestrator.py 탭 감지 시 OMR 경로 분기

**Files:**
- Modify: `app/pipeline/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes:
  - `run_omr_tab(pdf_path, regions, workdir) -> List[str]` (Task 2)
  - `token_texts_to_gp5(token_texts, out_path) -> str` (Task 4)
  - `OmrTabError` (Task 1)

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_orchestrator.py`에 추가:

```python
from app.pipeline.omr_tab import OmrTabError
from app.pipeline.tab_reader import TabStaffRegion


def test_tab_detected_uses_omr_path(tmp_path):
    """탭 보표 감지 시 Audiveris 대신 OMR 경로를 사용해야 한다."""
    from app.pipeline.orchestrator import run_conversion

    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.run_omr_tab", return_value=["TS_4_4\nBAR\nBEAT DUR_4 REST\nEND_BAR"]) as omr_mock, \
         patch("app.pipeline.orchestrator.token_texts_to_gp5", return_value=str(workdir / "out.gp5")) as gp_mock, \
         patch("app.pipeline.orchestrator.pdf_to_musicxml") as audiveris_mock:

        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    assert result == str(workdir / "out.gp5")
    omr_mock.assert_called_once()
    gp_mock.assert_called_once()
    audiveris_mock.assert_not_called()


def test_tab_omr_failure_propagates(tmp_path):
    """OMR 실패 시 OmrTabError가 상위로 전파돼야 한다."""
    import pytest
    from app.pipeline.orchestrator import run_conversion

    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.run_omr_tab", side_effect=OmrTabError("모델 실패")):
        with pytest.raises(OmrTabError):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)


def test_no_tab_uses_audiveris_path(tmp_path):
    """탭 보표 없으면 기존 Audiveris 경로를 사용해야 한다."""
    from app.pipeline.orchestrator import run_conversion

    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as audiveris_mock, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")), \
         patch("app.pipeline.orchestrator.run_omr_tab") as omr_mock:

        run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    audiveris_mock.assert_called_once()
    omr_mock.assert_not_called()
```

- [ ] **Step 2: 테스트 실패 확인**

```bash
pytest tests/test_orchestrator.py::test_tab_detected_uses_omr_path -v
```
예상: `ImportError` 또는 `AssertionError` (omr_mock not called)

- [ ] **Step 3: orchestrator.py 수정**

`app/pipeline/orchestrator.py` 전체 교체:

> **참고:** `test_tab_hints_passed_when_regions_detected`는 기존 동작(탭 감지 시 Audiveris+hints)을 가정한다. 새 설계에서는 탭 감지 시 OMR 경로로 가므로 이 테스트를 **삭제**한다.

```python
import logging
import os
from app.pipeline.audiveris import pdf_to_musicxml
from app.pipeline.musicxml_to_gp import musicxml_to_gp5
from app.pipeline.omr_tab import run_omr_tab
from app.pipeline.token_to_gp import token_texts_to_gp5
from app.pipeline.tab_reader import detect_tab_staves

logger = logging.getLogger(__name__)


def run_conversion(pdf_path: str, workdir: str, audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> str:
    """PDF→.gp5 전 과정을 실행하고 .gp5 경로를 반환한다.

    탭보표가 감지되면 guitar-tab-omr OMR 경로를 사용한다.
    탭보표가 없거나 감지 실패 시 Audiveris 경로(기존 동작)로 폴백한다.
    """
    gp5_path = os.path.join(workdir, "output.gp5")

    tab_regions = None
    try:
        tab_regions = detect_tab_staves(pdf_path)
    except Exception as e:
        logger.warning("탭 인식 실패, 휴리스틱으로 폴백: %s", e)

    if tab_regions:
        token_texts = run_omr_tab(pdf_path, tab_regions, workdir)
        return token_texts_to_gp5(token_texts, gp5_path)

    xml_dir = os.path.join(workdir, "xml")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)
    return musicxml_to_gp5(xml_path, gp5_path, timeout=timeout, tab_hints=None)
```

`tests/test_orchestrator.py`에서 `test_tab_hints_passed_when_regions_detected` 함수를 **삭제**한다 (탭 감지 시 OMR 경로를 사용하므로 Audiveris+hints 테스트는 불필요).

- [ ] **Step 4: 전체 테스트 통과 확인**

```bash
pytest tests/test_orchestrator.py tests/test_omr_tab.py tests/test_token_to_gp.py -v
```
예상: 전체 passed

- [ ] **Step 5: 기존 테스트도 통과하는지 확인**

```bash
pytest --ignore=tests/test_integration.py -v
```
예상: 전체 passed (test_integration.py는 실제 PDF 필요)

- [ ] **Step 6: 커밋**

```bash
git add app/pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: orchestrator - 탭 감지 시 guitar-tab-omr OMR 경로 분기"
```
