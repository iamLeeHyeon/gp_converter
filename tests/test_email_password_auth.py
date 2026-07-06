from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import User

client = TestClient(app, follow_redirects=False)


def _cleanup(*emails):
    db = SessionLocal()
    for email in emails:
        db.query(User).filter_by(email=email).delete()
    db.commit()
    db.close()


class TestRegister:
    def test_register_creates_unverified_user_and_returns_tokens(self):
        try:
            with patch("app.routers.auth.send_verification_email_task") as mock_task:
                r = client.post("/auth/register", json={
                    "email": "newuser1@x.com", "password": "password123",
                })
            assert r.status_code == 200
            body = r.json()
            assert "access_token" in body
            assert "refresh_token" in body

            db = SessionLocal()
            user = db.query(User).filter_by(email="newuser1@x.com").first()
            assert user is not None
            assert user.provider == "password"
            assert user.provider_id == "newuser1@x.com"
            assert user.email_verified is False
            assert user.password_hash is not None
            assert user.password_hash != "password123"
            assert user.verification_token is not None
            db.close()

            mock_task.delay.assert_called_once_with(user.id)
        finally:
            _cleanup("newuser1@x.com")

    def test_register_rejects_short_password(self):
        r = client.post("/auth/register", json={"email": "shortpw@x.com", "password": "abc"})
        assert r.status_code == 400

    def test_register_rejects_duplicate_email_same_provider(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "dup1@x.com", "password": "password123"})
                r = client.post("/auth/register", json={"email": "dup1@x.com", "password": "password456"})
            assert r.status_code == 400
        finally:
            _cleanup("dup1@x.com")

    def test_register_rejects_email_already_used_via_oauth(self):
        db = SessionLocal()
        db.add(User(id="oauth-dup-1", email="oauthdup@x.com", provider="google", provider_id="g-oauth-1"))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/register", json={"email": "oauthdup@x.com", "password": "password123"})
            assert r.status_code == 400
            assert "google" in r.json()["detail"].lower() or "Google" in r.json()["detail"]
        finally:
            _cleanup("oauthdup@x.com")


class TestVerify:
    def test_verify_valid_token_marks_verified_and_redirects_success(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "verifyme@x.com", "password": "password123"})
            db = SessionLocal()
            user = db.query(User).filter_by(email="verifyme@x.com").first()
            token = user.verification_token
            db.close()

            r = client.get("/auth/verify", params={"token": token})
            assert r.status_code in (302, 307)
            assert "verify=success" in r.headers["location"]

            db = SessionLocal()
            user = db.query(User).filter_by(email="verifyme@x.com").first()
            assert user.email_verified is True
            assert user.verification_token is None
            db.close()
        finally:
            _cleanup("verifyme@x.com")

    def test_verify_invalid_token_redirects_expired(self):
        r = client.get("/auth/verify", params={"token": "not-a-real-token"})
        assert r.status_code in (302, 307)
        assert "verify=expired" in r.headers["location"]

    def test_verify_expired_token_redirects_expired(self):
        from datetime import datetime, timedelta, timezone
        db = SessionLocal()
        db.add(User(
            id="expired-verify-1", email="expiredverify@x.com", provider="password",
            provider_id="expiredverify@x.com", password_hash="h", email_verified=False,
            verification_token="expired-tok-1",
            verification_token_expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        ))
        db.commit()
        db.close()
        try:
            r = client.get("/auth/verify", params={"token": "expired-tok-1"})
            assert r.status_code in (302, 307)
            assert "verify=expired" in r.headers["location"]
        finally:
            _cleanup("expiredverify@x.com")


class TestResendVerification:
    def test_resend_dispatches_new_token_for_unverified_user(self):
        try:
            with patch("app.routers.auth.send_verification_email_task") as mock_task:
                client.post("/auth/register", json={"email": "resend1@x.com", "password": "password123"})
                db = SessionLocal()
                old_token = db.query(User).filter_by(email="resend1@x.com").first().verification_token
                db.close()

                r = client.post("/auth/resend-verification", json={"email": "resend1@x.com"})
            assert r.status_code == 200

            db = SessionLocal()
            user = db.query(User).filter_by(email="resend1@x.com").first()
            assert user.verification_token is not None
            assert user.verification_token != old_token
            db.close()
            assert mock_task.delay.call_count == 2
        finally:
            _cleanup("resend1@x.com")

    def test_resend_returns_200_for_nonexistent_email(self):
        """계정 존재 여부를 유추할 수 없도록 항상 동일한 200을 반환한다."""
        r = client.post("/auth/resend-verification", json={"email": "doesnotexist@x.com"})
        assert r.status_code == 200

    def test_resend_returns_200_for_already_verified_user(self):
        db = SessionLocal()
        db.add(User(
            id="already-verified-1", email="alreadyverified@x.com", provider="password",
            provider_id="alreadyverified@x.com", password_hash="h", email_verified=True,
        ))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/resend-verification", json={"email": "alreadyverified@x.com"})
            assert r.status_code == 200
        finally:
            _cleanup("alreadyverified@x.com")


class TestLogin:
    def test_login_succeeds_with_correct_password(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "loginme@x.com", "password": "password123"})
            r = client.post("/auth/login", json={"email": "loginme@x.com", "password": "password123"})
            assert r.status_code == 200
            assert "access_token" in r.json()
        finally:
            _cleanup("loginme@x.com")

    def test_login_fails_with_wrong_password(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                client.post("/auth/register", json={"email": "wrongpw@x.com", "password": "password123"})
            r = client.post("/auth/login", json={"email": "wrongpw@x.com", "password": "wrongpassword"})
            assert r.status_code == 401
        finally:
            _cleanup("wrongpw@x.com")

    def test_login_fails_for_nonexistent_email(self):
        r = client.post("/auth/login", json={"email": "nosuchuser@x.com", "password": "password123"})
        assert r.status_code == 401

    def test_login_fails_for_oauth_only_account(self):
        """password_hash가 없는 OAuth 전용 계정은 자체가입 로그인으로 들어갈 수 없다."""
        db = SessionLocal()
        db.add(User(id="oauth-only-1", email="oauthonly@x.com", provider="google", provider_id="g-only-1"))
        db.commit()
        db.close()
        try:
            r = client.post("/auth/login", json={"email": "oauthonly@x.com", "password": "anything123"})
            assert r.status_code == 401
        finally:
            _cleanup("oauthonly@x.com")


class TestMe:
    def test_me_returns_current_user_info(self):
        try:
            with patch("app.routers.auth.send_verification_email_task"):
                reg = client.post("/auth/register", json={"email": "meuser@x.com", "password": "password123"})
            token = reg.json()["access_token"]
            r = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            body = r.json()
            assert body["email"] == "meuser@x.com"
            assert body["plan"] == "free"
            assert body["email_verified"] is False
        finally:
            _cleanup("meuser@x.com")

    def test_me_requires_auth(self):
        r = client.get("/auth/me")
        assert r.status_code in (401, 403)
