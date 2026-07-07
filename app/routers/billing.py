import os
from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import Settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import File, User

router = APIRouter(prefix="/billing", tags=["billing"])

try:
    _STRIPE_SECRET_KEY = os.environ["STRIPE_SECRET_KEY"]
    _STRIPE_WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
    _STRIPE_PRICE_ID_PRO = os.environ["STRIPE_PRICE_ID_PRO"]
except KeyError as e:
    raise ValueError(
        f"필수 환경변수 누락: {e}. .env 파일 또는 환경변수를 설정하세요."
    ) from e

stripe.api_key = _STRIPE_SECRET_KEY

_FRONTEND = Settings().frontend_url

FREE_CONVERSIONS_LIMIT = 3
FREE_FILES_LIMIT = 5


def count_usage(db: Session, user_id: str) -> tuple[int, int]:
    """(최근 30일 성공 변환 수, 저장된 파일 총개수) 반환.

    두 값 모두 gp5_path가 실제로 채워진(성공 변환) File 행만 카운트한다 —
    실패/대기 중이라 gp5_path=""로 남은 행은 어느 쪽에도 포함되지 않는다.
    차이는 시간 범위뿐이다: conversions_used는 최근 30일, files_used는 전체 기간.

    30일 컷오프는 timezone-naive UTC로 계산한다 — File.created_at이
    SQLite server_default(func.now())로 채워질 때 naive datetime 문자열로
    저장되므로, 비교 대상도 naive로 맞춰야 문자열 비교가 정확하다
    (aware datetime을 쓰면 오프셋 접미사 유무가 달라져서 문자열 비교가 깨짐).
    """
    cutoff = datetime.utcnow() - timedelta(days=30)
    conversions_used = (
        db.query(File)
        .filter(File.user_id == user_id, File.gp5_path != "", File.created_at >= cutoff)
        .count()
    )
    files_used = (
        db.query(File)
        .filter(File.user_id == user_id, File.gp5_path != "")
        .count()
    )
    return conversions_used, files_used


@router.post("/checkout")
def create_checkout_session(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Pro 구독 결제용 Stripe Checkout 세션 생성."""
    if not user.stripe_customer_id:
        customer = stripe.Customer.create(email=user.email)
        user.stripe_customer_id = customer.id
        db.commit()

    session = stripe.checkout.Session.create(
        customer=user.stripe_customer_id,
        mode="subscription",
        line_items=[{"price": _STRIPE_PRICE_ID_PRO, "quantity": 1}],
        success_url=f"{_FRONTEND}/?billing=success",
        cancel_url=f"{_FRONTEND}/?billing=cancel",
    )
    return {"url": session.url}


@router.post("/portal")
def create_portal_session(
    user: User = Depends(get_current_user),
):
    """구독 해지/카드변경용 Stripe Customer Portal 세션 생성."""
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="구독 정보가 없습니다")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{_FRONTEND}/",
    )
    return {"url": session.url}


@router.post("/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    """Stripe 웹훅 수신 — 인증 대신 서명 검증."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, _STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="잘못된 웹훅 서명")

    event_type = event["type"]
    obj = event["data"]["object"]
    customer_id = obj.get("customer")

    if customer_id:
        user = db.query(User).filter_by(stripe_customer_id=customer_id).first()
        if user:
            if event_type == "checkout.session.completed":
                user.plan = "pro"
            elif event_type == "customer.subscription.updated":
                user.plan = "pro" if obj.get("status") in ("active", "trialing") else "free"
            elif event_type == "customer.subscription.deleted":
                user.plan = "free"
            db.commit()

    return {"ok": True}


@router.get("/usage")
def get_usage(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """현재 플랜 + 사용량 조회."""
    conversions_used, files_used = count_usage(db, user.id)
    return {
        "plan": user.plan,
        "conversions_used": conversions_used,
        "conversions_limit": FREE_CONVERSIONS_LIMIT,
        "files_used": files_used,
        "files_limit": FREE_FILES_LIMIT,
    }
