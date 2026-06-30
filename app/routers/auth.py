import os
import jwt
import secrets
import httpx
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import create_access_token, create_refresh_token, decode_token
from app.database import get_db
from app.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

try:
    _GOOGLE_ID = os.environ["GOOGLE_CLIENT_ID"]
    _GOOGLE_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
    _GITHUB_ID = os.environ["GITHUB_CLIENT_ID"]
    _GITHUB_SECRET = os.environ["GITHUB_CLIENT_SECRET"]
except KeyError as e:
    raise ValueError(
        f"필수 환경변수 누락: {e}. .env 파일 또는 환경변수를 설정하세요."
    ) from e

_FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:5173")
_BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")


@router.get("/google")
def google_login():
    state = secrets.token_urlsafe(16)
    params = urlencode({
        "response_type": "code",
        "client_id": _GOOGLE_ID,
        "redirect_uri": f"{_BACKEND}/auth/google/callback",
        "scope": "openid email profile",
        "state": state,
    })
    response = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
    response.set_cookie("oauth_state", state, httponly=True, samesite="lax", max_age=600)
    return response


@router.get("/google/callback")
async def google_callback(request: Request, code: str, state: str = "", db: Session = Depends(get_db)):
    stored_state = request.cookies.get("oauth_state", "")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="invalid state")
    async with httpx.AsyncClient() as c:
        tok_resp = await c.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": _GOOGLE_ID, "client_secret": _GOOGLE_SECRET,
            "redirect_uri": f"{_BACKEND}/auth/google/callback",
            "grant_type": "authorization_code",
        })
        tok_resp.raise_for_status()
        tok = tok_resp.json()
        if "error" in tok:
            raise HTTPException(status_code=400, detail=f"OAuth error: {tok.get('error_description', tok['error'])}")

        info_resp = await c.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {tok['access_token']}"},
        )
        info_resp.raise_for_status()
        info = info_resp.json()

    user = db.query(User).filter_by(provider="google", provider_id=str(info["id"])).first()
    if not user:
        user = User(email=info["email"], provider="google", provider_id=str(info["id"]))
        db.add(user)
        db.commit()
        db.refresh(user)

    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return RedirectResponse(f"{_FRONTEND}/auth/callback#access_token={access}&refresh_token={refresh}")


@router.get("/github")
def github_login():
    state = secrets.token_urlsafe(16)
    params = urlencode({
        "client_id": _GITHUB_ID,
        "redirect_uri": f"{_BACKEND}/auth/github/callback",
        "scope": "user:email",
        "state": state,
    })
    response = RedirectResponse(f"https://github.com/login/oauth/authorize?{params}")
    response.set_cookie("oauth_state", state, httponly=True, samesite="lax", max_age=600)
    return response


@router.get("/github/callback")
async def github_callback(request: Request, code: str, state: str = "", db: Session = Depends(get_db)):
    stored_state = request.cookies.get("oauth_state", "")
    if not stored_state or stored_state != state:
        raise HTTPException(status_code=400, detail="invalid state")
    async with httpx.AsyncClient() as c:
        tok_resp = await c.post(
            "https://github.com/login/oauth/access_token",
            data={"client_id": _GITHUB_ID, "client_secret": _GITHUB_SECRET,
                  "code": code, "redirect_uri": f"{_BACKEND}/auth/github/callback"},
            headers={"Accept": "application/json"},
        )
        tok_resp.raise_for_status()
        tok = tok_resp.json()
        if "error" in tok:
            raise HTTPException(status_code=400, detail=f"OAuth error: {tok.get('error_description', tok['error'])}")

        info_resp = await c.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {tok['access_token']}", "Accept": "application/json"},
        )
        info_resp.raise_for_status()
        info = info_resp.json()

        emails_resp = await c.get(
            "https://api.github.com/user/emails",
            headers={"Authorization": f"Bearer {tok['access_token']}", "Accept": "application/json"},
        )
        emails_resp.raise_for_status()
        emails = emails_resp.json()

    primary_email = next((e["email"] for e in emails if e.get("primary")), info.get("email", ""))
    provider_id = str(info["id"])

    user = db.query(User).filter_by(provider="github", provider_id=provider_id).first()
    if not user:
        user = User(email=primary_email, provider="github", provider_id=provider_id)
        db.add(user)
        db.commit()
        db.refresh(user)

    access = create_access_token(user.id)
    refresh = create_refresh_token(user.id)
    return RedirectResponse(f"{_FRONTEND}/auth/callback#access_token={access}&refresh_token={refresh}")


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/refresh")
def refresh_tokens(body: RefreshRequest):
    try:
        payload = decode_token(body.refresh_token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user_id = payload["sub"]
    return {
        "access_token": create_access_token(user_id),
        "refresh_token": create_refresh_token(user_id),
    }
