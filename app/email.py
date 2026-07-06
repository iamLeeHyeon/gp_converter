import logging
import os
import smtplib
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, html_body: str) -> None:
    """SMTP_HOST 미설정 시 조용히 로그만 남기고 스킵한다(dev/test 환경 대비 의도된 동작)."""
    host = os.getenv("SMTP_HOST")
    if not host:
        logger.info("[SMTP_HOST 미설정 — 이메일 발송 스킵] to=%s subject=%s", to, subject)
        return

    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_email = os.getenv("SMTP_FROM_EMAIL", username)
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() != "false"

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to

    with smtplib.SMTP(host, port, timeout=10) as server:
        if use_tls:
            server.starttls()
        if username:
            server.login(username, password)
        server.send_message(msg)
