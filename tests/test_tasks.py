from unittest.mock import patch

from app.jobs import JobStore, JobStatus
from app.tasks import process_job_task


def test_process_job_task_delegates_with_reconstructed_store(tmp_path):
    """jobs_dir 문자열로 JobStore를 재구성해 process_job에 올바른 인자로 위임한다."""
    jobs_dir = str(tmp_path)
    store = JobStore(jobs_dir)
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.tasks.process_job") as mock_process_job:
        process_job_task(
            jobs_dir, job.id, str(pdf),
            audiveris_cmd="a", tuxguitar_cmd="t", timeout=10, file_id="f1",
        )

    mock_process_job.assert_called_once()
    args, kwargs = mock_process_job.call_args
    assert isinstance(args[0], JobStore)
    assert args[0].root == jobs_dir
    assert args[1] == job.id
    assert args[2] == str(pdf)
    assert kwargs == {
        "audiveris_cmd": "a", "tuxguitar_cmd": "t", "timeout": 10, "file_id": "f1",
    }


def test_process_job_task_real_success_updates_job_status(tmp_path):
    """mock 없이 실제 process_job까지 타서, 성공 시 job 상태가 DONE으로 바뀌는지 확인."""
    jobs_dir = str(tmp_path)
    store = JobStore(jobs_dir)
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job_task(jobs_dir, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.DONE
    assert got.result_path == "/x/output.gp5"


def test_process_job_task_callable_without_broker():
    """Celery task 데코레이터가 붙어도 일반 함수처럼 직접 호출 가능해야 한다(브로커 불필요)."""
    from app.tasks import process_job_task as task
    assert callable(task)
    # .delay/.apply_async 속성이 있다는 것 자체가 Celery task로 등록됐다는 증거
    assert hasattr(task, "delay")
    assert hasattr(task, "apply_async")
