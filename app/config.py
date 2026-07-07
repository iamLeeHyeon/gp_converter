import os

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GPC_")

    max_upload_bytes: int = 20 * 1024 * 1024
    step_timeout_sec: int = 300
    audiveris_cmd: str = "audiveris"
    jobs_dir: str = "jobs"

    @field_validator("jobs_dir")
    @classmethod
    def _abspath(cls, v: str) -> str:
        return os.path.abspath(v)
