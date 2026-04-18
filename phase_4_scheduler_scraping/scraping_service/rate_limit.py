from __future__ import annotations

import random
import time


class TokenBucketRateLimiter:
    """Simple 1-token token bucket for polite crawling.

    interval_seconds: seconds between allowed requests.
    jitter_max_seconds: uniform jitter added on top of the wait.
    """

    def __init__(
        self,
        interval_seconds: float,
        jitter_max_seconds: float = 0.0,
        rng: random.Random | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        self.interval = interval_seconds
        self.jitter_max = jitter_max_seconds
        self._rng = rng or random.Random()
        self._clock = clock
        self._sleep = sleep
        self._next_allowed: float = 0.0

    def wait(self) -> float:
        now = self._clock()
        delay = max(0.0, self._next_allowed - now)
        jitter = self._rng.uniform(0, self.jitter_max) if self.jitter_max else 0.0
        total = delay + jitter
        if total > 0:
            self._sleep(total)
        self._next_allowed = self._clock() + self.interval
        return total
