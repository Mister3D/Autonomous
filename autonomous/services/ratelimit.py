"""In-memory sliding-window rate limiter (mono-user self-host)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Allow at most ``limit`` events per ``window_s`` seconds for a key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, *, limit: int, window_s: float) -> bool:
        """Record an attempt. Return True if allowed, False if over the limit."""
        now = time.monotonic()
        cutoff = now - window_s
        with self._lock:
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()


# Shared buckets used by HTTP routes (tests can .clear()).
LOGIN = RateLimiter()
HOOKS = RateLimiter()
PAIRING = RateLimiter()
