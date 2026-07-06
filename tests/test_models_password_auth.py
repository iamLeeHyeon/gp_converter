from app.database import SessionLocal, engine, run_sqlite_migrations
from app.models import User


def test_new_oauth_user_defaults_email_verified_true():
    """provider/provider_id만 채우고 만든 User는 email_verified 기본값이 True여야 한다."""
    run_sqlite_migrations(engine)
    db = SessionLocal()
    try:
        user = User(id="pwtest-oauth-1", email="oauth1@x.com", provider="google", provider_id="g1")
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.email_verified is True
        assert user.password_hash is None
    finally:
        db.query(User).filter_by(id="pwtest-oauth-1").delete()
        db.commit()
        db.close()


def test_password_user_can_set_email_verified_false():
    """자체가입 코드는 email_verified=False를 명시적으로 넣을 수 있어야 한다."""
    run_sqlite_migrations(engine)
    db = SessionLocal()
    try:
        user = User(
            id="pwtest-pw-1", email="pw1@x.com", provider="password", provider_id="pw1@x.com",
            password_hash="hashed", email_verified=False,
            verification_token="tok-abc",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        assert user.email_verified is False
        assert user.verification_token == "tok-abc"
    finally:
        db.query(User).filter_by(id="pwtest-pw-1").delete()
        db.commit()
        db.close()
