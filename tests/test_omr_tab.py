import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from app.pipeline.tab_reader import TabStaffRegion


def _make_regions():
    return [
        TabStaffRegion(page_index=0, line_ys=[700.0, 690.0, 680.0, 670.0, 660.0, 650.0]),
        TabStaffRegion(page_index=0, line_ys=[500.0, 490.0, 480.0, 470.0, 460.0, 450.0]),
    ]


def test_crop_tab_systems_saves_pngs(tmp_path):
    """각 region마다 PNG 파일이 생성돼야 한다."""
    from app.pipeline.omr_tab import crop_tab_systems

    regions = _make_regions()
    clips_dir = str(tmp_path / "clips")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_pixmap = MagicMock()
    mock_page.get_pixmap.return_value = mock_pixmap
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc):
        paths = crop_tab_systems("dummy.pdf", regions, clips_dir)

    assert len(paths) == 2
    assert paths[0].endswith("clip-1.png")
    assert paths[1].endswith("clip-2.png")
    assert mock_pixmap.save.call_count == 2


def test_crop_tab_systems_clips_dir_created(tmp_path):
    """clips_dir가 없어도 자동 생성돼야 한다."""
    from app.pipeline.omr_tab import crop_tab_systems

    clips_dir = str(tmp_path / "nonexistent" / "clips")
    regions = _make_regions()

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc):
        crop_tab_systems("dummy.pdf", regions, clips_dir)

    assert Path(clips_dir).exists()


def test_crop_uses_correct_page_index(tmp_path):
    """region.page_index로 올바른 페이지를 가져와야 한다."""
    from app.pipeline.omr_tab import crop_tab_systems

    regions = [
        TabStaffRegion(page_index=2, line_ys=[700.0, 690.0, 680.0, 670.0, 660.0, 650.0]),
    ]
    clips_dir = str(tmp_path / "clips")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc):
        crop_tab_systems("dummy.pdf", regions, clips_dir)

    mock_doc.__getitem__.assert_called_once_with(2)


# ---------------------------------------------------------------------------
# Task 2: run_omr_tab 테스트
# ---------------------------------------------------------------------------

def _fake_predictions_json(tmp_path, token_texts):
    """predictions.json 내용을 반환하는 헬퍼."""
    return {
        "predictions": [
            {"clipId": f"clip-{i+1}", "tokenText": tt, "warnings": []}
            for i, tt in enumerate(token_texts)
        ]
    }


def _mock_subprocess_ok(tmp_path, token_texts):
    """subprocess.run 성공 mock: output_path에 predictions.json을 써준다."""
    def _side_effect(cmd, **kwargs):
        # cmd에서 --output-json 다음 인자가 output_path
        out_idx = cmd.index("--output-json") + 1
        out_path = cmd[out_idx]
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(
            json.dumps(_fake_predictions_json(tmp_path, token_texts)),
            encoding="utf-8",
        )
        result = MagicMock()
        result.returncode = 0
        return result
    return _side_effect


def test_run_omr_tab_returns_token_texts(tmp_path, monkeypatch):
    """OMR 성공 시 tokenText 리스트를 반환해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab

    monkeypatch.setenv("GUITAR_OMR_DIR", str(tmp_path / "omr_repo"))
    (tmp_path / "omr_repo" / "scripts").mkdir(parents=True)
    (tmp_path / "omr_repo" / "scripts" / "guitar_omr_infer.py").write_text("")

    regions = _make_regions()
    expected = ["TS_4_4\nBAR\nBEAT DUR_4 REST\nEND_BAR", "TS_4_4\nBAR\nBEAT DUR_4 N_S1_F0\nEND_BAR"]

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc), \
         patch("subprocess.run", side_effect=_mock_subprocess_ok(tmp_path, expected)):
        result = run_omr_tab("dummy.pdf", regions, str(tmp_path / "work"))

    assert result == expected


def test_run_omr_tab_missing_env_raises(tmp_path, monkeypatch):
    """GUITAR_OMR_DIR 미설정 시 OmrTabError가 발생해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab, OmrTabError

    monkeypatch.delenv("GUITAR_OMR_DIR", raising=False)
    with pytest.raises(OmrTabError, match="GUITAR_OMR_DIR"):
        run_omr_tab("dummy.pdf", _make_regions(), str(tmp_path))


def test_run_omr_tab_subprocess_failure_raises(tmp_path, monkeypatch):
    """subprocess 비정상 종료 시 OmrTabError가 발생해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab, OmrTabError

    monkeypatch.setenv("GUITAR_OMR_DIR", str(tmp_path / "omr_repo"))
    (tmp_path / "omr_repo" / "scripts").mkdir(parents=True)
    (tmp_path / "omr_repo" / "scripts" / "guitar_omr_infer.py").write_text("")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "model not found"

    with patch("fitz.open", return_value=mock_doc), \
         patch("subprocess.run", return_value=mock_result):
        with pytest.raises(OmrTabError, match="실패"):
            run_omr_tab("dummy.pdf", _make_regions(), str(tmp_path))


def test_run_omr_tab_all_clips_fail_raises(tmp_path, monkeypatch):
    """모든 clip이 tokenText 없으면 OmrTabError가 발생해야 한다."""
    from app.pipeline.omr_tab import run_omr_tab, OmrTabError

    monkeypatch.setenv("GUITAR_OMR_DIR", str(tmp_path / "omr_repo"))
    (tmp_path / "omr_repo" / "scripts").mkdir(parents=True)
    (tmp_path / "omr_repo" / "scripts" / "guitar_omr_infer.py").write_text("")

    mock_doc = MagicMock()
    mock_page = MagicMock()
    mock_page.rect.height = 841.0
    mock_page.rect.width = 595.0
    mock_page.get_pixmap.return_value = MagicMock()
    mock_doc.__getitem__ = MagicMock(return_value=mock_page)

    with patch("fitz.open", return_value=mock_doc), \
         patch("subprocess.run", side_effect=_mock_subprocess_ok(tmp_path, ["", ""])):
        with pytest.raises(OmrTabError, match="모든 clip"):
            run_omr_tab("dummy.pdf", _make_regions(), str(tmp_path))
