"""Простой in-memory rate limiter для защиты endpoint'ов."""
import time
from collections import defaultdict, deque

# key -> deque of timestamps
_buckets: dict[str, deque] = defaultdict(deque)


def rate_limit(key: str, max_requests: int, window_sec: int) -> tuple[bool, int]:
    """
    Проверяет rate limit.
    Возвращает (allowed, seconds_until_reset).
    """
    now = time.time()
    bucket = _buckets[key]

    # Удаляем старые записи за пределами окна
    while bucket and bucket[0] < now - window_sec:
        bucket.popleft()

    if len(bucket) >= max_requests:
        reset = int(bucket[0] + window_sec - now) + 1
        return False, reset

    bucket.append(now)
    return True, 0


def get_client_ip(request) -> str:
    """Извлечь IP клиента (с учётом прокси Traefik)."""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    xri = request.headers.get("x-real-ip", "")
    if xri:
        return xri.strip()
    client = getattr(request, "client", None)
    return client.host if client else "unknown"
