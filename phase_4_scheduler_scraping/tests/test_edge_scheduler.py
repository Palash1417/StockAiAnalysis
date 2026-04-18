"""Edge-case tests for the scheduler surface (edgecase.md §1).

Covers:
  §1.2 singleton / workflow declaration   → workflow YAML shape
  §1.3 retry workflow wiring              → retry-failed-ingest.yml shape
  §1.4 admin trigger dispatch             → admin_trigger payload + auth
  §1.6 runner FS is ephemeral             → BASE_DIR overridable, report path
  CLI exit codes: 0 clean, 1 partial-fail, 2 circuit-breaker-open
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scraping_service.models import ScrapeReport, ScrapeResult
from scraping_service.service import CircuitBreakerOpen


REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_YML = REPO_ROOT / ".github" / "workflows" / "ingest.yml"
RETRY_YML = REPO_ROOT / ".github" / "workflows" / "retry-failed-ingest.yml"


# ---------------------------------------------------------------------------
# §1.2 — singleton concurrency + §1.3 retry companion
# ---------------------------------------------------------------------------
def test_ingest_workflow_has_singleton_concurrency():
    text = INGEST_YML.read_text()
    assert "concurrency:" in text
    assert "group: ingest-groww" in text
    # Must NOT cancel: queue behavior
    assert "cancel-in-progress: false" in text


def test_ingest_workflow_runs_at_09_00_ist():
    text = INGEST_YML.read_text()
    # 03:30 UTC = 09:00 IST (architecture §4.3)
    assert 'cron: "30 3 * * *"' in text


def test_ingest_workflow_has_timeout_and_force_input():
    text = INGEST_YML.read_text()
    assert "timeout-minutes: 20" in text
    assert "workflow_dispatch:" in text
    assert "force:" in text


def test_ingest_workflow_uploads_report_as_artifact():
    text = INGEST_YML.read_text()
    assert "upload-artifact" in text
    assert "scrape_report.json" in text
    assert "retention-days: 90" in text


def test_retry_workflow_listens_on_failure_only():
    text = RETRY_YML.read_text()
    assert 'workflows: ["Ingest Groww Corpus"]' in text
    assert "workflow_run" in text
    assert "failure" in text
    # 2 retries cap + 15 min delay (architecture §4.3)
    assert "sleep 900" in text
    assert "run_attempt" in text


# ---------------------------------------------------------------------------
# §1.4 — admin trigger dispatches via GitHub REST
# ---------------------------------------------------------------------------
def test_admin_trigger_rejects_when_token_missing(monkeypatch):
    from scheduler.admin_trigger import dispatch_ingest

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    result = dispatch_ingest(repo="org/repo", token=None)
    assert result.ok is False
    assert "GITHUB_TOKEN" in result.detail


def test_admin_trigger_posts_to_correct_endpoint(monkeypatch):
    from scheduler import admin_trigger

    captured = {}

    class FakeResponse:
        status_code = 204
        text = ""

    class FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    class FakeHttpx:
        Client = FakeClient

    monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)

    result = admin_trigger.dispatch_ingest(
        repo="acme/rag", workflow_file="ingest.yml",
        ref="main", force=True, token="t0k3n",
    )
    assert result.ok is True
    assert result.status_code == 204
    assert captured["url"].endswith(
        "/repos/acme/rag/actions/workflows/ingest.yml/dispatches"
    )
    assert captured["headers"]["Authorization"] == "Bearer t0k3n"
    assert captured["json"]["ref"] == "main"
    assert captured["json"]["inputs"]["force"] == "true"


def test_admin_trigger_propagates_non_204(monkeypatch):
    from scheduler import admin_trigger

    class FakeResponse:
        status_code = 422
        text = "validation failed"

    class FakeClient:
        def __init__(self, *a, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, headers, json): return FakeResponse()

    class FakeHttpx:
        Client = FakeClient

    monkeypatch.setitem(__import__("sys").modules, "httpx", FakeHttpx)

    result = admin_trigger.dispatch_ingest(repo="x/y", token="t")
    assert result.ok is False
    assert result.status_code == 422
    assert "validation failed" in result.detail


# ---------------------------------------------------------------------------
# §1.6 — BASE_DIR overridable so state never lands on ephemeral FS by default
# ---------------------------------------------------------------------------
def test_scraper_base_dir_env_overrides_default(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SCRAPER_BASE_DIR", str(tmp_path / "external-state"))
    # Reload module so the env is picked up at import time
    import importlib
    import scheduler.cli as cli
    importlib.reload(cli)
    try:
        assert cli.BASE_DIR == tmp_path / "external-state"
    finally:
        monkeypatch.delenv("SCRAPER_BASE_DIR", raising=False)
        importlib.reload(cli)


# ---------------------------------------------------------------------------
# CLI exit codes — 0 clean, 1 partial-fail, 2 circuit-breaker
# ---------------------------------------------------------------------------
def _install_fake_service(monkeypatch, tmp_path: Path, report_or_exc):
    """Replace ScrapingService + loaders so CLI doesn't touch the real network."""
    import scheduler.cli as cli

    class FakeService:
        def __init__(self, *a, **kw): pass

        def run(self, run_id, source_ids=None, force=False):
            if isinstance(report_or_exc, Exception):
                raise report_or_exc
            return report_or_exc

    monkeypatch.setattr(cli, "ScrapingService", FakeService)
    monkeypatch.setattr(cli, "load_sources", lambda path: [])
    monkeypatch.setattr(
        cli, "load_scraper_config",
        lambda path: {
            "fetcher": {"user_agent": "t"},
            "politeness": {"rate_limit_per_seconds": 0, "jitter_max_seconds": 0},
            "retry": {"per_url_attempts": 1, "backoff_seconds": [0]},
            "circuit_breaker": {"abort_if_failed_fraction_exceeds": 0.5},
            "drift": {"required_field_extraction_threshold": 0.7},
            "required_fields": [],
            "persistence": {"report_path": "artifacts/scrape_report.json"},
        },
    )
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)


