import logging
import os
from app.pipeline.audiveris import pdf_to_musicxml
from app.pipeline.musicxml_to_gp import musicxml_to_gp5
from app.pipeline.tab_reader import detect_tab_staves, extract_tab_notes

logger = logging.getLogger(__name__)


def run_conversion(pdf_path: str, workdir: str, audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> str:
    """PDF→MusicXML→.gp5 전 과정을 실행하고 .gp5 경로를 반환한다.

    탭보표가 검출되면 탭에서 읽은 (현,프렛)을 휴리스틱 대신 사용한다.
    탭 인식 경로의 어떤 실패(검출 실패/추출 예외)도 변환 자체를 막지 않고
    tab_hints=None으로 폴백한다(기존 휴리스틱 동작과 동일하게 진행). 폴백 사유는
    경고 로그로 남긴다 — 그래야 운영자가 소스를 안 읽고도 원인을 알 수 있다.
    """
    xml_dir = os.path.join(workdir, "xml")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)

    tab_hints = None
    try:
        regions = detect_tab_staves(pdf_path)
        if regions:
            tab_notes = extract_tab_notes(pdf_path, regions)
            tab_hints = [(n.string, n.fret) for n in tab_notes]
    except Exception as e:
        logger.warning("탭 인식 실패, 휴리스틱으로 폴백: %s", e)
        tab_hints = None

    gp5_path = os.path.join(workdir, "output.gp5")
    return musicxml_to_gp5(xml_path, gp5_path, timeout=timeout, tab_hints=tab_hints)
