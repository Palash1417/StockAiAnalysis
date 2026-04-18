import random
from pathlib import Path

import pytest

from scraping_service.fetcher import FetchError
from scraping_service.models import DocumentChangedEvent, Source
from scraping_service.persistence import LocalStorage
from scraping_service.rate_limit import TokenBucketRateLimiter
from scraping_service.service import CircuitBreakerOpen, ScrapingService, _sha256


SCRAPER_CFG = {
    "fetcher": {"user_agent": "test/1.0"},
    "politeness": {"rate_limit_per_seconds": 0, "jitter_max_seconds": 0},
    "retry": {"per_url_attempts": 1, "backoff_seconds": [0]},
    "circuit_breaker": {"abort_if_failed_fraction_exceeds": 0.5},
    "drift": {"required_field_extraction_threshold": 0.7},
    "required_fields": ["scheme", "expense_ratio", "exit_load"],
    "tracked_fields": ["scheme", "expense_ratio", "exit_load"],
    "persistence": {"report_path": "artifacts/scrape_report.json"},
}


class _FakeFetcher:
    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[str] = []

    def fetch(self, url):
        self.calls.append(url)
        r = self.responses[url]
        if isinstance(r, Exception):
            raise r

        class _FR:
            html = r
        return _FR()


class _FakeParser:
    def __init__(self, facts_by_source: dict[str, dict]):
        self.facts_by_source = facts_by_source

    def parse(self, source: Source, html: str):
        from scraping_service.models import ParsedDocument
        return ParsedDocument(
            source_id=source.id,
            scheme=source.scheme,
            facts=dict(self.facts_by_source.get(source.id, {})),
        )


def _no_wait_limiter():
    return TokenBucketRateLimiter(
        interval_seconds=0,
        jitter_max_seconds=0,
        rng=random.Random(0),
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )


def _source(i: int) -> Source:
    return Source(
        id=f"src_{i:03d}",
        url=f"https://example.test/{i}",
        type="scheme_page",
        scheme=f"Scheme {i}",
        category="x",
        source_class="groww",
    )


def test_unchanged_when_checksum_matches(tmp_path: Path):
    src = _source(1)
    html = "<html>same</html>"
    fetcher = _FakeFetcher({src.url: html})
    parser = _FakeParser({src.id: {"scheme": "x", "expense_ratio": "0.6%", "exit_load": "1%"}})
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=SCRAPER_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=_no_wait_limiter(),
        event_emitter=events.append,
        last_checksums={src.id: _sha256(html)},
    )

    report = service.run(run_id="r1")
    assert report.summary["unchanged"] == 1
    assert events == []


def test_changed_emits_event_and_persists(tmp_path: Path):
    src = _source(2)
    html = "<html>fresh</html>"
    fetcher = _FakeFetcher({src.url: html})
    parser = _FakeParser({src.id: {"scheme": "x", "expense_ratio": "0.6%", "exit_load": "1%"}})
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=SCRAPER_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=_no_wait_limiter(),
        event_emitter=events.append,
    )

    report = service.run(run_id="r2")
    assert report.summary["changed"] == 1
    assert len(events) == 1
    assert events[0].source_id == src.id
    assert (tmp_path / "corpus" / "r2" / f"{src.id}.html").exists()
    assert (tmp_path / "corpus" / "r2" / f"{src.id}.json").exists()


def test_missing_required_field_marks_degraded(tmp_path: Path):
    src = _source(3)
    fetcher = _FakeFetcher({src.url: "<html>ok</html>"})
    # No exit_load → validator marks degraded
    parser = _FakeParser({src.id: {"scheme": "x", "expense_ratio": "0.6%"}})
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=SCRAPER_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=_no_wait_limiter(),
        event_emitter=events.append,
    )

    report = service.run(run_id="r3")
    assert report.summary["degraded"] == 1
    assert events == []
    assert report.results[0].error == "missing field: exit_load"


def test_circuit_breaker_aborts_when_majority_fail(tmp_path: Path):
    srcs = [_source(i) for i in range(1, 5)]
    fetcher = _FakeFetcher({s.url: FetchError("nope") for s in srcs})
    parser = _FakeParser({})
    storage = LocalStorage(str(tmp_path))

    service = ScrapingService(
        sources=srcs, scraper_config=SCRAPER_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=_no_wait_limiter(),
    )

    with pytest.raises(CircuitBreakerOpen):
        service.run(run_id="r4")
