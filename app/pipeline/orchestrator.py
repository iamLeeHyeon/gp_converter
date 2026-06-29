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

    탭보표가 감지됐으나 OMR이 실패(OmrTabError)하면 Audiveris로 폴백하지 않고
    그대로 에러를 전파한다 — 탭을 잘못 인식한 오선보 결과보다 명시적 실패가 낫다.
    """
    gp5_path = os.path.join(workdir, "output.gp5")

    tab_regions = None
    try:
        tab_regions = detect_tab_staves(pdf_path)
    except Exception as e:
        logger.warning("탭 인식 실패, 휴리스틱으로 폴백: %s", e)

    if tab_regions:
        token_texts = run_omr_tab(pdf_path, tab_regions, workdir, timeout=timeout)
        return token_texts_to_gp5(token_texts, gp5_path)

    xml_dir = os.path.join(workdir, "xml")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)
    return musicxml_to_gp5(xml_path, gp5_path, timeout=timeout, tab_hints=None)
