from unittest.mock import MagicMock, patch

import redis
import pytest
from fastapi import HTTPException, Request


def _fake_request():
    req = MagicMock(spec=Request)
    req.client.host = "1.2.3.4"
    return req


def test_rate_limit_allows_under_threshold():
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 5
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        dep(_fake_request())  # 예외 없이 통과해야 함


def test_rate_limit_blocks_over_threshold():
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 21
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        with pytest.raises(HTTPException) as exc_info:
            dep(_fake_request())
        assert exc_info.value.status_code == 429


def test_rate_limit_sets_expiry_only_on_first_request():
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.return_value = 1
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        dep(_fake_request())
    fake_redis.expire.assert_called_once()


def test_rate_limit_fails_open_when_redis_unavailable():
    """Redis 장애 시 요청을 막지 않는다(fail-open)."""
    from app.rate_limit import rate_limit
    fake_redis = MagicMock()
    fake_redis.incr.side_effect = redis.exceptions.ConnectionError("boom")
    with patch("app.rate_limit._redis_client", fake_redis):
        dep = rate_limit("test-endpoint")
        dep(_fake_request())  # 예외 없이 통과해야 함
