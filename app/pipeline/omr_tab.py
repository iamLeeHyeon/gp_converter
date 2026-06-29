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
