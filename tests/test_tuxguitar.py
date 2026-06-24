import os
import pytest
from unittest.mock import patch
from app.pipeline.tuxguitar import musicxml_to_gp5, TuxGuitarError


def test_success(tmp_path):
    xml = tmp_path / "in.xml"
    xml.write_text("<score-partwise/>")
    out = tmp_path / "out.gp5"

    def fake_run(cmd, **kwargs):
        out.write_bytes(b"FICHIER GUITAR PRO v5.00")
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.tuxguitar.subprocess.run", side_effect=fake_run):
        result = musicxml_to_gp5(str(xml), str(out), tuxguitar_cmd="tuxguitar", timeout=10)
    assert result == str(out)
    assert os.path.exists(result) and os.path.getsize(result) > 0


def test_no_output_raises(tmp_path):
    xml = tmp_path / "in.xml"
    xml.write_text("<score-partwise/>")
    out = tmp_path / "out.gp5"

    def fake_run(cmd, **kwargs):
        class R: returncode = 0; stdout = b""; stderr = b""
        return R()

    with patch("app.pipeline.tuxguitar.subprocess.run", side_effect=fake_run):
        with pytest.raises(TuxGuitarError):
            musicxml_to_gp5(str(xml), str(out), tuxguitar_cmd="tuxguitar", timeout=10)


def test_nonzero_exit_raises(tmp_path):
    xml = tmp_path / "in.xml"
    xml.write_text("<score-partwise/>")
    out = tmp_path / "out.gp5"

    def fake_run(cmd, **kwargs):
        class R: returncode = 2; stdout = b""; stderr = b"err"
        return R()

    with patch("app.pipeline.tuxguitar.subprocess.run", side_effect=fake_run):
        with pytest.raises(TuxGuitarError):
            musicxml_to_gp5(str(xml), str(out), tuxguitar_cmd="tuxguitar", timeout=10)
