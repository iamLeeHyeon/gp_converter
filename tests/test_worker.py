from unittest.mock import patch
from app.jobs import JobStore, JobStatus
from app.worker import process_job
from app.pipeline.audiveris import AudiverisError


def test_process_job_success(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.DONE
    assert got.result_path == "/x/output.gp5"


def test_process_job_failure(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", side_effect=AudiverisError("악보 인식 실패")):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.FAILED
    assert got.message == "악보 인식 실패"
