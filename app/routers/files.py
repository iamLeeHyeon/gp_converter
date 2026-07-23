from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File
from app.storage import get_storage

router = APIRouter(prefix="/files", tags=["files"])


@router.get("")
def list_files(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # gp5_path==""는 변환이 아직 안 끝났거나(진행 중) 실패해서 영영 안 채워진
    # 예약 레코드다(worker.py가 실패 시 File을 건드리지 않음) — 목록에 계속
    # 남으면 클릭해도 다운로드 못 하는 깨진 항목으로 영구 노출된다.
    files = (
        db.query(File)
        .filter(File.user_id == user.id, File.gp5_path != "")
        .order_by(File.created_at.desc())
        .all()
    )
    return [{"id": f.id, "name": f.name, "created_at": str(f.created_at)} for f in files]


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    f = db.query(File).filter_by(id=file_id, user_id=user.id).first()
    if not f:
        raise HTTPException(status_code=404, detail="파일 없음")
    storage = get_storage()
    if f.gp5_path and storage.exists(f.gp5_path):
        storage.delete(f.gp5_path)
    db.delete(f)
    db.commit()
