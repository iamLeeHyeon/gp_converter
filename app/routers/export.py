import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File

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
