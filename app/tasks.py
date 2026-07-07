from typing import Optional

from app.celery_app import celery_app
from app.config import Settings
from app.database import SessionLocal
from app.email import send_email
from app.jobs import JobStore
from app.models import User
from app.worker import process_job

_settings = Settings()
_FRONTEND_URL = _settings.frontend_url
_BACKEND_URL = _settings.backend_url


@celery_app.task(name="gp_converter.process_job")
def process_job_task(
    jobs_dir: str, job_id: str, pdf_path: str,
    audiveris_cmd: str, timeout: int,
    file_id: Optional[str] = None,
) -> None:
    """Celery task 인자는 JSON 직렬화되므로 JobStore 객체를 직접 못 넘긴다.

    jobs_dir(문자열)만 받아 워커 프로세스 안에서 JobStore를 재구성한다.
    """
    store = JobStore(jobs_dir)
    process_job(
        store, job_id, pdf_path,
        audiveris_cmd=audiveris_cmd, timeout=timeout,
        file_id=file_id,
    )


@celery_app.task(name="gp_converter.send_verification_email")
def send_verification_email_task(user_id: str) -> None:
    """워커 프로세스 안에서 DB 세션을 새로 만들어 user_id로 유저를 재조회한다."""
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.verification_token:
            return
        link = f"{_BACKEND_URL}/auth/verify?token={user.verification_token}"
        send_email(
            user.email,
            "GP Converter 이메일 인증",
            f'<p>아래 링크를 눌러 이메일을 인증해주세요 (24시간 이내):</p>'
            f'<p><a href="{link}">{link}</a></p>',
        )
    finally:
        db.close()


@celery_app.task(name="gp_converter.send_reset_email")
def send_reset_email_task(user_id: str) -> None:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user or not user.reset_token:
            return
        link = f"{_FRONTEND_URL}/reset-password?token={user.reset_token}"
        send_email(
            user.email,
            "GP Converter 비밀번호 재설정",
            f'<p>아래 링크를 눌러 비밀번호를 재설정해주세요 (1시간 이내):</p>'
            f'<p><a href="{link}">{link}</a></p>',
        )
    finally:
        db.close()
