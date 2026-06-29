import os
from datetime import datetime, timedelta, timezone
import jwt

_SECRET = os.environ["JWT_SECRET_KEY"]
_ALGO = "HS256"
_ACCESS_MINUTES = 15
_REFRESH_DAYS = 7


def create_access_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=_ACCESS_MINUTES)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "access"}, _SECRET, algorithm=_ALGO)


def create_refresh_token(user_id: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=_REFRESH_DAYS)
    return jwt.encode({"sub": user_id, "exp": exp, "type": "refresh"}, _SECRET, algorithm=_ALGO)


def decode_token(token: str) -> dict:
    return jwt.decode(token, _SECRET, algorithms=[_ALGO])
