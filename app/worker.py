from typing import Optional

from app.jobs import JobStore, JobStatus
from app.pipeline.orchestrator import run_conversion
from app.storage import get_storage


def process_job(store: JobStore, job_id: str, pdf_path: str,
                audiveris_cmd: str, tuxguitar_cmd: str, timeout: int,
                file_id: Optional[str] = None) -> None:
    job = store.get(job_id)
    if job is None:
        return
    store.update(job_id, status=JobStatus.RUNNING, progress_pct=5)

    def _progress(pct: int, step: str):
        store.update(job_id, progress_pct=pct, message=step)

    try:
        gp5_path = run_conversion(
            pdf_path, job.workdir,
            audiveris_cmd=audiveris_cmd, tuxguitar_cmd=tuxguitar_cmd, timeout=timeout,
            progress_callback=_progress,
        )
        store.update(job_id, status=JobStatus.DONE, result_path=gp5_path, progress_pct=100)
        if file_id:
            _update_file_gp5_path(file_id, gp5_path)
    except Exception as e:
        store.update(job_id, status=JobStatus.FAILED, message=str(e))


def _update_file_gp5_path(file_id: str, local_gp5_path: str) -> None:
    from app.database import SessionLocal
    from app.models import File

    storage = get_storage()
    db = SessionLocal()
    try:
        f = db.query(File).filter_by(id=file_id).first()
        if f is not None:
            key = storage.key_for(file_id, local_gp5_path)
            storage.save_file(key, local_gp5_path)
            f.gp5_path = key
            db.commit()
    finally:
        db.close()
