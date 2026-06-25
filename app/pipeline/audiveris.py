import glob
import os
import subprocess


class AudiverisError(Exception):
    pass


# 디폴트 해상도(보통 300dpi)에서는 8분음표 꼬리(플래그)를 별도 노트헤드로
# 오인식해 화음으로 잘못 읽는 경우가 실측으로 확인됐다(예: 1개 음을
# 2개짜리 화음+박자 다른 음표로 오인식). 400dpi로 올리면 해당 사례가
# 정확히 고쳐진다. 단, 다른 페이지에서 인식이 달라질 수도 있어 만능은 아님.
_PDF_RESOLUTION_DPI = 400


def pdf_to_musicxml(pdf_path: str, out_dir: str, audiveris_cmd: str, timeout: int) -> str:
    """PDF를 MusicXML(.mxl/.xml)로 변환하고 산출 파일 경로를 반환한다."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        audiveris_cmd,
        "-batch",
        "-export",
        "-constant",
        f"org.audiveris.omr.image.ImageLoading.pdfResolution={_PDF_RESOLUTION_DPI}",
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
