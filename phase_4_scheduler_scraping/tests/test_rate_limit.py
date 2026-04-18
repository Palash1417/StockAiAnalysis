import random

from scraping_service.rate_limit import TokenBucketRateLimiter


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_first_call_does_not_block():
    clock = FakeClock()
    rl = TokenBucketRateLimiter(
        interval_seconds=3.0,
        jitter_max_seconds=0.0,
        rng=random.Random(0),
        clock=clock.now,
        sleep=clock.sleep,
    )
    waited = rl.wait()
    assert waited == 0.0


def test_subsequent_call_waits_interval():
    clock = FakeClock()
    rl = TokenBucketRateLimiter(
        interval_seconds=3.0,
        jitter_max_seconds=0.0,
        rng=random.Random(0),
        clock=clock.now,
        sleep=clock.sleep,
    )
    rl.wait()
    waited = rl.wait()
    assert waited == 3.0


def test_jitter_bounded():
    clock = FakeClock()
    rl = TokenBucketRateLimiter(
        interval_seconds=3.0,
        jitter_max_seconds=60.0,
        rng=random.Random(42),
        clock=clock.now,
        sleep=clock.sleep,
    )
    rl.wait()
    waited = rl.wait()
    # interval 3s + jitter [0, 60]
    assert 3.0 <= waited <= 63.0
