import os

import pytest

# OAuth/JWT 관련 환경변수 — app.auth, app.routers.auth 모듈 수준 import 전에 세팅
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-minimum!!")
os.environ.setdefault("GOOGLE_CLIENT_ID", "g-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "g-secret")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_dummy")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_dummy")
os.environ.setdefault("STRIPE_PRICE_ID_PRO", "price_dummy")


@pytest.fixture(autouse=True)
def _reset_rate_limit_counters():
    """매 테스트 전 레이트리밋 Redis 카운터를 지운다.

    app/rate_limit.py의 dependency는 실제 로컬 Redis(CELERY_BROKER_URL)를
    공유한다 — 이걸 안 지우면 register/login/forgot-password 등을 반복
    호출하는 테스트들이 스위트를 여러 번 돌릴수록(또는 이전 실행의 잔여
    카운터가 남아있으면) 429로 결정적으로 실패한다. Redis가 아예 안 떠있는
    환경에서는(fail-open 설계) 이 정리 자체도 조용히 스킵된다.
    """
    from app.rate_limit import _redis_client
    import redis as _redis_module
    try:
        for key in _redis_client.scan_iter(match="ratelimit:*"):
            _redis_client.delete(key)
    except _redis_module.exceptions.RedisError:
        pass
    yield
