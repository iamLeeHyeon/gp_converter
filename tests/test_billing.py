from unittest.mock import patch, MagicMock

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
