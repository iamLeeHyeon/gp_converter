import os
import tempfile
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
from app.pipeline.token_to_gp import snapshot_to_gp5
from app.storage import get_storage

router = APIRouter(prefix="/files", tags=["edit"])


@router.post("/{file_id}/sync")
def sync_file(
    file_id: str,
    snapshot: dict,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """ScoreSnapshot JSON → GP5 재생성 후 저장."""
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix='.gp5')
    os.close(tmp_fd)
    try:
        try:
            snapshot_to_gp5(snapshot, tmp_path)
        except (ValueError, KeyError, TypeError) as e:
            raise HTTPException(status_code=422, detail=str(e))

        storage = get_storage()
        storage.save_file(f.gp5_path, tmp_path)
    finally:
        os.unlink(tmp_path)

    return {"ok": True}
