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
