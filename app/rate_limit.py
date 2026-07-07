import redis
from fastapi import HTTPException, Request

from app.config import Settings

RATE_LIMIT_MAX = 20
RATE_LIMIT_WINDOW_SEC = 3600

_redis_client = redis.from_url(Settings().celery_broker_url)


def rate_limit(endpoint_name: str):
    """IP당 시간당 RATE_LIMIT_MAX회로 제한하는 FastAPI dependency를 만든다.

    Redis 장애 시에는 요청을 막지 않는다(fail-open) — 로그인/가입 자체가
    Redis 장애로 완전히 막히는 것을 방지하기 위한 의도된 동작이다.
    """
    def _dependency(request: Request) -> None:
        ip = request.client.host if request.client else "unknown"
        key = f"ratelimit:{endpoint_name}:{ip}"
        try:
            count = _redis_client.incr(key)
            if count == 1:
                _redis_client.expire(key, RATE_LIMIT_WINDOW_SEC)
        except redis.exceptions.RedisError:
            return
        if count > RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429, detail="너무 많은 요청입니다. 잠시 후 다시 시도하세요."
            )
    return _dependency
