import os
from app.config import Settings

def test_defaults(monkeypatch):
    monkeypatch.delenv("GPC_AUDIVERIS_CMD", raising=False)
    monkeypatch.delenv("GPC_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("GPC_STEP_TIMEOUT_SEC", raising=False)
    s = Settings()
    assert s.max_upload_bytes == 20 * 1024 * 1024
    assert s.step_timeout_sec == 300
    assert s.audiveris_cmd == "audiveris"

def test_env_override(monkeypatch):
    monkeypatch.setenv("GPC_AUDIVERIS_CMD", "/opt/audiveris/bin/audiveris")
    s = Settings()
    assert s.audiveris_cmd == "/opt/audiveris/bin/audiveris"

def test_jobs_dir_default_is_absolute():
    s = Settings()
    assert os.path.isabs(s.jobs_dir)
    assert s.jobs_dir == os.path.join(os.getcwd(), "jobs")

def test_jobs_dir_env_override_relative_is_resolved_absolute(monkeypatch):
    monkeypatch.setenv("GPC_JOBS_DIR", "custom_jobs")
    s = Settings()
    assert s.jobs_dir == os.path.join(os.getcwd(), "custom_jobs")

def test_jobs_dir_env_override_absolute_is_kept(monkeypatch):
    monkeypatch.setenv("GPC_JOBS_DIR", "/var/data/jobs")
    s = Settings()
    assert s.jobs_dir == "/var/data/jobs"
