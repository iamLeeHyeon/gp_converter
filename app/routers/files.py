from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
import os

router = APIRouter(prefix="/files", tags=["files"])


@router.get("")
def list_files(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    files = db.query(File).filter_by(user_id=user.id).order_by(File.created_at.desc()).all()
    return [{"id": f.id, "name": f.name, "created_at": str(f.created_at)} for f in files]


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter_by(id=file_id, user_id=user.id).first()
    if not f:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.gp5_path and os.path.exists(f.gp5_path):
        os.remove(f.gp5_path)
    db.delete(f)
    db.commit()
