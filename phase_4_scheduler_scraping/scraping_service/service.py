from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Optional

import yaml  # type: ignore

from .fetcher import Fetcher, FetchError
from .models import (
    DocumentChangedEvent,
    ParsedDocument,
    ScrapeReport,
    ScrapeResult,
    Source,
)
from .parser import GrowwSchemePageParser
from .persistence import Storage
from .rate_limit import TokenBucketRateLimiter
from .validator import Validator

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256(data: str) -> str:
    return "sha256:" + hashlib.sha256(data.encode("utf-8")).hexdigest()


class CircuitBreakerOpen(Exception):
    """Aborts the run when too many URLs have failed."""


class ScrapingService:
    """Orchestrates fetch → parse → validate → persist for every source.

    Contract (from architecture §4.4):
      - Per-URL retries with exponential backoff.
      - Circuit breaker: abort if > N% of URLs fail.
      - Checksum diff: unchanged sources skip downstream work.
      - Emits DocumentChangedEvent only for changed sources.
    """

    def __init__(
        self,
        sources: list[Source],
        scraper_config: dict,
        storage: Storage,
        fetcher: Optional[Fetcher] = None,
        parser: Optional[GrowwSchemePageParser] = None,
        validator: Optional[Validator] = None,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        event_emitter: Optional[Callable[[DocumentChangedEvent], None]] = None,
        last_checksums: Optional[dict[str, str]] = None,
    ):
        self.sources = sources
        self.cfg = scraper_config
        self.storage = storage
        self.parser = parser or GrowwSchemePageParser()

        fcfg = scraper_config["fetcher"]
        self.fetcher = fetcher or Fetcher(
            user_agent=fcfg["user_agent"],
            nav_timeout_ms=fcfg.get("nav_timeout_ms", 30000),
            wait_until=fcfg.get("wait_until", "networkidle"),
            anchor_selector_text=fcfg.get("anchor_selector_text"),
        )

        pcfg = scraper_config["politeness"]
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter(
            interval_seconds=pcfg["rate_limit_per_seconds"],
            jitter_max_seconds=pcfg.get("jitter_max_seconds", 0),
        )

        required = scraper_config["required_fields"]
        tracked = scraper_config.get("tracked_fields") or [
            "scheme", "expense_ratio", "exit_load",
            "min_sip", "min_lumpsum", "lock_in",
            "risk", "benchmark", "fund_manager", "aum", "launch_date",
        ]
        self.validator = validator or Validator(
            required_fields=required, tracked_fields=tracked
        )

        self.event_emitter = event_emitter or (lambda e: log.info("DocumentChangedEvent: %s", e))
        self.last_checksums = last_checksums or {}

    def run(
        self,
        run_id: str,
        source_ids: Optional[Iterable[str]] = None,
        force: bool = False,
    ) -> ScrapeReport:
        wanted = set(source_ids) if source_ids else None
        targets = [s for s in self.sources if not wanted or s.id in wanted]

        report = ScrapeReport(run_id=run_id, started_at=_now_iso())
        cb_fraction = self.cfg["circuit_breaker"]["abort_if_failed_fraction_exceeds"]
        drift_threshold = self.cfg["drift"]["required_field_extraction_threshold"]

        extraction_ratios: list[float] = []

        for src in targets:
            self._check_circuit_breaker(report, len(targets), cb_fraction)
            self.rate_limiter.wait()
            result = self._process_source(run_id, src, force)
            report.results.append(result)

        report.finished_at = _now_iso()

        # Drift alert across the run
        if extraction_ratios:
            avg_ratio = sum(extraction_ratios) / len(extraction_ratios)
            if avg_ratio < drift_threshold:
                log.error(
                    "groww_selector_drift: avg extraction ratio %.2f < %.2f",
                    avg_ratio, drift_threshold,
                )

        report_rel = self.cfg["persistence"]["report_path"]
        self.storage.write_report(report_rel, report.to_dict())
        return report

    def _check_circuit_breaker(
        self, report: ScrapeReport, total: int, threshold: float
    ) -> None:
        failed = sum(1 for r in report.results if r.status == "failed")
        if total and (failed / total) > threshold:
            raise CircuitBreakerOpen(
                f"{failed}/{total} URLs failed — aborting; previous snapshot stays live"
            )

    def _process_source(
        self, run_id: str, src: Source, force: bool
    ) -> ScrapeResult:
        try:
            html = self._fetch_with_retry(src)
        except FetchError as e:
            log.error("fetch failed for %s: %s", src.id, e)
            return ScrapeResult(source_id=src.id, status="failed", error=str(e))

        checksum = _sha256(html)
        previous = self.last_checksums.get(src.id)
        if not force and previous and previous == checksum:
            return ScrapeResult(
                source_id=src.id, status="unchanged", checksum=checksum
            )

        html_path = self.storage.write_html(run_id, src.id, html)

        try:
            doc: ParsedDocument = self.parser.parse(src, html)
        except Exception as e:
            log.exception("parse failed for %s", src.id)
            return ScrapeResult(
                source_id=src.id, status="degraded", checksum=checksum,
                error=f"parse error: {e}",
            )

        validation = self.validator.validate(doc)
        if not validation.ok:
            log.warning(
                "validation failed for %s: missing=%s", src.id, validation.missing_required
            )
            return ScrapeResult(
                source_id=src.id, status="degraded", checksum=checksum,
                fields_extracted=len(doc.facts),
                error=validation.error,
            )

        json_path = self.storage.write_structured(
            run_id, src.id, doc.to_json_dict()
        )

        self.event_emitter(
            DocumentChangedEvent(
                run_id=run_id,
                source_id=src.id,
                source_url=src.url,
                scheme=src.scheme,
                structured_json_path=json_path,
                html_path=html_path,
                checksum=checksum,
            )
        )

        return ScrapeResult(
            source_id=src.id, status="changed", checksum=checksum,
            fields_extracted=len(doc.facts),
        )

    def _fetch_with_retry(self, src: Source) -> str:
        attempts = self.cfg["retry"]["per_url_attempts"]
        backoff = self.cfg["retry"]["backoff_seconds"]
        last_exc: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                return self.fetcher.fetch(src.url).html
            except Exception as e:
                last_exc = e
                if attempt >= attempts:
                    break
                delay = backoff[min(attempt - 1, len(backoff) - 1)]
                log.warning(
                    "fetch attempt %d/%d failed for %s: %s — sleeping %ds",
                    attempt, attempts, src.id, e, delay,
                )
                time.sleep(delay)
        raise FetchError(f"all {attempts} attempts failed for {src.url}: {last_exc}")


def load_sources(path: str | Path) -> list[Source]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return [Source(**entry) for entry in raw]


def load_scraper_config(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))
