"""IP-based token-bucket rate limiter — Starlette middleware.

Default: 20 requests per 60-second window per IP.
Returns HTTP 429 with Retry-After header on breach.
"""
from __future__ import annotations

import time
from collections import defaultdict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


class _Bucket:
    """Simple token-bucket tracking for one IP."""

    def __init__(self, capacity: int, refill_rate: float):
        self.tokens = float(capacity)
        self.capacity = capacity
        self.refill_rate = refill_rate   # tokens per second
        self.last_refill = time.monotonic()

    def consume(self) -> bool:
        """Try to consume 1 token. Returns True if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP token-bucket rate limiter.

    Parameters
    ----------
    max_requests:
        Burst capacity (tokens in bucket).
    window_seconds:
        Time window used to compute the steady-state refill rate
        (refill_rate = max_requests / window_seconds).
    exempt_paths:
        Paths that bypass rate limiting (e.g., /health).
    """

    def __init__(
        self,
        app,
        max_requests: int = 20,
        window_seconds: int = 60,
        exempt_paths: tuple[str, ...] = ("/health", "/docs", "/openapi.json"),
    ):
        super().__init__(app)
        self._capacity = max_requests
        self._refill_rate = max_requests / window_seconds
        self._exempt = exempt_paths
        self._buckets: dict[str, _Bucket] = defaultdict(
            lambda: _Bucket(self._capacity, self._refill_rate)
        )

    async def dispatch(self, request: Request, call_next):
        if request.url.path in self._exempt:
            return await call_next(request)

        ip = (request.client.host if request.client else "unknown") or "unknown"
        bucket = self._buckets[ip]

        if not bucket.consume():
            retry_after = int(1 / self._refill_rate) + 1
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please slow down."},
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
