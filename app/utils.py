from datetime import datetime, timezone


def as_utc(dt: datetime) -> datetime:
    """naive datetime을 UTC aware로 정규화한다 (이미 aware면 그대로)."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
