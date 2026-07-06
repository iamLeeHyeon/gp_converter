from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.database import SessionLocal
from app.models import User


def _make_user(uid, **kwargs):
    db = SessionLocal()
    user = User(id=uid, email=f"{uid}@x.com", provider="password", provider_id=f"{uid}@x.com",
                password_hash="h", email_verified=False, **kwargs)
    db.add(user)
    db.commit()
    db.close()


def _cleanup(uid):
    db = SessionLocal()
    db.query(User).filter_by(id=uid).delete()
    db.commit()
    db.close()


def test_send_verification_email_task_sends_link_with_token():
    _make_user(
        "task-verify-1",
        verification_token="verify-tok-1",
        verification_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    try:
        from app.tasks import send_verification_email_task
        with patch("app.tasks.send_email") as mock_send:
            send_verification_email_task("task-verify-1")
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[0] == "task-verify-1@x.com"
        assert "verify-tok-1" in args[2]
    finally:
        _cleanup("task-verify-1")


def test_send_verification_email_task_noop_if_no_token():
    _make_user("task-verify-2")
    try:
        from app.tasks import send_verification_email_task
        with patch("app.tasks.send_email") as mock_send:
            send_verification_email_task("task-verify-2")
        mock_send.assert_not_called()
    finally:
        _cleanup("task-verify-2")


def test_send_reset_email_task_sends_link_with_token():
    _make_user(
        "task-reset-1",
        reset_token="reset-tok-1",
        reset_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
    )
    try:
        from app.tasks import send_reset_email_task
        with patch("app.tasks.send_email") as mock_send:
            send_reset_email_task("task-reset-1")
        mock_send.assert_called_once()
        args, _ = mock_send.call_args
        assert args[0] == "task-reset-1@x.com"
        assert "reset-tok-1" in args[2]
    finally:
        _cleanup("task-reset-1")


def test_email_tasks_callable_without_broker():
    """Celery task 데코레이터가 붙어도 일반 함수처럼 직접 호출 가능해야 한다."""
    from app.tasks import send_verification_email_task, send_reset_email_task
    assert hasattr(send_verification_email_task, "delay")
    assert hasattr(send_reset_email_task, "delay")
