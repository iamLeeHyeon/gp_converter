import glob
import math
import os
import subprocess


class AudiverisError(Exception):
    pass


# 목표 해상도. PDF 페이지가 커서 Audiveris 20M픽셀 한도를 초과하면
# _safe_dpi()가 자동으로 낮춰준다.
_PDF_RESOLUTION_DPI = 400
_AUDIVERIS_MAX_PIXELS = 20_000_000


def _safe_dpi(pdf_path: str) -> int:
    """PDF 최대 페이지 크기 기준으로 Audiveris 픽셀 한도 이내 DPI를 반환한다."""
    try:
        from pdfminer.high_level import extract_pages
        from pdfminer.layout import LTPage
        max_area = 0.0
        for page in extract_pages(pdf_path):
            if isinstance(page, LTPage):
                area = (page.width / 72) * (page.height / 72)
                max_area = max(max_area, area)
        if max_area > 0:
            max_dpi = int(math.sqrt(_AUDIVERIS_MAX_PIXELS / max_area))
            return min(_PDF_RESOLUTION_DPI, max_dpi)
    except Exception:
        pass
    return _PDF_RESOLUTION_DPI


def pdf_to_musicxml(pdf_path: str, out_dir: str, audiveris_cmd: str, timeout: int) -> str:
    """PDF를 MusicXML(.mxl/.xml)로 변환하고 산출 파일 경로를 반환한다."""
    os.makedirs(out_dir, exist_ok=True)
    dpi = _safe_dpi(pdf_path)
    cmd = [
        audiveris_cmd,
        "-batch",
        "-export",
        "-constant",
        f"org.audiveris.omr.image.ImageLoading.pdfResolution={dpi}",
        "-output",
        out_dir,
        "--",
        pdf_path,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AudiverisError("악보 인식 시간 초과") from e
    if proc.returncode != 0:
        raise AudiverisError(f"악보 인식 실패 (exit {proc.returncode})")
    # 파일시스템 순서에 의존하지 않도록 각 그룹을 정렬한다. .mxl을 .xml보다 우선한다.
    matches = sorted(glob.glob(os.path.join(out_dir, "**", "*.mxl"), recursive=True)) \
        + sorted(glob.glob(os.path.join(out_dir, "**", "*.xml"), recursive=True))
    if not matches:
        raise AudiverisError("악보 인식 실패: MusicXML 산출물 없음")
    return matches[0]
