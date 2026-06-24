import os

import pytest

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
    assert os.path.isdir(job.workdir)


def test_write_failure_does_not_corrupt_existing_file(tmp_path, monkeypatch):
    """_write가 임시파일+os.replace로 원자적이어야 한다.

    쓰기 도중 실패해도 기존 job.json은 손상되지 않고 그대로 남아야 한다.
    (truncate 후 바로 쓰는 방식이면 실패 시 파일이 비거나 잘린 상태로 남음)
    """
    from app import jobs as jobs_module

    store = JobStore(str(tmp_path))
    job = store.create()
    store.update(job.id, status=JobStatus.RUNNING)

    meta_path = store._meta_path(job.id)
    original_content = open(meta_path).read()
    assert original_content

    def boom(*args, **kwargs):
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(jobs_module.json, "dump", boom)

    with pytest.raises(RuntimeError):
        store.update(job.id, status=JobStatus.DONE)

    assert open(meta_path).read() == original_content
    leftover = [f for f in os.listdir(os.path.dirname(meta_path)) if f != "job.json"]
    assert leftover == []
