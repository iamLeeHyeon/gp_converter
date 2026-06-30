import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
from app.pipeline.midi_export import gp5_to_midi

router = APIRouter(prefix="/files", tags=["export"])


@router.get("/{file_id}/download")
def download_gp5(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GP5 파일 다운로드."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    if not f.gp5_path or not os.path.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")
    return FileResponse(
        f.gp5_path,
        media_type="application/octet-stream",
        filename=f"{f.name}.gp5",
    )


@router.get("/{file_id}/export/midi")
def export_midi(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """GP5 → MIDI 변환 후 다운로드."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    if not f.gp5_path or not os.path.exists(f.gp5_path):
        raise HTTPException(status_code=404, detail="GP5 파일 없음")

    try:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".mid")
        os.close(tmp_fd)
        gp5_to_midi(f.gp5_path, tmp_path)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"MIDI 변환 실패: {e}")

    return FileResponse(
        tmp_path,
        media_type="audio/midi",
        filename=f"{f.name}.mid",
        background=None,  # FileResponse가 전송 후 파일 삭제하지 않음 (tmp는 OS가 정리)
    )
