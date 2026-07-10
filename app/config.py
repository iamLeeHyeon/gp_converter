import os

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GPC_")

    max_upload_bytes: int = 20 * 1024 * 1024
    step_timeout_sec: int = 300
    audiveris_cmd: str = "audiveris"
    jobs_dir: str = "jobs"

    # GPC_ 접두사 없이 이미 여러 모듈에서 그대로 쓰이던 환경변수 — alias로 접두사 우회
    frontend_url: str = Field("http://localhost:5173", validation_alias="FRONTEND_URL")
    backend_url: str = Field("http://localhost:8010", validation_alias="BACKEND_URL")
    celery_broker_url: str = Field("redis://localhost:6379/0", validation_alias="CELERY_BROKER_URL")

    @field_validator("jobs_dir")
    @classmethod
    def _abspath(cls, v: str) -> str:
        return os.path.abspath(v)
