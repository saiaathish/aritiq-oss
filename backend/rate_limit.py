"""
Per-user rate limiting for the audit endpoints (keyed by Supabase user id,
not IP). Two fixed windows:

  - burst:  10 requests / 10 minutes  (ARITIQ_USER_BURST_LIMIT)
  - daily:  10 requests / 24 hours    (ARITIQ_USER_DAILY_LIMIT)

Backed by Upstash Redis when UPSTASH_REDIS_REST_URL / _TOKEN are set (survives
restarts, shared across workers). Falls back to in-process counters otherwise
so local dev works with zero extra infrastructure — fine for a single uvicorn
process, not for a multi-worker deployment.
"""
from __future__ import annotations

import os
import threading
import time

BURST_LIMIT = int(os.environ.get("ARITIQ_USER_BURST_LIMIT", "10"))
BURST_WINDOW = 600      # 10 minutes
DAILY_LIMIT = int(os.environ.get("ARITIQ_USER_DAILY_LIMIT", "10"))
DAILY_WINDOW = 86400    # 24 hours


class RateLimitExceeded(Exception):
    pass


# --- backend selection ------------------------------------------------------

_redis = None
if os.environ.get("UPSTASH_REDIS_REST_URL") and os.environ.get("UPSTASH_REDIS_REST_TOKEN"):
    from upstash_redis import Redis

    _redis = Redis.from_env()

_local: dict[str, tuple[int, float]] = {}  # key -> (count, window_expiry)
_local_lock = threading.Lock()


def _incr(key: str, window_seconds: int) -> int:
    """Increment a fixed-window counter, returning the new count."""
    if _redis is not None:
        count = _redis.incr(key)
        if count == 1:
            _redis.expire(key, window_seconds)
        return count
    now = time.time()
    with _local_lock:
        count, expiry = _local.get(key, (0, 0.0))
        if now >= expiry:
            count, expiry = 0, now + window_seconds
        count += 1
        _local[key] = (count, expiry)
        return count


def check_rate_limit(user_id: str) -> None:
    """Raise RateLimitExceeded if this user is over either window."""
    daily = _incr(f"ratelimit:daily:{user_id}", DAILY_WINDOW)
    if daily > DAILY_LIMIT:
        raise RateLimitExceeded(
            f"Daily limit of {DAILY_LIMIT} audits reached. Try again tomorrow."
        )
    burst = _incr(f"ratelimit:burst:{user_id}", BURST_WINDOW)
    if burst > BURST_LIMIT:
        raise RateLimitExceeded(
            f"Slow down — at most {BURST_LIMIT} audits per "
            f"{BURST_WINDOW // 60} minutes. Try again in a few minutes."
        )
