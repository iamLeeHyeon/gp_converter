from typing import Optional

from app.celery_app import celery_app
from app.jobs import JobStore
from app.worker import process_job


@celery_app.task(name="gp_converter.process_job")
def process_job_task(
    jobs_dir: str, job_id: str, pdf_path: str,
    audiveris_cmd: str, tuxguitar_cmd: str, timeout: int,
    file_id: Optional[str] = None,
) -> None:
    """Celery task 인자는 JSON 직렬화되므로 JobStore 객체를 직접 못 넘긴다.

    jobs_dir(문자열)만 받아 워커 프로세스 안에서 JobStore를 재구성한다.
    """
    store = JobStore(jobs_dir)
    process_job(
        store, job_id, pdf_path,
        audiveris_cmd=audiveris_cmd, tuxguitar_cmd=tuxguitar_cmd, timeout=timeout,
        file_id=file_id,
    )
