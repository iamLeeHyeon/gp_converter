from app.jobs import JobStore, JobStatus


def test_create_and_get(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    assert job.status == JobStatus.QUEUED
    fetched = store.get(job.id)
    assert fetched.id == job.id
    assert fetched.status == JobStatus.QUEUED


def test_update_status(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    store.update(job.id, status=JobStatus.RUNNING)
    assert store.get(job.id).status == JobStatus.RUNNING
    store.update(job.id, status=JobStatus.FAILED, message="악보 인식 실패")
    got = store.get(job.id)
    assert got.status == JobStatus.FAILED
    assert got.message == "악보 인식 실패"


def test_get_missing_returns_none(tmp_path):
    store = JobStore(str(tmp_path))
    assert store.get("nope") is None


def test_workdir_created(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    import os
    assert os.path.isdir(job.workdir)
