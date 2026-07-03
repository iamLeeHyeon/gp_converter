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


def test_process_job_success_updates_file_gp5_path(tmp_path):
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    db.merge(User(id="w-u1", email="w1@x.com", provider="google", provider_id="w-u1"))
    db.merge(File(id="w-f1", user_id="w-u1", name="test", gp5_path=""))
    db.commit()
    db.close()

    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t",
                     timeout=10, file_id="w-f1")

    db = SessionLocal()
    updated = db.query(File).filter_by(id="w-f1").first()
    assert updated.gp5_path == "/x/output.gp5"
    db.close()


def test_process_job_failure_does_not_touch_file(tmp_path):
    from app.database import SessionLocal
    from app.models import User, File

    db = SessionLocal()
    db.merge(User(id="w-u2", email="w2@x.com", provider="google", provider_id="w-u2"))
    db.merge(File(id="w-f2", user_id="w-u2", name="test", gp5_path=""))
    db.commit()
    db.close()

    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", side_effect=AudiverisError("실패")):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t",
                     timeout=10, file_id="w-f2")

    db = SessionLocal()
    untouched = db.query(File).filter_by(id="w-f2").first()
    assert untouched.gp5_path == ""
    db.close()


def test_process_job_without_file_id_still_works(tmp_path):
    """기존 호출 시그니처(익명 유저, file_id 없음) 하위호환."""
    store = JobStore(str(tmp_path))
    job = store.create()
    pdf = tmp_path / "in.pdf"
    pdf.write_bytes(b"%PDF dummy")

    with patch("app.worker.run_conversion", return_value="/x/output.gp5"):
        process_job(store, job.id, str(pdf), audiveris_cmd="a", tuxguitar_cmd="t", timeout=10)

    got = store.get(job.id)
    assert got.status == JobStatus.DONE


def test_update_file_gp5_path_uses_storage_key_for_and_save_file(tmp_path):
    from unittest.mock import MagicMock, patch
    from app.database import SessionLocal
    from app.models import User, File
    from app.worker import _update_file_gp5_path

    db = SessionLocal()
    db.merge(User(id="w-u5", email="w5@x.com", provider="google", provider_id="w-u5"))
    db.merge(File(id="w-f5", user_id="w-u5", name="test", gp5_path=""))
    db.commit()
    db.close()

    fake_storage = MagicMock()
    fake_storage.key_for.return_value = "custom-key.gp5"

    with patch("app.worker.get_storage", return_value=fake_storage):
        _update_file_gp5_path("w-f5", "/tmp/local-output.gp5")

    fake_storage.key_for.assert_called_once_with("w-f5", "/tmp/local-output.gp5")
    fake_storage.save_file.assert_called_once_with("custom-key.gp5", "/tmp/local-output.gp5")

    db = SessionLocal()
    updated = db.query(File).filter_by(id="w-f5").first()
    assert updated.gp5_path == "custom-key.gp5"
    db.close()