def test_cli_exit_0_on_clean_run(monkeypatch, tmp_path: Path, capsys):
    import scheduler.cli as cli
    report = ScrapeReport(
        run_id="r1", started_at="2026-04-19T09:00:00+05:30",
        finished_at="2026-04-19T09:02:00+05:30",
        results=[ScrapeResult(source_id="src_001", status="unchanged")],
    )
    _install_fake_service(monkeypatch, tmp_path, report)

    code = cli.main(["run", "--force", "false", "--run-id", "r1"])
    assert code == 0
    assert "unchanged=1" in capsys.readouterr().out


def test_cli_exit_1_when_any_source_failed(monkeypatch, tmp_path: Path):
    import scheduler.cli as cli
    report = ScrapeReport(
        run_id="r2", started_at="t", finished_at="t",
        results=[
            ScrapeResult(source_id="src_001", status="changed"),
            ScrapeResult(source_id="src_002", status="failed", error="boom"),
        ],
    )
    _install_fake_service(monkeypatch, tmp_path, report)
    assert cli.main(["run", "--force", "false", "--run-id", "r2"]) == 1


def test_cli_exit_2_when_circuit_breaker_trips(monkeypatch, tmp_path: Path):
    import scheduler.cli as cli
    _install_fake_service(monkeypatch, tmp_path, CircuitBreakerOpen("3/3 failed"))
    assert cli.main(["run", "--force", "false", "--run-id", "r3"]) == 2


def test_cli_parses_force_case_insensitively(monkeypatch, tmp_path: Path):
    import scheduler.cli as cli

    captured = {}

    class FakeService:
        def __init__(self, *a, **kw): pass
        def run(self, run_id, source_ids=None, force=False):
            captured["force"] = force
            return ScrapeReport(run_id=run_id, started_at="t", finished_at="t", results=[])

    monkeypatch.setattr(cli, "ScrapingService", FakeService)
    monkeypatch.setattr(cli, "load_sources", lambda path: [])
    monkeypatch.setattr(
        cli, "load_scraper_config",
        lambda path: {
            "fetcher": {"user_agent": "t"},
            "politeness": {"rate_limit_per_seconds": 0, "jitter_max_seconds": 0},
            "retry": {"per_url_attempts": 1, "backoff_seconds": [0]},
            "circuit_breaker": {"abort_if_failed_fraction_exceeds": 0.5},
            "drift": {"required_field_extraction_threshold": 0.7},
            "required_fields": [],
            "persistence": {"report_path": "artifacts/scrape_report.json"},
        },
    )
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)

    cli.main(["run", "--force", "TRUE", "--run-id", "r4"])
    assert captured["force"] is True
    cli.main(["run", "--force", "False", "--run-id", "r5"])
    assert captured["force"] is False


def test_cli_sources_flag_splits_csv(monkeypatch, tmp_path: Path):
    import scheduler.cli as cli

    captured = {}

    class FakeService:
        def __init__(self, *a, **kw): pass
        def run(self, run_id, source_ids=None, force=False):
            captured["ids"] = source_ids
            return ScrapeReport(run_id=run_id, started_at="t", finished_at="t", results=[])

    monkeypatch.setattr(cli, "ScrapingService", FakeService)
    monkeypatch.setattr(cli, "load_sources", lambda path: [])
    monkeypatch.setattr(
        cli, "load_scraper_config",
        lambda path: {
            "fetcher": {"user_agent": "t"},
            "politeness": {"rate_limit_per_seconds": 0, "jitter_max_seconds": 0},
            "retry": {"per_url_attempts": 1, "backoff_seconds": [0]},
            "circuit_breaker": {"abort_if_failed_fraction_exceeds": 0.5},
            "drift": {"required_field_extraction_threshold": 0.7},
            "required_fields": [],
            "persistence": {"report_path": "artifacts/scrape_report.json"},
        },
    )
    monkeypatch.setattr(cli, "BASE_DIR", tmp_path)

    cli.main(["run", "--sources", "src_001,src_003", "--run-id", "r6"])
    assert captured["ids"] == ["src_001", "src_003"]
