import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User, File

router = APIRouter(prefix="/files", tags=["share"])


class ShareCreateRequest(BaseModel):
    expires_in_days: Optional[Literal[7, 30]] = 7


def _share_response(f: File) -> dict:
    return {
        "token": f.shared_token,
        "expires_at": f.shared_expires_at.isoformat() if f.shared_expires_at else None,
    }


def _get_owned_file(file_id: str, user: User, db: Session) -> File:
    f = db.query(File).filter_by(id=file_id).first()
    if f is None:
        raise HTTPException(status_code=404, detail="파일 없음")
    if f.user_id != user.id:
        raise HTTPException(status_code=403, detail="접근 금지")
    return f


@router.post("/{file_id}/share")
def create_share_link(
    file_id: str,
    body: ShareCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """공유 링크 생성 (기존 링크 있으면 덮어씀 — 파일당 1개)."""
    f = _get_owned_file(file_id, user, db)
    f.shared_token = secrets.token_urlsafe(24)
    f.shared_expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.expires_in_days)
        if body.expires_in_days is not None else None
    )
    db.commit()
    db.refresh(f)
    return _share_response(f)


@router.get("/{file_id}/share")
def get_share_status(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 공유 상태 조회 (링크 없으면 token: null)."""
    f = _get_owned_file(file_id, user, db)
    return _share_response(f)


@router.delete("/{file_id}/share", status_code=204)
def revoke_share_link(
    file_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """공유 중단."""
    f = _get_owned_file(file_id, user, db)
    f.shared_token = None
    f.shared_expires_at = None
    db.commit()
