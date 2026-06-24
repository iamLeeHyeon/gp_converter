import os
from app.config import Settings

def test_defaults():
    s = Settings()
    assert s.max_upload_bytes == 20 * 1024 * 1024
    assert s.step_timeout_sec == 300
    assert s.audiveris_cmd == "audiveris"
    assert s.tuxguitar_cmd == "tuxguitar"

def test_env_override(monkeypatch):
    monkeypatch.setenv("GPC_AUDIVERIS_CMD", "/opt/audiveris/bin/audiveris")
    s = Settings()
    assert s.audiveris_cmd == "/opt/audiveris/bin/audiveris"
