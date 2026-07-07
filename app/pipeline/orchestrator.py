import logging
import os
from app.pipeline.audiveris import pdf_to_musicxml
from app.pipeline.musicxml_to_gp import musicxml_to_gp5
from app.pipeline.omr_tab import run_omr_tab
from app.pipeline.token_to_gp import token_texts_to_gp5
from app.pipeline.tab_reader import detect_tab_staves, extract_tab_notes, has_multiple_strings

logger = logging.getLogger(__name__)


def run_conversion(
    pdf_path: str,
    workdir: str,
    audiveris_cmd: str,
    timeout: int,
    progress_callback=None,  # (pct: int, step: str) -> None
) -> str:
    """PDF→.gp5 전 과정을 실행하고 .gp5 경로를 반환한다.

    탭보표가 감지되면 guitar-tab-omr OMR 경로를 사용한다.
    탭보표가 없거나 감지 실패 시 Audiveris 경로(기존 동작)로 폴백한다.

    탭보표가 감지됐으나 OMR이 실패(OmrTabError)하면 Audiveris로 폴백하지 않고
    그대로 에러를 전파한다 — 탭을 잘못 인식한 오선보 결과보다 명시적 실패가 낫다.

    단, 감지된 영역에서 추출한 프렛숫자가 전부 같은 한 현에만 몰려있으면(마디번호나
    8va 표시선이 우연히 보표 줄 간격에 걸려 6번째 탭선으로 오탐지된 신호) OMR로
    넘기지 않고 Audiveris로 폴백한다 — 진짜 탭이라면 곡 전체에서 여러 현을
    오갔을 게 거의 확실하다.
    """
    gp5_path = os.path.join(workdir, "output.gp5")

    def _cb(pct: int, step: str):
        if progress_callback:
            progress_callback(pct, step)

    tab_regions = None
    try:
        tab_regions = detect_tab_staves(pdf_path)
        if tab_regions:
            candidate_notes = extract_tab_notes(pdf_path, tab_regions)
            if not has_multiple_strings(candidate_notes):
                logger.warning(
                    "탭보표로 감지된 영역이 전부 같은 현에만 몰려있어(오탐지 가능성) "
                    "Audiveris로 폴백합니다"
                )
                tab_regions = None
    except Exception as e:
        logger.warning("탭 인식 실패, 휴리스틱으로 폴백: %s", e)
        tab_regions = None

    _cb(10, "tab_detect")

    if tab_regions:
        _cb(30, "omr")
        token_texts = run_omr_tab(pdf_path, tab_regions, workdir, timeout=timeout)
        result = token_texts_to_gp5(token_texts, gp5_path)
        _cb(80, "gp5_build")
        return result

    xml_dir = os.path.join(workdir, "xml")
    _cb(30, "audiveris")
    xml_path = pdf_to_musicxml(pdf_path, xml_dir, audiveris_cmd=audiveris_cmd, timeout=timeout)
    _cb(80, "musicxml_convert")
    result = musicxml_to_gp5(xml_path, gp5_path, timeout=timeout, tab_hints=None)
    _cb(90, "gp5_build")
    return result
