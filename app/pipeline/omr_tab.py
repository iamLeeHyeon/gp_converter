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
            # 상단: 리듬 스템이 TAB 위 공간(5선보-TAB 사이)에 있으므로 충분히 확보
            top_margin = staff_height * 1.5
            bot_margin = staff_height * 0.5

            # pymupdf: y0=위(작은 값), y1=아래(큰 값)
            rect_y0 = page_height - (y_top_pm + top_margin)
            rect_y1 = page_height - (y_bot_pm - bot_margin)

            page_bounds = fitz.Rect(0, 0, page.rect.width, page_height)
            rect = fitz.Rect(0, rect_y0, page.rect.width, rect_y1)
            rect = rect.intersect(page_bounds)

            mat = fitz.Matrix(2.0, 2.0)  # 2x 해상도로 렌더링
            pix = page.get_pixmap(matrix=mat, clip=rect)

            img_path = str(Path(clips_dir) / f"clip-{idx + 1}.png")
            pix.save(img_path)
            image_paths.append(img_path)
    finally:
        doc.close()

    return image_paths


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


def _run_inference(manifest_path: str, output_path: str, omr_dir: Path, timeout: int = 0) -> None:
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
    else:
        model_repo = os.environ.get("GUITAR_OMR_MODEL_REPO", "kk9293/guitar-tab-omr")
        cmd += ["--model-repo", model_repo]

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout if timeout > 0 else None,
    )
    if result.returncode != 0:
        raise OmrTabError(
            f"guitar_omr_infer.py 실패 (exit {result.returncode}): {result.stderr[:500]}"
        )


def run_omr_tab(
    pdf_path: str,
    regions: List[TabStaffRegion],
    workdir: str,
    timeout: int = 0,
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
    _run_inference(manifest_path, output_path, omr_dir, timeout=timeout)

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
