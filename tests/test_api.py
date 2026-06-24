from unittest.mock import patch
from fastapi.testclient import TestClient


def make_client(tmp_path, monkeypatch):
    monkeypatch.setenv("GPC_JOBS_DIR", str(tmp_path / "jobs"))
    import importlib
    import app.config, app.main
    importlib.reload(app.config)
    importlib.reload(app.main)
    return TestClient(app.main.app), app.main


def test_convert_rejects_non_pdf(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    r = client.post("/convert", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_convert_then_status_then_result(tmp_path, monkeypatch):
    client, main = make_client(tmp_path, monkeypatch)

    # 백그라운드 태스크가 즉시 동기 실행되도록 process_job을 패치
    def fake_process(store, job_id, pdf_path, **kwargs):
        gp5 = tmp_path / "r.gp5"
        gp5.write_bytes(b"FICHIER GUITAR PRO")
        store.update(job_id, status=main.JobStatus.DONE, result_path=str(gp5))

    with patch("app.main.process_job", side_effect=fake_process):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

        s = client.get(f"/jobs/{job_id}")
        assert s.status_code == 200
        assert s.json()["status"] == "done"

        res = client.get(f"/jobs/{job_id}/result")
        assert res.status_code == 200
        assert res.content.startswith(b"FICHIER GUITAR PRO")


def test_status_missing_job_404(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.get("/jobs/nope").status_code == 404


def test_result_not_done_returns_409(tmp_path, monkeypatch):
    # process_job is a no-op so the job stays in "queued" state
    def noop_process(store, job_id, pdf_path, **kwargs):
        pass

    client, _ = make_client(tmp_path, monkeypatch)
    with patch("app.main.process_job", side_effect=noop_process):
        r = client.post("/convert", files={"file": ("a.pdf", b"%PDF-1.4 x", "application/pdf")})
        assert r.status_code == 200
        job_id = r.json()["job_id"]

    res = client.get(f"/jobs/{job_id}/result")
    assert res.status_code == 409


def test_upload_too_large_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("GPC_MAX_UPLOAD_BYTES", "10")
    client, _ = make_client(tmp_path, monkeypatch)
    body = b"%PDF-1.4 " + b"x" * 100
    r = client.post("/convert", files={"file": ("a.pdf", body, "application/pdf")})
    assert r.status_code == 400


def _jobs_dir_entries(tmp_path):
    jobs_dir = tmp_path / "jobs"
    if not jobs_dir.exists():
        return []
    return list(jobs_dir.iterdir())


def test_rejected_upload_leaves_no_temp_or_job_files(tmp_path, monkeypatch):
    """비-PDF/용량초과로 거부된 업로드는 임시파일이나 job 디렉토리를 남기면 안 된다."""
    monkeypatch.setenv("GPC_MAX_UPLOAD_BYTES", "10")
    client, _ = make_client(tmp_path, monkeypatch)

    r1 = client.post("/convert", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r1.status_code == 400

    body = b"%PDF-1.4 " + b"x" * 100
    r2 = client.post("/convert", files={"file": ("a.pdf", body, "application/pdf")})
    assert r2.status_code == 400

    assert _jobs_dir_entries(tmp_path) == []

    import glob
    leftover_tmp = glob.glob("/tmp/upload_*")
    assert leftover_tmp == []


def test_accepted_upload_content_fully_written(tmp_path, monkeypatch):
    """스트리밍으로 받은 PDF가 잘리지 않고 job workdir에 그대로 저장돼야 한다."""
    client, main = make_client(tmp_path, monkeypatch)
    body = b"%PDF-1.4 " + b"x" * (2 * 1024 * 1024)  # 청크 경계를 넘는 크기

    def noop_process(store, job_id, pdf_path, **kwargs):
        with open(pdf_path, "rb") as f:
            assert f.read() == body

    with patch("app.main.process_job", side_effect=noop_process):
        r = client.post("/convert", files={"file": ("a.pdf", body, "application/pdf")})
        assert r.status_code == 200
