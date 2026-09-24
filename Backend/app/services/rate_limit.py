"""
In-memory sliding-window rate limiter. Deliberately no Redis — a single
Render web service is the deployment target, so process memory is enough.
State resets on restart, which is acceptable for abuse protection.
"""

import time
from collections import defaultdict

from fastapi import Request

# bucket name -> key (ip / email) -> list of timestamps within the window
_buckets: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))


def client_ip(request: Request) -> str:
    # Render (and most PaaS) terminate TLS at a proxy and pass the real IP here.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(bucket: str, key: str, max_calls: int, window_seconds: int) -> bool:
    """Returns True if the call is allowed (and records it), False if the limit is hit."""
    now = time.time()
    hits = _buckets[bucket][key]
    hits[:] = [t for t in hits if now - t < window_seconds]
    if len(hits) >= max_calls:
        return False
    hits.append(now)
    return True


def seconds_until_reset(bucket: str, key: str, window_seconds: int) -> int:
    hits = _buckets[bucket].get(key) or []
    if not hits:
        return 0
    return max(0, int(window_seconds - (time.time() - min(hits))))
