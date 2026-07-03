from unittest.mock import patch, MagicMock

import stripe
from fastapi.testclient import TestClient

from app.main import app
from app.auth import create_access_token

client = TestClient(app)


def _tok(uid: str) -> str:
    return create_access_token(uid)


def _setup_user(db, uid="u1", plan="free", stripe_customer_id=None):
    from app.models import User
    user = User(id=uid, email=f"{uid}@x.com", provider="google", provider_id=uid,
                plan=plan, stripe_customer_id=stripe_customer_id)
    db.merge(user)
    db.commit()
    return user


class TestCreateCheckoutSession:
    def test_200_creates_customer_and_session(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u1")
        db.close()

        fake_customer = MagicMock(id="cus_abc")
        fake_session = MagicMock(url="https://checkout.stripe.com/session/xyz")
        with patch("stripe.Customer.create", return_value=fake_customer) as mock_customer, \
             patch("stripe.checkout.Session.create", return_value=fake_session) as mock_session:
            resp = client.post("/billing/checkout",
                                headers={"Authorization": f"Bearer {_tok('b-u1')}"})

        assert resp.status_code == 200
        assert resp.json() == {"url": "https://checkout.stripe.com/session/xyz"}
        mock_customer.assert_called_once()
        mock_session.assert_called_once()

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="b-u1").first()
        assert u.stripe_customer_id == "cus_abc"
        db.close()

    def test_reuses_existing_stripe_customer_id(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u2", stripe_customer_id="cus_existing")
        db.close()

        fake_session = MagicMock(url="https://checkout.stripe.com/session/abc")
        with patch("stripe.Customer.create") as mock_customer, \
             patch("stripe.checkout.Session.create", return_value=fake_session) as mock_session:
            resp = client.post("/billing/checkout",
                                headers={"Authorization": f"Bearer {_tok('b-u2')}"})

        assert resp.status_code == 200
        mock_customer.assert_not_called()
        mock_session.assert_called_once()
        assert mock_session.call_args.kwargs["customer"] == "cus_existing"


class TestCreatePortalSession:
    def test_200_with_existing_customer(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u3", stripe_customer_id="cus_p1")
        db.close()

        fake_session = MagicMock(url="https://billing.stripe.com/session/p1")
        with patch("stripe.billing_portal.Session.create", return_value=fake_session) as mock_portal:
            resp = client.post("/billing/portal",
                                headers={"Authorization": f"Bearer {_tok('b-u3')}"})

        assert resp.status_code == 200
        assert resp.json() == {"url": "https://billing.stripe.com/session/p1"}
        mock_portal.assert_called_once()

    def test_400_without_stripe_customer(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="b-u4")
        db.close()

        resp = client.post("/billing/portal",
                            headers={"Authorization": f"Bearer {_tok('b-u4')}"})
        assert resp.status_code == 400


class TestStripeWebhook:
    def test_400_invalid_signature(self):
        with patch("stripe.Webhook.construct_event",
                   side_effect=stripe.error.SignatureVerificationError("bad sig", "sig_header")):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "bad"})
        assert resp.status_code == 400

    def test_checkout_session_completed_sets_plan_pro(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u1", plan="free", stripe_customer_id="cus_w1")
        db.close()

        fake_event = {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_w1"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u1").first()
        assert u.plan == "pro"
        db.close()

    def test_subscription_updated_active_sets_pro(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u2", plan="free", stripe_customer_id="cus_w2")
        db.close()

        fake_event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_w2", "status": "active"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u2").first()
        assert u.plan == "pro"
        db.close()

    def test_subscription_updated_canceled_sets_free(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u3", plan="pro", stripe_customer_id="cus_w3")
        db.close()

        fake_event = {
            "type": "customer.subscription.updated",
            "data": {"object": {"customer": "cus_w3", "status": "canceled"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u3").first()
        assert u.plan == "free"
        db.close()

    def test_subscription_deleted_sets_free(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="w-u4", plan="pro", stripe_customer_id="cus_w4")
        db.close()

        fake_event = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"customer": "cus_w4"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200

        db = SessionLocal()
        from app.models import User
        u = db.query(User).filter_by(id="w-u4").first()
        assert u.plan == "free"
        db.close()

    def test_unknown_customer_id_does_not_crash(self):
        fake_event = {
            "type": "checkout.session.completed",
            "data": {"object": {"customer": "cus_unknown"}},
        }
        with patch("stripe.Webhook.construct_event", return_value=fake_event):
            resp = client.post("/billing/webhook", content=b"{}",
                                headers={"stripe-signature": "sig"})
        assert resp.status_code == 200  # 유저 못 찾아도 200 (Stripe 재전송 방지)


class TestUsage:
    def test_free_user_usage_counts(self, tmp_path):
        from app.database import SessionLocal
        from app.models import File
        db = SessionLocal()
        _setup_user(db, uid="u-u1", plan="free")
        for i in range(2):
            db.merge(File(id=f"u-f{i}", user_id="u-u1", name="s",
                           gp5_path=str(tmp_path / f"{i}.gp5")))
        db.merge(File(id="u-f-pending", user_id="u-u1", name="s", gp5_path=""))
        db.commit()
        db.close()

        resp = client.get("/billing/usage",
                           headers={"Authorization": f"Bearer {_tok('u-u1')}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["plan"] == "free"
        assert body["conversions_used"] == 2
        assert body["conversions_limit"] == 3
        assert body["files_used"] == 2
        assert body["files_limit"] == 5

    def test_old_conversions_excluded_from_30day_window(self):
        from datetime import datetime, timedelta
        from app.database import SessionLocal
        from app.models import File
        db = SessionLocal()
        _setup_user(db, uid="u-u2", plan="free")
        old_file = File(id="u-f-old", user_id="u-u2", name="s", gp5_path="/x/old.gp5")
        old_file.created_at = datetime.utcnow() - timedelta(days=31)
        db.merge(old_file)
        db.commit()
        db.close()

        resp = client.get("/billing/usage",
                           headers={"Authorization": f"Bearer {_tok('u-u2')}"})
        body = resp.json()
        assert body["conversions_used"] == 0  # 30일 밖이라 카운트 제외
        assert body["files_used"] == 1  # 저장 카운트는 시간 무관

    def test_pro_user_plan_reported(self):
        from app.database import SessionLocal
        db = SessionLocal()
        _setup_user(db, uid="u-u3", plan="pro")
        db.close()

        resp = client.get("/billing/usage",
                           headers={"Authorization": f"Bearer {_tok('u-u3')}"})
        assert resp.json()["plan"] == "pro"
