import os
import time
import pytest
import jwt

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")


def test_access_token_roundtrip():
    from app.auth import create_access_token, decode_token
    token = create_access_token("user123")
    payload = decode_token(token)
    assert payload["sub"] == "user123"
    assert payload["type"] == "access"


def test_refresh_token_roundtrip():
    from app.auth import create_refresh_token, decode_token
    token = create_refresh_token("user456")
    payload = decode_token(token)
    assert payload["sub"] == "user456"
    assert payload["type"] == "refresh"


def test_expired_token_raises():
    from app.auth import decode_token
    # 만료시간 1초 전 토큰 직접 발급
    payload = {"sub": "u1", "exp": int(time.time()) - 1, "type": "access"}
    token = jwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


def test_invalid_token_raises():
    from app.auth import decode_token
    with pytest.raises(jwt.InvalidTokenError):
        decode_token("not.a.valid.token")
