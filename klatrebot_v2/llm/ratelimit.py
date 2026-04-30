"""Per-user sliding-window rate limiter. In-memory; resets on restart."""
import time
from collections import defaultdict, deque

from klatrebot_v2.settings import get_settings


_buckets: defaultdict[int, deque[float]] = defaultdict(deque)
_WINDOW_SECONDS: float = 3600.0
_LIMIT_PER_HOUR: int = 0   # 0 = uninitialized; resolved lazily on first call


def _resolve_limit() -> int:
    global _LIMIT_PER_HOUR
    if _LIMIT_PER_HOUR == 0:
        _LIMIT_PER_HOUR = get_settings().rate_limit_per_user_per_hour
    return _LIMIT_PER_HOUR


def check_and_record(user_id: int) -> bool:
    """Return True if the call is allowed; False if rate-limited."""
    limit = _resolve_limit()
    now = time.monotonic()
    q = _buckets[user_id]
    while q and now - q[0] > _WINDOW_SECONDS:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
