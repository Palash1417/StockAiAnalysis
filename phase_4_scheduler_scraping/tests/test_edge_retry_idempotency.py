"""Edge-case tests for retry, idempotency, circuit breaker boundary (edgecase.md §2.6, §2.9)."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Iterator

import pytest

from scraping_service.fetcher import FetchError
from scraping_service.models import DocumentChangedEvent, ParsedDocument, Source
from scraping_service.persistence import LocalStorage
from scraping_service.rate_limit import TokenBucketRateLimiter
from scraping_service.service import CircuitBreakerOpen, ScrapingService, _sha256


BASE_CFG = {
    "fetcher": {"user_agent": "test/1.0"},
    "politeness": {"rate_limit_per_seconds": 0, "jitter_max_seconds": 0},
    "retry": {"per_url_attempts": 3, "backoff_seconds": [0, 0, 0]},
    "circuit_breaker": {"abort_if_failed_fraction_exceeds": 0.5},
    "drift": {"required_field_extraction_threshold": 0.7},
    "required_fields": ["scheme", "expense_ratio", "exit_load"],
    "tracked_fields": ["scheme", "expense_ratio", "exit_load"],
    "persistence": {"report_path": "artifacts/scrape_report.json"},
}


class SequenceFetcher:
    """Returns a scripted sequence per URL — Exceptions are raised."""

    def __init__(self, script: dict[str, list]):
        self._script: dict[str, Iterator] = {k: iter(v) for k, v in script.items()}
        self.calls: list[str] = []

    def fetch(self, url):
        self.calls.append(url)
        item = next(self._script[url])
        if isinstance(item, Exception):
            raise item

        class _FR:
            html = item
        return _FR()


class FakeParser:
    def __init__(self, facts_by_source):
        self.facts_by_source = facts_by_source

    def parse(self, source: Source, html: str):
        return ParsedDocument(
            source_id=source.id,
            scheme=source.scheme,
            facts=dict(self.facts_by_source.get(source.id, {})),
        )


def no_wait_limiter():
    return TokenBucketRateLimiter(
        interval_seconds=0,
        jitter_max_seconds=0,
        rng=random.Random(0),
        clock=lambda: 0.0,
        sleep=lambda s: None,
    )


def make_source(i: int) -> Source:
    return Source(
        id=f"src_{i:03d}",
        url=f"https://example.test/{i}",
        type="scheme_page",
        scheme=f"Scheme {i}",
        category="x",
        source_class="groww",
    )


# ---------------------------------------------------------------------------
# Retry path — transient error, then success on attempt 3
# ---------------------------------------------------------------------------
def test_retry_succeeds_on_third_attempt(tmp_path: Path, monkeypatch):
    # Skip real sleeps between retries
    monkeypatch.setattr("scraping_service.service.time.sleep", lambda s: None)

    src = make_source(1)
    fetcher = SequenceFetcher(
        {
            src.url: [
                FetchError("transient 500"),
                FetchError("transient 500"),
                "<html>ok</html>",
            ]
        }
    )
    parser = FakeParser(
        {src.id: {"scheme": src.scheme, "expense_ratio": "0.6%", "exit_load": "1%"}}
    )
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=no_wait_limiter(),
        event_emitter=events.append,
    )
    report = service.run(run_id="retry1")

    assert fetcher.calls == [src.url, src.url, src.url]
    assert report.summary["changed"] == 1
    assert len(events) == 1


def test_retry_exhausted_marks_failed(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("scraping_service.service.time.sleep", lambda s: None)

    src = make_source(2)
    fetcher = SequenceFetcher(
        {src.url: [FetchError("a"), FetchError("b"), FetchError("c")]}
    )
    storage = LocalStorage(str(tmp_path))

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=FakeParser({}), rate_limiter=no_wait_limiter(),
    )
    report = service.run(run_id="retry2")

    assert fetcher.calls == [src.url] * 3
    assert report.summary["failed"] == 1
    assert "3 attempts failed" in (report.results[0].error or "")


# ---------------------------------------------------------------------------
# Circuit breaker 50 % boundary (edgecase §2.6)
# ---------------------------------------------------------------------------
def test_circuit_breaker_does_not_trip_at_exactly_50_pct(tmp_path: Path):
    """2 of 4 failing = 0.5, which is NOT > 0.5 → run continues."""
    srcs = [make_source(i) for i in range(1, 5)]
    responses = {
        srcs[0].url: FetchError("down"),
        srcs[1].url: FetchError("down"),
        srcs[2].url: "<html>ok</html>",
        srcs[3].url: "<html>ok</html>",
    }

    class SingleShotFetcher:
        def __init__(self, table):
            self.table = table

        def fetch(self, url):
            r = self.table[url]
            if isinstance(r, Exception):
                raise r

            class _FR:
                html = r
            return _FR()

    cfg = dict(BASE_CFG)
    cfg["retry"] = {"per_url_attempts": 1, "backoff_seconds": [0]}

    parser = FakeParser(
        {
            s.id: {"scheme": s.scheme, "expense_ratio": "0.6%", "exit_load": "1%"}
            for s in srcs
        }
    )
    storage = LocalStorage(str(tmp_path))

    service = ScrapingService(
        sources=srcs, scraper_config=cfg, storage=storage,
        fetcher=SingleShotFetcher(responses), parser=parser,
        rate_limiter=no_wait_limiter(),
    )
    report = service.run(run_id="cb50")
    assert report.summary["failed"] == 2
    assert report.summary["changed"] == 2


def test_circuit_breaker_trips_when_strictly_over_50_pct(tmp_path: Path):
    """3 of 4 failed processed before the 4th is attempted → 0.75 > 0.5 → abort."""
    srcs = [make_source(i) for i in range(1, 5)]
    responses = {
        srcs[0].url: FetchError("down"),
        srcs[1].url: FetchError("down"),
        srcs[2].url: FetchError("down"),
        srcs[3].url: "<html>ok</html>",
    }

    class SingleShotFetcher:
        def __init__(self, table):
            self.table = table

        def fetch(self, url):
            r = self.table[url]
            if isinstance(r, Exception):
                raise r

            class _FR:
                html = r
            return _FR()

    cfg = dict(BASE_CFG)
    cfg["retry"] = {"per_url_attempts": 1, "backoff_seconds": [0]}

    storage = LocalStorage(str(tmp_path))
    service = ScrapingService(
        sources=srcs, scraper_config=cfg, storage=storage,
        fetcher=SingleShotFetcher(responses), parser=FakeParser({}),
        rate_limiter=no_wait_limiter(),
    )

    with pytest.raises(CircuitBreakerOpen):
        service.run(run_id="cb75")


# ---------------------------------------------------------------------------
# §2.9 — force=true bypasses the checksum cache
# ---------------------------------------------------------------------------
def test_force_flag_reprocesses_even_when_checksum_matches(tmp_path: Path):
    src = make_source(5)
    html = "<html>identical</html>"

    class OneShot:
        def __init__(self, r): self.r = r
        def fetch(self, url):
            class _FR: html = self.r
            return _FR()

    parser = FakeParser(
        {src.id: {"scheme": src.scheme, "expense_ratio": "0.6%", "exit_load": "1%"}}
    )
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=OneShot(html), parser=parser,
        rate_limiter=no_wait_limiter(),
        event_emitter=events.append,
        last_checksums={src.id: _sha256(html)},
    )

    # Without force → unchanged
    report_a = service.run(run_id="f0", force=False)
    assert report_a.summary["unchanged"] == 1
    assert events == []

    # With force → reprocessed even though checksum matches
    report_b = service.run(run_id="f1", force=True)
    assert report_b.summary["changed"] == 1
    assert len(events) == 1


# ---------------------------------------------------------------------------
# Report/artifact invariants — ScrapeReport persisted on every run
# ---------------------------------------------------------------------------
def test_report_written_even_when_sources_fail(tmp_path: Path):
    src = make_source(6)

    class AlwaysFails:
        def fetch(self, url):
            raise FetchError("nope")

    cfg = dict(BASE_CFG)
    cfg["retry"] = {"per_url_attempts": 1, "backoff_seconds": [0]}

    storage = LocalStorage(str(tmp_path))
    service = ScrapingService(
        sources=[src], scraper_config=cfg, storage=storage,
        fetcher=AlwaysFails(), parser=FakeParser({}),
        rate_limiter=no_wait_limiter(),
    )
    report = service.run(run_id="rep1")
    assert report.summary["failed"] == 1
    assert (tmp_path / "artifacts" / "scrape_report.json").exists()


def test_sources_filter_processes_only_requested(tmp_path: Path):
    """CLI's --sources flag ends up here."""
    s1, s2 = make_source(7), make_source(8)

    class OnlyS2:
        def fetch(self, url):
            if url == s2.url:
                class _FR: html = "<html>s2</html>"
                return _FR()
            raise AssertionError(f"unexpected fetch: {url}")

    parser = FakeParser(
        {s2.id: {"scheme": s2.scheme, "expense_ratio": "0.6%", "exit_load": "1%"}}
    )
    storage = LocalStorage(str(tmp_path))
    service = ScrapingService(
        sources=[s1, s2], scraper_config=BASE_CFG, storage=storage,
        fetcher=OnlyS2(), parser=parser, rate_limiter=no_wait_limiter(),
    )
    report = service.run(run_id="sel1", source_ids=[s2.id])
    assert {r.source_id for r in report.results} == {s2.id}
    assert report.summary["changed"] == 1
