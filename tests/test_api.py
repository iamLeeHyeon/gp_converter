import glob
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main
from app.config import Settings


def make_client(tmp_path, **settings_overrides):
    """jobs_dir을 tmp_path 하위로 둔 Settings를 dependency_overrides로 주입한다.

    importlib.reload 없이 app.main.app을 그대로 재사용한다.

    DB도 tmp_path 하위 격리된 SQLite로 재구성한다 — 실제 개발용 gp_converter.db를
    테스트가 오염시키는 것을 막는다. app.database.SessionLocal은 앱 전역에서
    공유하는 단일 sessionmaker 객체라, 새 객체로 교체(재할당)하지 않고
    `.configure(bind=...)`로 같은 객체의 bind만 바꾼다 — 테스트 함수들이
    `from app.database import SessionLocal`를 make_client() 호출보다 먼저
    실행해 이미 참조를 붙잡고 있어도(현재 TestConvertUsageLimits가 그렇게 작성됨),
    같은 객체이므로 이후 호출에서 재구성된 bind가 그대로 적용된다.
    """
    settings = Settings(jobs_dir=str(tmp_path / "jobs"), **settings_overrides)
    main.app.dependency_overrides[main.get_settings] = lambda: settings

    from sqlalchemy import create_engine
    from app.database import Base, SessionLocal

    test_engine = create_engine(
        f"sqlite:///{tmp_path}/test.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=test_engine)
    SessionLocal.configure(bind=test_engine)

    return TestClient(main.app), main


def test_convert_rejects_non_pdf(tmp_path):
    client, _ = make_client(tmp_path)
    r = client.post("/convert", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_convert_then_status_then_result(tmp_path):
    client, m = make_client(tmp_path)

    # Celery task 디스패치(.delay)가 즉시 동기 실행되도록 패치
    def fake_delay(jobs_dir, job_id, pdf_path, **kwargs):
        from app.jobs import JobStore
        store = JobStore(jobs_dir)
        gp5 = tmp_path / "r.gp5"
        gp5.write_bytes(b"FICHIER GUITAR PRO")
        store.update(job_id, status=m.JobStatus.DONE, result_path=str(gp5))

    with patch("app.main.process_job_task.delay", side_effect=fake_delay):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        s = client.get(f"/jobs/{job_id}")
        assert s.status_code == 200
        assert s.json()["status"] == "done"

        res = client.get(f"/jobs/{job_id}/result")
        assert res.status_code == 200
        assert res.content.startswith(b"FICHIER GUITAR PRO")


def test_status_missing_job_404(tmp_path):
    client, _ = make_client(tmp_path)
    assert client.get("/jobs/nope").status_code == 404


def test_result_not_done_returns_409(tmp_path):
    # 큐 디스패치가 no-op이라 job은 "queued" 상태로 남는다
    def noop_delay(jobs_dir, job_id, pdf_path, **kwargs):
        pass

    client, _ = make_client(tmp_path)
    with patch("app.main.process_job_task.delay", side_effect=noop_delay):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

    res = client.get(f"/jobs/{job_id}/result")
    assert res.status_code == 409


def test_upload_too_large_rejected(tmp_path):
    client, _ = make_client(tmp_path, max_upload_bytes=10)
    body = b"%PDF-1.4 " + b"x" * 100
    r = client.post("/convert", files={"file": ("a.pdf", body, "application/pdf")})
    assert r.status_code == 400


def _jobs_dir_entries(tmp_path):
    jobs_dir = tmp_path / "jobs"
    if not jobs_dir.exists():
        return []
    return list(jobs_dir.iterdir())


def test_rejected_upload_leaves_no_temp_or_job_files(tmp_path):
    """비-PDF/용량초과로 거부된 업로드는 임시파일이나 job 디렉토리를 남기면 안 된다."""
    client, _ = make_client(tmp_path, max_upload_bytes=10)

    r1 = client.post("/convert", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r1.status_code == 400

    body = b"%PDF-1.4 " + b"x" * 100
    r2 = client.post("/convert", files={"file": ("a.pdf", body, "application/pdf")})
    assert r2.status_code == 400

    assert _jobs_dir_entries(tmp_path) == []

    leftover_tmp = glob.glob("/tmp/upload_*")
    assert leftover_tmp == []


def test_accepted_upload_content_fully_written(tmp_path):
    """스트리밍으로 받은 PDF가 잘리지 않고 job workdir에 그대로 저장돼야 한다."""
    client, _ = make_client(tmp_path)
    body = b"%PDF-1.4 " + b"x" * (2 * 1024 * 1024)  # 청크 경계를 넘는 크기

    def noop_delay(jobs_dir, job_id, pdf_path, **kwargs):
        with open(pdf_path, "rb") as f:
            assert f.read() == body

    with patch("app.main.process_job_task.delay", side_effect=noop_delay):
        r = client.post("/convert", files={"file": ("a.pdf", body, "application/pdf")})
        assert r.status_code == 200


def test_each_test_gets_isolated_jobs_dir(tmp_path):
    """dependency_overrides가 매 테스트마다 독립된 Settings를 주입해야 한다."""
    client, _ = make_client(tmp_path)
    with patch("app.main.process_job_task.delay"):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
    assert r.status_code == 200
    assert (tmp_path / "jobs").is_dir()


class TestConvertUsageLimits:
    def test_free_user_blocked_after_3_successful_conversions(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u1", email="cv1@x.com", provider="google",
                       provider_id="cv-u1", plan="free"))
        for i in range(3):
            db.merge(File(id=f"cv-f{i}", user_id="cv-u1", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u1")
        r = client.post(
            "/convert",
            files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 402

    def test_free_user_allowed_with_2_successful_conversions(self, tmp_path):
        from unittest.mock import patch
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u2", email="cv2@x.com", provider="google",
                       provider_id="cv-u2", plan="free"))
        for i in range(2):
            db.merge(File(id=f"cv-f2-{i}", user_id="cv-u2", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u2")
        with patch("app.main.process_job_task.delay"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200

    def test_free_user_blocked_after_5_saved_files(self, tmp_path):
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u3", email="cv3@x.com", provider="google",
                       provider_id="cv-u3", plan="free"))
        for i in range(5):
            db.merge(File(id=f"cv-f3-{i}", user_id="cv-u3", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u3")
        r = client.post(
            "/convert",
            files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 402

    def test_free_user_not_blocked_by_failed_conversions(self, tmp_path):
        """실패/대기(gp5_path="") 변환은 저장 한도(5개)에 카운트되면 안 된다."""
        from unittest.mock import patch
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u5", email="cv5@x.com", provider="google",
                       provider_id="cv-u5", plan="free"))
        for i in range(5):
            db.merge(File(id=f"cv-f5-{i}", user_id="cv-u5", name="s", gp5_path=""))
        db.commit()
        db.close()

        token = create_access_token("cv-u5")
        with patch("app.main.process_job_task.delay"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200

    def test_pro_user_unlimited(self, tmp_path):
        from unittest.mock import patch
        from app.database import SessionLocal
        from app.models import User, File
        from app.auth import create_access_token

        client, _ = make_client(tmp_path)
        db = SessionLocal()
        db.merge(User(id="cv-u4", email="cv4@x.com", provider="google",
                       provider_id="cv-u4", plan="pro"))
        for i in range(10):
            db.merge(File(id=f"cv-f4-{i}", user_id="cv-u4", name="s", gp5_path=f"/x/{i}.gp5"))
        db.commit()
        db.close()

        token = create_access_token("cv-u4")
        with patch("app.main.process_job_task.delay"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert r.status_code == 200

    def test_anonymous_user_not_limited(self, tmp_path):
        """비로그인 유저는 사용량 제한 대상이 아니다 (기존 아키텍처 연장, 알려진 한계)."""
        from unittest.mock import patch

        client, _ = make_client(tmp_path)
        with patch("app.main.process_job_task.delay"):
            r = client.post(
                "/convert",
                files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")},
            )
        assert r.status_code == 200
