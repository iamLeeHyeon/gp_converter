import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import httpx
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import create_access_token, create_refresh_token, decode_token
from app.config import Settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import User
from app.rate_limit import rate_limit
from app.tasks import send_verification_email_task, send_reset_email_task
from app.utils import as_utc

router = APIRouter(prefix="/auth", tags=["auth"])

try:
    _GOOGLE_ID = os.environ["GOOGLE_CLIENT_ID"]
    _GOOGLE_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
except KeyError as e:
    raise ValueError(
        f"필수 환경변수 누락: {e}. .env 파일 또는 환경변수를 설정하세요."
    ) from e

_settings = Settings()
_FRONTEND = _settings.frontend_url
_BACKEND = _settings.backend_url


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
        existing = db.query(User).filter_by(email=info["email"]).first()
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"이미 {existing.provider.capitalize()}로 가입된 이메일입니다. "
                       f"{existing.provider.capitalize()} 로그인을 사용하세요.",
            )
        user = User(email=info["email"], provider="google", provider_id=str(info["id"]))
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


class RegisterRequest(BaseModel):
    email: str
    password: str


@router.post("/register")
def register(body: RegisterRequest, db: Session = Depends(get_db), _=Depends(rate_limit("register"))):
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    existing = db.query(User).filter_by(email=body.email).first()
    if existing:
        if existing.provider != "password":
            raise HTTPException(
                status_code=400,
                detail=f"이미 {existing.provider.capitalize()}로 가입된 이메일입니다. "
                       f"{existing.provider.capitalize()} 로그인을 사용하세요.",
            )
        raise HTTPException(status_code=400, detail="이미 가입된 이메일입니다.")

    password_hash = bcrypt.hashpw(body.password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    token = secrets.token_urlsafe(32)
    user = User(
        email=body.email,
        provider="password",
        provider_id=body.email,
        password_hash=password_hash,
        email_verified=False,
        verification_token=token,
        verification_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    send_verification_email_task.delay(user.id)

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


@router.get("/verify")
def verify_email(token: str, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(verification_token=token).first()
    if not user or not user.verification_token_expires_at:
        return RedirectResponse(f"{_FRONTEND}/login?verify=expired")

    if as_utc(user.verification_token_expires_at) < datetime.now(timezone.utc):
        return RedirectResponse(f"{_FRONTEND}/login?verify=expired")

    user.email_verified = True
    user.verification_token = None
    user.verification_token_expires_at = None
    db.commit()
    return RedirectResponse(f"{_FRONTEND}/login?verify=success")


class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/resend-verification")
def resend_verification(body: ResendVerificationRequest, db: Session = Depends(get_db), _=Depends(rate_limit("resend-verification"))):
    user = db.query(User).filter_by(email=body.email, provider="password").first()
    if user and not user.email_verified:
        user.verification_token = secrets.token_urlsafe(32)
        user.verification_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        db.commit()
        send_verification_email_task.delay(user.id)
    return {"message": "인증 이메일이 발송되었으면 잠시 후 확인해주세요."}


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginRequest, db: Session = Depends(get_db), _=Depends(rate_limit("login"))):
    user = db.query(User).filter_by(email=body.email, provider="password").first()
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")
    if not bcrypt.checkpw(body.password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise HTTPException(status_code=401, detail="이메일 또는 비밀번호가 올바르지 않습니다.")

    return {
        "access_token": create_access_token(user.id),
        "refresh_token": create_refresh_token(user.id),
    }


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "email": current_user.email,
        "plan": current_user.plan,
        "email_verified": current_user.email_verified,
    }


class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db), _=Depends(rate_limit("forgot-password"))):
    user = db.query(User).filter_by(email=body.email, provider="password").first()
    if user:
        user.reset_token = secrets.token_urlsafe(32)
        user.reset_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.commit()
        send_reset_email_task.delay(user.id)
    return {"message": "메일이 발송되었으면 잠시 후 확인해주세요."}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password")
def reset_password(body: ResetPasswordRequest, db: Session = Depends(get_db), _=Depends(rate_limit("reset-password"))):
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")

    user = db.query(User).filter_by(reset_token=body.token).first()
    if not user or not user.reset_token_expires_at:
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")

    if as_utc(user.reset_token_expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="유효하지 않거나 만료된 토큰입니다.")

    user.password_hash = bcrypt.hashpw(body.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user.reset_token = None
    user.reset_token_expires_at = None
    db.commit()
    return {"message": "비밀번호가 변경되었습니다."}
