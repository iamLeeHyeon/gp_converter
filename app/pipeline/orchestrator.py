import os
from app.pipeline.audiveris import pdf_to_musicxml
from app.pipeline.musicxml_to_gp import musicxml_to_gp5


def run_conversion(pdf_path: str, workdir: str, audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> str:
    """PDF→MusicXML→.gp5 전 과정을 실행하고 .gp5 경로를 반환한다."""
    xml_dir = os.path.join(workdir, "xml")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)
    gp5_path = os.path.join(workdir, "output.gp5")
    return musicxml_to_gp5(xml_path, gp5_path, timeout=timeout)
