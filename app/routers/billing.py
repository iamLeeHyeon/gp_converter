import os

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import User

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

_FRONTEND = os.getenv("FRONTEND_URL", "http://localhost:5173")


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
