from app.jobs import JobStore, JobStatus
from app.pipeline.orchestrator import run_conversion


def process_job(store: JobStore, job_id: str, pdf_path: str,
                audiveris_cmd: str, tuxguitar_cmd: str, timeout: int) -> None:
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
    except Exception as e:
        store.update(job_id, status=JobStatus.FAILED, message=str(e))
