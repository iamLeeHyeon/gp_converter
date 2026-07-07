import os
from unittest.mock import patch
from app.pipeline.orchestrator import run_conversion
from app.pipeline.audiveris import AudiverisError
from app.pipeline.musicxml_to_gp import GpConvertError
from app.pipeline.omr_tab import OmrTabError
from app.pipeline.tab_reader import TabStaffRegion, TabNote


def test_happy_path(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as a, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as t:
        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert result == str(workdir / "out.gp5")
    a.assert_called_once()
    t.assert_called_once()


def test_audiveris_failure_propagates(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", side_effect=AudiverisError("악보 인식 실패")):
        import pytest
        with pytest.raises(AudiverisError):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)


def test_gpconvert_failure_propagates(tmp_path):
    import pytest
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", side_effect=GpConvertError("gp 생성 실패")):
        with pytest.raises(GpConvertError):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)


def test_tab_detected_uses_omr_path(tmp_path):
    """탭 보표 감지 시 Audiveris 대신 OMR 경로를 사용해야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])
    real_notes = [TabNote(string=1, fret=0), TabNote(string=3, fret=5)]

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.extract_tab_notes", return_value=real_notes), \
         patch("app.pipeline.orchestrator.run_omr_tab", return_value=["TS_4_4\nBAR\nBEAT DUR_4 REST\nEND_BAR"]) as omr_mock, \
         patch("app.pipeline.orchestrator.token_texts_to_gp5", return_value=str(workdir / "out.gp5")) as gp_mock, \
         patch("app.pipeline.orchestrator.pdf_to_musicxml") as audiveris_mock:

        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert result == str(workdir / "out.gp5")
    omr_mock.assert_called_once()
    gp_mock.assert_called_once()
    audiveris_mock.assert_not_called()


def test_tab_omr_failure_propagates(tmp_path):
    """OMR 실패 시 OmrTabError가 상위로 전파돼야 한다."""
    import pytest
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])
    real_notes = [TabNote(string=1, fret=0), TabNote(string=3, fret=5)]

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.extract_tab_notes", return_value=real_notes), \
         patch("app.pipeline.orchestrator.run_omr_tab", side_effect=OmrTabError("모델 실패")):
        with pytest.raises(OmrTabError):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)


def test_no_tab_uses_audiveris_path(tmp_path):
    """탭 보표 없으면 기존 Audiveris 경로를 사용해야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as audiveris_mock, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")), \
         patch("app.pipeline.orchestrator.run_omr_tab") as omr_mock:

        run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    audiveris_mock.assert_called_once()
    omr_mock.assert_not_called()


def test_tab_hints_none_when_no_regions_detected(tmp_path):
    """탭보표가 검출되지 않으면 기존 동작과 동일하게 tab_hints=None으로 호출돼야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[]), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as gp:
        run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    _, kwargs = gp.call_args
    assert kwargs["tab_hints"] is None


def test_tab_reader_exception_falls_back_to_none(tmp_path):
    """tab_reader가 예외를 던져도 변환 자체는 실패하지 않고 tab_hints=None으로 폴백해야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.detect_tab_staves", side_effect=RuntimeError("pdfminer 파싱 실패")), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as gp:
        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert result == str(workdir / "out.gp5")
    _, kwargs = gp.call_args
    assert kwargs["tab_hints"] is None


def test_tab_reader_exception_is_logged(tmp_path, caplog):
    """탭 인식 실패 시 조용히 넘어가지 않고 사유가 로그로 남아야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl"), \
         patch("app.pipeline.orchestrator.detect_tab_staves", side_effect=RuntimeError("pdfminer 파싱 실패")), \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")):
        with caplog.at_level("WARNING", logger="app.pipeline.orchestrator"):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert len(caplog.records) == 1
    assert "pdfminer 파싱 실패" in caplog.records[0].message


def test_false_positive_tab_region_falls_back_to_audiveris(tmp_path):
    """탭보표로 감지됐어도 프렛숫자가 전부 같은 한 현에만 몰려있으면(오탐지 신호)
    Audiveris 경로로 폴백해야 한다.

    Rêverie PDF 실사례 재현: 오선보 위 마디번호가 우연히 보표 줄 간격과 같은
    위치에 있어 6번째 탭선으로 오탐지됨 — 이 상태로 OMR을 돌리면 실제 오선보
    내용 전체가 유실되고 마디번호에서 뽑아낸 의미없는 결과만 남는다.
    """
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=1, line_ys=[784.6, 779.3, 774.1, 769.0, 763.9, 758.8])
    false_positive_notes = [TabNote(string=1, fret=4), TabNote(string=1, fret=8)]

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.extract_tab_notes", return_value=false_positive_notes), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as audiveris_mock, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")), \
         patch("app.pipeline.orchestrator.run_omr_tab") as omr_mock:

        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert result == str(workdir / "out.gp5")
    audiveris_mock.assert_called_once()
    omr_mock.assert_not_called()


def test_real_tab_region_with_multiple_strings_still_uses_omr(tmp_path):
    """프렛숫자가 여러 현에 걸쳐 있으면(진짜 탭 신호) 기존대로 OMR 경로를 써야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])
    real_notes = [TabNote(string=1, fret=0), TabNote(string=3, fret=5)]

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.extract_tab_notes", return_value=real_notes), \
         patch("app.pipeline.orchestrator.run_omr_tab", return_value=["TS_4_4\nBAR\nBEAT DUR_4 REST\nEND_BAR"]) as omr_mock, \
         patch("app.pipeline.orchestrator.token_texts_to_gp5", return_value=str(workdir / "out.gp5")), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml") as audiveris_mock:

        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert result == str(workdir / "out.gp5")
    omr_mock.assert_called_once()
    audiveris_mock.assert_not_called()


def test_extract_tab_notes_exception_falls_back_to_audiveris(tmp_path):
    """오탐지 검증 단계(extract_tab_notes) 자체가 예외를 던져도 변환은 실패하지
    않고 Audiveris로 안전하게 폴백해야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    fake_region = TabStaffRegion(page_index=0, line_ys=[6, 5, 4, 3, 2, 1])

    with patch("app.pipeline.orchestrator.detect_tab_staves", return_value=[fake_region]), \
         patch("app.pipeline.orchestrator.extract_tab_notes", side_effect=RuntimeError("파싱 실패")), \
         patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as audiveris_mock, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")), \
         patch("app.pipeline.orchestrator.run_omr_tab") as omr_mock:

        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", timeout=10)

    assert result == str(workdir / "out.gp5")
    audiveris_mock.assert_called_once()
    omr_mock.assert_not_called()
