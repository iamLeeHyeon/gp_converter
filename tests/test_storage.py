import os
from unittest.mock import MagicMock, patch

import pytest

from app.storage import LocalStorage, S3Storage, get_storage


class TestLocalStorage:
    def test_key_for_returns_local_path_unchanged(self, tmp_path):
        storage = LocalStorage()
        local_path = str(tmp_path / "output.gp5")
        assert storage.key_for("file-1", local_path) == local_path

    def test_save_file_noop_when_key_equals_local_path(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        path.write_bytes(b"GP5DATA")
        storage.save_file(str(path), str(path))
        assert path.read_bytes() == b"GP5DATA"

    def test_save_file_copies_when_key_differs(self, tmp_path):
        storage = LocalStorage()
        src = tmp_path / "src.gp5"
        src.write_bytes(b"NEWDATA")
        dst = tmp_path / "dst.gp5"
        dst.write_bytes(b"OLDDATA")
        storage.save_file(str(dst), str(src))
        assert dst.read_bytes() == b"NEWDATA"
        assert src.read_bytes() == b"NEWDATA"  # 원본은 호출자가 정리하기 전까지 그대로

    def test_save_file_uses_atomic_replace_when_key_differs(self, tmp_path):
        storage = LocalStorage()
        src = tmp_path / "src.gp5"
        src.write_bytes(b"NEWDATA")
        dst = tmp_path / "dst.gp5"
        dst.write_bytes(b"OLDDATA")

        with patch("app.storage.os.replace", wraps=os.replace) as mock_replace:
            storage.save_file(str(dst), str(src))

        mock_replace.assert_called_once()
        replaced_src, replaced_dst = mock_replace.call_args[0]
        assert os.path.dirname(replaced_src) == str(tmp_path)  # 같은 디렉토리의 임시파일
        assert replaced_dst == str(dst)
        assert dst.read_bytes() == b"NEWDATA"
        # 임시파일은 rename으로 소비되어 남지 않아야 함
        leftover = [p for p in tmp_path.iterdir() if p not in (src, dst)]
        assert leftover == []

    def test_load_to_temp_returns_disposable_copy_not_original(self, tmp_path):
        storage = LocalStorage()
        original = tmp_path / "output.gp5"
        original.write_bytes(b"GP5DATA")

        tmp_result = storage.load_to_temp(str(original))
        try:
            assert tmp_result != str(original)
            with open(tmp_result, "rb") as f:
                assert f.read() == b"GP5DATA"
            assert original.exists()
        finally:
            os.unlink(tmp_result)

    def test_exists(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        assert storage.exists(str(path)) is False
        path.write_bytes(b"x")
        assert storage.exists(str(path)) is True

    def test_delete(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        path.write_bytes(b"x")
        storage.delete(str(path))
        assert not path.exists()

    def test_response_for_returns_file_response(self, tmp_path):
        storage = LocalStorage()
        path = tmp_path / "output.gp5"
        path.write_bytes(b"GP5DATA")
        response = storage.response_for(str(path), filename="score.gp5")
        assert response.path == str(path)
        assert response.filename == "score.gp5"


class TestS3Storage:
    def test_key_for_ignores_local_path(self):
        with patch("boto3.client"):
            storage = S3Storage(bucket="my-bucket")
        assert storage.key_for("file-42", "/tmp/anything.gp5") == "file-42.gp5"

    def test_save_file_uploads(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            storage.save_file("file-42.gp5", "/tmp/local.gp5")
        mock_client.upload_file.assert_called_once_with("/tmp/local.gp5", "my-bucket", "file-42.gp5")

    def test_load_to_temp_downloads(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            result = storage.load_to_temp("file-42.gp5")
        try:
            args = mock_client.download_file.call_args[0]
            assert args[0] == "my-bucket"
            assert args[1] == "file-42.gp5"
            assert args[2] == result
        finally:
            os.unlink(result)

    def test_exists_true(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            assert storage.exists("file-42.gp5") is True
        mock_client.head_object.assert_called_once_with(Bucket="my-bucket", Key="file-42.gp5")

    def test_exists_false_on_404(self):
        from botocore.exceptions import ClientError
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.head_object.side_effect = ClientError(
                {"Error": {"Code": "404"}}, "HeadObject"
            )
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            assert storage.exists("file-42.gp5") is False

    def test_delete(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            storage.delete("file-42.gp5")
        mock_client.delete_object.assert_called_once_with(Bucket="my-bucket", Key="file-42.gp5")

    def test_response_for_downloads_then_serves_with_cleanup(self):
        with patch("boto3.client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client_factory.return_value = mock_client
            storage = S3Storage(bucket="my-bucket")
            response = storage.response_for("file-42.gp5", filename="score.gp5")
        assert response.filename == "score.gp5"
        assert response.background is not None
        os.unlink(response.path)  # 테스트에선 실제 응답 전송이 없어 BackgroundTask가 안 실행됨


class TestGetStorage:
    def test_default_is_local(self, monkeypatch):
        monkeypatch.delenv("STORAGE_BACKEND", raising=False)
        assert isinstance(get_storage(), LocalStorage)

    def test_s3_backend_requires_bucket_name(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.delenv("S3_BUCKET_NAME", raising=False)
        with pytest.raises(ValueError, match="S3_BUCKET_NAME"):
            get_storage()

    def test_s3_backend_returns_s3_storage(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "s3")
        monkeypatch.setenv("S3_BUCKET_NAME", "my-bucket")
        with patch("boto3.client"):
            storage = get_storage()
        assert isinstance(storage, S3Storage)
        assert storage._bucket == "my-bucket"

    def test_unknown_backend_raises(self, monkeypatch):
        monkeypatch.setenv("STORAGE_BACKEND", "azure")
        with pytest.raises(ValueError, match="azure"):
            get_storage()
