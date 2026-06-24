import os
import subprocess


class TuxGuitarError(Exception):
    pass


def _build_cmd(tuxguitar_cmd: str, xml_path: str, gp5_path: str) -> list:
    # Task 0b 스파이크에서 확정한 실제 변환 명령으로 맞춘다.
    return [tuxguitar_cmd, "--convert", xml_path, gp5_path]


def musicxml_to_gp5(xml_path: str, gp5_path: str, tuxguitar_cmd: str, timeout: int) -> str:
    """MusicXML을 .gp5로 변환하고 출력 경로를 반환한다."""
    cmd = _build_cmd(tuxguitar_cmd, xml_path, gp5_path)
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise TuxGuitarError("gp 생성 시간 초과") from e
    if proc.returncode != 0:
        raise TuxGuitarError(f"gp 생성 실패 (exit {proc.returncode})")
    if not os.path.exists(gp5_path) or os.path.getsize(gp5_path) == 0:
        raise TuxGuitarError("gp 생성 실패: 출력 파일 없음")
    return gp5_path
