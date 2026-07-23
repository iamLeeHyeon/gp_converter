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


def test_zero_timeout_means_unlimited(tmp_path):
    """timeout=0은 omr_tab.py._run_inference와 동일한 관례로 '무제한'을
    의미해야 한다 — 지금까지는 subprocess.run(timeout=0)에 그대로 넘겨져서
    0초 대기 후 즉시 TimeoutExpired가 나버렸다(실제로는 timeout=0이 호출될
    일이 거의 없어서 발동하진 않았지만, 두 함수 간 관례가 어긋나 있었다)."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        os.makedirs(out_dir, exist_ok=True)
        (out_dir / "in.mxl").write_bytes(b"PK\x03\x04fake")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=0)

    assert captured["timeout"] is None


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


def test_includes_pdf_resolution_constant(tmp_path):
    """디폴트 해상도는 일부 음표(플래그·노트헤드)를 오인식하므로 400dpi로 올려서
    호출해야 한다. 실제 검증: 같은 PDF를 디폴트/400dpi로 각각 돌려보니 400dpi에서
    8분음표 꼬리를 화음으로 오인식하던 게 정확히 고쳐짐."""
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    out_dir = tmp_path / "out"
    captured_cmd = {}

    def fake_run(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        os.makedirs(out_dir, exist_ok=True)
        (out_dir / "in.mxl").write_bytes(b"PK\x03\x04fake")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.audiveris.subprocess.run", side_effect=fake_run):
        pdf_to_musicxml(str(pdf), str(out_dir), audiveris_cmd="audiveris", timeout=10)

    cmd = captured_cmd["cmd"]
    idx = cmd.index("-constant")
    assert cmd[idx + 1] == "org.audiveris.omr.image.ImageLoading.pdfResolution=400"


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
