import os
from unittest.mock import patch, MagicMock


def test_send_email_skips_when_smtp_host_unset(monkeypatch):
    """SMTP_HOST 미설정이면 예외 없이 조용히 스킵한다."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    from app.email import send_email
    with patch("smtplib.SMTP") as mock_smtp:
        send_email("to@x.com", "제목", "<p>본문</p>")
    mock_smtp.assert_not_called()


def test_send_email_sends_via_smtp_with_tls(monkeypatch):
    """SMTP_HOST 설정 시 실제로 SMTP 서버에 접속해서 발송한다."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "noreply@example.com")

    from app.email import send_email
    mock_server = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_server
    with patch("smtplib.SMTP", return_value=mock_smtp_cm) as mock_smtp:
        send_email("to@x.com", "제목", "<p>본문</p>")

    mock_smtp.assert_called_once_with("smtp.example.com", 587, timeout=10)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("user@example.com", "app-password")
    mock_server.send_message.assert_called_once()
    sent_msg = mock_server.send_message.call_args[0][0]
    assert sent_msg["To"] == "to@x.com"
    assert sent_msg["From"] == "noreply@example.com"
    assert sent_msg["Subject"] == "제목"


def test_send_email_skips_tls_and_login_when_disabled(monkeypatch):
    """SMTP_USE_TLS=false + SMTP_USERNAME 없으면 starttls/login을 호출하지 않는다."""
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)

    from app.email import send_email
    mock_server = MagicMock()
    mock_smtp_cm = MagicMock()
    mock_smtp_cm.__enter__.return_value = mock_server
    with patch("smtplib.SMTP", return_value=mock_smtp_cm):
        send_email("to@x.com", "제목", "<p>본문</p>")

    mock_server.starttls.assert_not_called()
    mock_server.login.assert_not_called()
    mock_server.send_message.assert_called_once()
