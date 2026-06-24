import os
from unittest.mock import patch
from app.pipeline.orchestrator import run_conversion
from app.pipeline.audiveris import AudiverisError


def test_happy_path(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", return_value="x.mxl") as a, \
         patch("app.pipeline.orchestrator.musicxml_to_gp5", return_value=str(workdir / "out.gp5")) as t:
        result = run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    assert result == str(workdir / "out.gp5")
    a.assert_called_once()
    t.assert_called_once()


def test_audiveris_failure_propagates(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")
    workdir = tmp_path / "work"
    workdir.mkdir()

    with patch("app.pipeline.orchestrator.pdf_to_musicxml", side_effect=AudiverisError("악보 인식 실패")):
        import pytest
        with pytest.raises(AudiverisError):
            run_conversion(str(pdf), str(workdir), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)
