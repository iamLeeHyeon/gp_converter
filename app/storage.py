import os
import shutil
import tempfile
from typing import Optional, Protocol

import boto3
from fastapi import Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask


class Storage(Protocol):
    def key_for(self, file_id: str, local_path: str) -> str: ...
    def save_file(self, key: str, local_path: str) -> None: ...
    def load_to_temp(self, key: str) -> str: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
    def response_for(self, key: str, filename: str) -> Response: ...


class LocalStorage:
    """key == 로컬 파일시스템 경로. 기존(추상화 이전) 동작과 완전히 동일하다."""

    def key_for(self, file_id: str, local_path: str) -> str:
        return local_path

    def save_file(self, key: str, local_path: str) -> None:
        if os.path.abspath(key) != os.path.abspath(local_path):
            shutil.copy(local_path, key)

    def load_to_temp(self, key: str) -> str:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".gp5")
        os.close(tmp_fd)
        shutil.copy(key, tmp_path)
        return tmp_path

    def exists(self, key: str) -> bool:
        return os.path.exists(key)

    def delete(self, key: str) -> None:
        os.remove(key)

    def response_for(self, key: str, filename: str) -> Response:
        return FileResponse(key, media_type="application/octet-stream", filename=filename)


class S3Storage:
    """S3 호환 오브젝트 스토리지. endpoint_url을 지정하면 AWS가 아닌 다른 서비스
    (MinIO, Cloudflare R2 등)로도 붙을 수 있다."""

    def __init__(self, bucket: str, endpoint_url: Optional[str] = None):
        self._bucket = bucket
        self._client = boto3.client("s3", endpoint_url=endpoint_url)

    def key_for(self, file_id: str, local_path: str) -> str:
        return f"{file_id}.gp5"

    def save_file(self, key: str, local_path: str) -> None:
        self._client.upload_file(local_path, self._bucket, key)

    def load_to_temp(self, key: str) -> str:
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".gp5")
        os.close(tmp_fd)
        self._client.download_file(self._bucket, key, tmp_path)
        return tmp_path

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def response_for(self, key: str, filename: str) -> Response:
        tmp_path = self.load_to_temp(key)
        return FileResponse(
            tmp_path,
            media_type="application/octet-stream",
            filename=filename,
            background=BackgroundTask(os.unlink, tmp_path),
        )


def get_storage() -> "Storage":
    """STORAGE_BACKEND 환경변수(기본 local)로 백엔드 선택."""
    backend = os.getenv("STORAGE_BACKEND", "local")
    if backend == "local":
        return LocalStorage()
    if backend == "s3":
        bucket = os.getenv("S3_BUCKET_NAME")
        if not bucket:
            raise ValueError(
                "STORAGE_BACKEND=s3인데 S3_BUCKET_NAME 환경변수가 없습니다."
            )
        endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
        return S3Storage(bucket=bucket, endpoint_url=endpoint_url)
    raise ValueError(f"알 수 없는 STORAGE_BACKEND: {backend!r}")
