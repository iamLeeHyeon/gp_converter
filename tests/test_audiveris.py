import os
import pytest
from unittest.mock import patch
from app.pipeline.audiveris import pdf_to_musicxml, AudiverisError


def test_success(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        os.makedirs(out_dir, exist_ok=True)
        (out_dir / "in.mxl").write_bytes(b"PK\x03\x04fake")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        result = pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)
    assert result.endswith(".mxl")
    assert os.path.exists(result)


def test_no_output_raises(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        os.makedirs(out_dir, exist_ok=True)  # 아무 파일도 안 만듦
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        with pytest.raises(AudiverisError):
            pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)


def test_nonzero_exit_raises(tmp_path):
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        class R: returncode = 1; stdout = b""; stderr = b"boom"
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        with pytest.raises(AudiverisError):
            pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)


def test_multiple_mxl_outputs_pick_deterministically(tmp_path):
    """여러 .mxl 산출물이 있으면 파일시스템 순서에 의존하지 않고
    항상 같은(정렬된) 파일을 선택해야 한다."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"

    def fake_run(cmd, **kwargs):
        os.makedirs(out_dir, exist_ok=True)
        # 'b' 먼저 생성해 파일시스템(생성 순서) 의존 시 b가 먼저 나올 수 있게 한다.
        (out_dir / "b.mxl").write_bytes(b"PK\x03\x04second")
        (out_dir / "a.mxl").write_bytes(b"PK\x03\x04first")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        result = pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)

    assert result == str(out_dir / "a.mxl")
