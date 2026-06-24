import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    max_upload_bytes: int = field(default_factory=lambda: int(_env("GPC_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))))
    step_timeout_sec: int = field(default_factory=lambda: int(_env("GPC_STEP_TIMEOUT_SEC", "300")))
    audiveris_cmd: str = field(default_factory=lambda: _env("GPC_AUDIVERIS_CMD", "audiveris"))
    tuxguitar_cmd: str = field(default_factory=lambda: _env("GPC_TUXGUITAR_CMD", "tuxguitar"))
    jobs_dir: str = field(default_factory=lambda: _env("GPC_JOBS_DIR", "jobs"))


settings = Settings()
