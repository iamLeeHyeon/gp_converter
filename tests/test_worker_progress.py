import os, tempfile, pytest
from unittest.mock import patch, MagicMock
from app.jobs import JobStore, JobStatus


@pytest.fixture
def store(tmp_path):
    return JobStore(str(tmp_path))


def test_worker_updates_progress(store, tmp_path):
    pdf_path = str(tmp_path / "in.pdf")
    open(pdf_path, "w").close()

    recorded = []

    def fake_run_conversion(pdf_path, workdir, **kwargs):
        cb = kwargs.get("progress_callback")
        if cb:
            cb(10, "tab_detect")
            cb(30, "omr")
            cb(80, "gp5_build")
        return str(tmp_path / "out.gp5")

    open(str(tmp_path / "out.gp5"), "w").close()

    with patch("app.worker.run_conversion", side_effect=fake_run_conversion):
        from app.worker import process_job
        job = store.create()
        process_job(store, job.id, pdf_path,
                    audiveris_cmd="", tuxguitar_cmd="", timeout=0)

    final = store.get(job.id)
    assert final.status == JobStatus.DONE
    assert final.progress_pct == 100
