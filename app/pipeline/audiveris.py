import glob
import os
import subprocess


class AudiverisError(Exception):
    pass


def pdf_to_musicxml(pdf_path: str, out_dir: str, audiveris_cmd: str, timeout: int) -> str:
    """PDF를 MusicXML(.mxl/.xml)로 변환하고 산출 파일 경로를 반환한다."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = [audiveris_cmd, "-batch", "-export", "-output", out_dir, "--", pdf_path]
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
