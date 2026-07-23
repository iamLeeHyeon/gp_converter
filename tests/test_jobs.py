import os
import time

import pytest

from app.jobs import Job, JobStore, JobStatus


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


def test_job_has_progress_pct(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    assert job.progress_pct == 0


def test_update_progress_pct(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    store.update(job.id, progress_pct=42)
    updated = store.get(job.id)
    assert updated.progress_pct == 42


def test_progress_persists_across_read(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    store.update(job.id, progress_pct=75, status=JobStatus.RUNNING)
    reloaded = store.get(job.id)
    assert reloaded.progress_pct == 75
    assert reloaded.status == JobStatus.RUNNING


def test_create_with_user_id(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create(user_id="u1")
    assert job.user_id == "u1"
    assert store.get(job.id).user_id == "u1"


def test_create_without_user_id_defaults_none(tmp_path):
    store = JobStore(str(tmp_path))
    job = store.create()
    assert job.user_id is None


def test_create_sweeps_stale_job_dirs(tmp_path):
    """TTL이 지난 job 디렉토리는 새 job을 만들 때 자동으로 정리돼야 한다 —
    로그인 없이도 /convert를 무제한 호출할 수 있는데 정리 로직이 없으면
    PDF+중간산출물+결과물이 디스크에 영구 누적된다."""
    store = JobStore(str(tmp_path), ttl_hours=1.0)
    old_job = store.create()
    old_meta = store._meta_path(old_job.id)
    old_time = time.time() - 3600 * 2  # 2시간 전(TTL 1시간 초과)
    os.utime(old_meta, (old_time, old_time))

    new_job = store.create()

    assert not os.path.exists(old_job.workdir)
    assert os.path.exists(new_job.workdir)


def test_create_keeps_fresh_job_dirs(tmp_path):
    """TTL 안 지난 job은 지우면 안 된다(생성 직후 새 job 생성해도 그대로)."""
    store = JobStore(str(tmp_path), ttl_hours=24.0)
    job1 = store.create()
    job2 = store.create()

    assert os.path.exists(job1.workdir)
    assert os.path.exists(job2.workdir)
