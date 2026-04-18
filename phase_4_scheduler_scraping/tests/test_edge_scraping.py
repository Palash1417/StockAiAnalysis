"""Edge-case tests mapped to doc/edgecase.md §2 (Scraping Service).

Only scenarios whose guard lives inside phase-4 code are covered here;
workflow-level concerns (GitHub delay, retry workflow, Slack alerts) belong
to integration / ops tests.
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from scraping_service.fetcher import FetchError
from scraping_service.fetcher.fetcher import RobotsCache
from scraping_service.models import DocumentChangedEvent, ParsedDocument, Source
from scraping_service.parser import GrowwSchemePageParser
from scraping_service.persistence import LocalStorage
from scraping_service.rate_limit import TokenBucketRateLimiter
from scraping_service.service import ScrapingService, _sha256
from scraping_service.validator import Validator


BASE_CFG = {
    "fetcher": {"user_agent": "test/1.0"},
    "politeness": {"rate_limit_per_seconds": 0, "jitter_max_seconds": 0},
    "retry": {"per_url_attempts": 1, "backoff_seconds": [0]},
    "circuit_breaker": {"abort_if_failed_fraction_exceeds": 0.5},
    "drift": {"required_field_extraction_threshold": 0.7},
    "required_fields": ["scheme", "expense_ratio", "exit_load"],
    "tracked_fields": ["scheme", "expense_ratio", "exit_load"],
    "persistence": {"report_path": "artifacts/scrape_report.json"},
}


class FakeFetcher:
    def __init__(self, responses):
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
# §2.1 — Groww selector drift: required field goes missing → degraded, no event
# ---------------------------------------------------------------------------
def test_selector_drift_marks_degraded_and_blocks_event(tmp_path: Path):
    src = make_source(1)
    # Parser no longer finds exit_load (DOM redesign).
    parser = FakeParser({src.id: {"scheme": "x", "expense_ratio": "0.6%"}})
    fetcher = FakeFetcher({src.url: "<html>redesigned</html>"})
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=no_wait_limiter(),
        event_emitter=events.append,
    )
    report = service.run(run_id="drift1")

    assert report.summary["degraded"] == 1
    assert report.summary["changed"] == 0
    assert events == []  # previous snapshot stays live
    assert "missing field" in (report.results[0].error or "")


def test_drift_ratio_computed_across_tracked_fields():
    """Validator exposes extraction_ratio for the drift alert (§2.1)."""
    v = Validator(
        required_fields=["scheme"],
        tracked_fields=[
            "scheme", "expense_ratio", "exit_load",
            "benchmark", "min_sip", "min_lumpsum",
            "lock_in", "risk", "fund_manager", "aum",
        ],
    )
    doc = ParsedDocument(
        source_id="src_x", scheme="x",
        facts={"scheme": "x", "expense_ratio": "0.6%"},
    )
    result = v.validate(doc)
    assert result.ok is True
    assert result.extraction_ratio == pytest.approx(0.2)
    # This ratio < 0.7 drift threshold → alert would fire at the run level.


# ---------------------------------------------------------------------------
# §2.2 — Playwright timeout → httpx fallback (unit-level, via the real Fetcher)
# ---------------------------------------------------------------------------
def test_playwright_failure_falls_back_to_httpx(monkeypatch):
    from scraping_service.fetcher.fetcher import Fetcher

    f = Fetcher(user_agent="test/1.0")
    # Skip robots.txt network call.
    monkeypatch.setattr(f.robots, "can_fetch", lambda url: True)
    monkeypatch.setattr(
        f, "_fetch_playwright", lambda url: (_ for _ in ()).throw(TimeoutError("networkidle"))
    )
    monkeypatch.setattr(f, "_fetch_httpx", lambda url: "<html>fallback</html>")

    result = f.fetch("https://example.test/x")
    assert result.method == "httpx"
    assert "fallback" in result.html


def test_fetcher_raises_when_both_methods_fail(monkeypatch):
    from scraping_service.fetcher.fetcher import Fetcher

    f = Fetcher(user_agent="test/1.0")
    monkeypatch.setattr(f.robots, "can_fetch", lambda url: True)
    monkeypatch.setattr(
        f, "_fetch_playwright", lambda url: (_ for _ in ()).throw(RuntimeError("pw down"))
    )
    monkeypatch.setattr(
        f, "_fetch_httpx", lambda url: (_ for _ in ()).throw(RuntimeError("http down"))
    )

    with pytest.raises(FetchError):
        f.fetch("https://example.test/x")


# ---------------------------------------------------------------------------
# §2.3 — 200 OK but empty skeleton HTML → checksum changes, validator degrades
# ---------------------------------------------------------------------------
def test_skeleton_html_changes_checksum_but_never_emits_event(tmp_path: Path):
    src = make_source(2)
    fetcher = FakeFetcher({src.url: "<html><body></body></html>"})
    parser = FakeParser({src.id: {}})  # nothing extractable
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=no_wait_limiter(),
        event_emitter=events.append,
    )
    report = service.run(run_id="skel1")

    assert report.summary["degraded"] == 1
    assert events == []
    # Raw HTML still persisted for forensics
    assert (tmp_path / "corpus" / "skel1" / f"{src.id}.html").exists()
    # But structured JSON NOT persisted when degraded
    assert not (tmp_path / "corpus" / "skel1" / f"{src.id}.json").exists()


# ---------------------------------------------------------------------------
# §2.4 — robots.txt disallows the URL → FetchError → source marked failed
# ---------------------------------------------------------------------------
def test_robots_disallow_raises_fetch_error(monkeypatch):
    from scraping_service.fetcher.fetcher import Fetcher

    f = Fetcher(user_agent="test/1.0")
    monkeypatch.setattr(f.robots, "can_fetch", lambda url: False)

    with pytest.raises(FetchError, match="robots.txt disallows"):
        f.fetch("https://example.test/blocked")


def test_robots_disallow_marks_source_failed_end_to_end(tmp_path: Path):
    src = make_source(3)
    fetcher = FakeFetcher({src.url: FetchError("robots.txt disallows fetching")})
    parser = FakeParser({})
    storage = LocalStorage(str(tmp_path))

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=no_wait_limiter(),
    )
    report = service.run(run_id="rob1")
    assert report.summary["failed"] == 1
    assert "robots.txt" in (report.results[0].error or "")


def test_robots_cache_reuses_parser_for_same_host(monkeypatch):
    """§2.4 — robots.txt fetched once per host per day."""
    calls = {"n": 0}

    class StubRP:
        def set_url(self, u): pass
        def read(self):
            calls["n"] += 1
        def can_fetch(self, ua, url): return True

    monkeypatch.setattr(
        "scraping_service.fetcher.fetcher.robotparser.RobotFileParser", StubRP
    )
    cache = RobotsCache(user_agent="test/1.0")
    cache.can_fetch("https://example.test/a")
    cache.can_fetch("https://example.test/b")
    cache.can_fetch("https://example.test/c")
    assert calls["n"] == 1  # same host → single read


# ---------------------------------------------------------------------------
# §2.5 — Rate limiter serializes requests even across URLs
# ---------------------------------------------------------------------------
def test_rate_limiter_called_before_each_source(tmp_path: Path):
    srcs = [make_source(i) for i in range(1, 4)]
    fetcher = FakeFetcher({s.url: "<html>x</html>" for s in srcs})
    parser = FakeParser(
        {s.id: {"scheme": s.scheme, "expense_ratio": "0.6%", "exit_load": "1%"} for s in srcs}
    )

    waits: list[float] = []

    class CountingLimiter:
        def wait(self):
            waits.append(0.0)
            return 0.0

    storage = LocalStorage(str(tmp_path))
    service = ScrapingService(
        sources=srcs, scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=CountingLimiter(),
    )
    service.run(run_id="rl1")
    assert len(waits) == len(srcs)


# ---------------------------------------------------------------------------
# §2.7 — Two sources with identical HTML still produce isolated results
# ---------------------------------------------------------------------------
def test_identical_html_across_sources_keeps_ids_isolated(tmp_path: Path):
    s1, s2 = make_source(10), make_source(11)
    shared_html = "<html>template</html>"
    fetcher = FakeFetcher({s1.url: shared_html, s2.url: shared_html})
    parser = FakeParser(
        {
            s1.id: {"scheme": s1.scheme, "expense_ratio": "0.6%", "exit_load": "1%"},
            s2.id: {"scheme": s2.scheme, "expense_ratio": "0.9%", "exit_load": "2%"},
        }
    )
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[s1, s2], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=no_wait_limiter(),
        event_emitter=events.append,
    )
    report = service.run(run_id="dup1")

    assert report.summary["changed"] == 2
    assert {e.source_id for e in events} == {s1.id, s2.id}
    # Same checksum is acceptable — source_id is what keys the artifacts.
    assert events[0].checksum == events[1].checksum


# ---------------------------------------------------------------------------
# §2.8 — Checksum is computed on raw HTML, BEFORE normalization
# ---------------------------------------------------------------------------
def test_whitespace_changes_flip_checksum(tmp_path: Path):
    src = make_source(4)
    html_v1 = "<html>  spaced  </html>"
    # Same text content, different whitespace → different raw bytes → new checksum.
    html_v2 = "<html>spaced</html>"

    fetcher = FakeFetcher({src.url: html_v2})
    parser = FakeParser(
        {src.id: {"scheme": src.scheme, "expense_ratio": "0.6%", "exit_load": "1%"}}
    )
    storage = LocalStorage(str(tmp_path))
    events: list[DocumentChangedEvent] = []

    service = ScrapingService(
        sources=[src], scraper_config=BASE_CFG, storage=storage,
        fetcher=fetcher, parser=parser, rate_limiter=no_wait_limiter(),
        event_emitter=events.append,
        last_checksums={src.id: _sha256(html_v1)},
    )
    report = service.run(run_id="ws1")
    # The raw HTML differs → status is "changed", not "unchanged".
    assert report.summary["changed"] == 1
    assert report.summary["unchanged"] == 0


# ---------------------------------------------------------------------------
# Parser smoke: a representative Groww-like HTML fragment yields required facts
# ---------------------------------------------------------------------------
def test_groww_parser_extracts_labeled_facts():
    html = """
    <html><body>
      <h2>Fund Details</h2>
      <div>Expense Ratio: 0.67%</div>
      <div>Exit Load: 1% if redeemed within 1 year</div>
      <div>Min SIP: ₹500</div>
      <div>Benchmark: NIFTY Smallcap 250 TRI</div>
    </body></html>
    """
    src = make_source(99)
    doc = GrowwSchemePageParser().parse(src, html)
    assert doc.facts.get("expense_ratio", "").startswith("0.67")
    assert "1%" in doc.facts.get("exit_load", "")
    assert "500" in doc.facts.get("min_sip", "")
    assert "NIFTY" in doc.facts.get("benchmark", "")
    # scheme falls back to source.scheme when page doesn't label it
    assert doc.facts["scheme"] == src.scheme
