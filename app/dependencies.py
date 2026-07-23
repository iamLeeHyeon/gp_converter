from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from typing import Optional
from app.auth import decode_token
from app.config import Settings
from app.database import get_db
from app.jobs import JobStore
from app.models import User

_bearer = HTTPBearer()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_store(settings: Settings = Depends(get_settings)) -> JobStore:
    return JobStore(settings.jobs_dir, ttl_hours=settings.job_ttl_hours)


def _access_user(token: str, db: Session) -> Optional[User]:
    """access 토큰을 디코드해 해당 유저를 조회한다. 실패 시 None."""
    try:
        payload = decode_token(token)
    except jwt.InvalidTokenError:
        return None
    if payload.get("type") != "access":
        return None
    return db.query(User).filter(User.id == payload["sub"]).first()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_optional_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Authorization 헤더가 없거나 토큰이 유효하지 않으면 None 반환 (비로그인 허용)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    return _access_user(auth.split(" ", 1)[1], db)
