"""Tests for phase_5_ingestion_cli.cli — run and purge subcommands."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from phase_5_ingestion_cli import cli
from .conftest import FakeDB, make_prod_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pipeline_and_patch(fake_db: FakeDB, connect):
    """Return a build_prod_pipeline patcher that injects a fake ProdPipeline."""
    prod = make_prod_pipeline(connect)

    def _fake_build_prod(config_path):
        return prod

    return prod, _fake_build_prod


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# run — single-source mode
# ---------------------------------------------------------------------------

def test_run_single_source_exits_0(tmp_path, fake_db: FakeDB, connect, capsys):
    src_json = tmp_path / "src_001.json"
    _write_json(src_json, {
        "source_id": "src_001",
        "scheme": "Nippon India Taiwan Equity Fund Direct - Growth",
        "source_url": "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth",
        "last_updated": "2026-04-19",
        "facts": {"expense_ratio": "0.59%", "exit_load": "1% if < 1y"},
        "sections": [],
        "tables": [],
    })

    prod, fake_build = _make_pipeline_and_patch(fake_db, connect)
    with patch("phase_5_ingestion_cli.cli.build_prod_pipeline", fake_build):
        rc = cli.main([
            "run",
            "--config", "phase_5_ingestion_cli/config/phase5.yaml",
            "--source-id", "src_001",
            "--json", str(src_json),
            "--source-url", "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth",
            "--scheme", "Nippon India Taiwan Equity Fund Direct - Growth",
            "--last-updated", "2026-04-19",
            "--run-id", "test_run",
        ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["ok"] == 1
    assert out["sources"][0]["swapped"] is True


def test_run_single_source_missing_args_exits_2(capsys):
    rc = cli.main([
        "run",
        "--config", "phase_5_ingestion_cli/config/phase5.yaml",
        "--source-id", "src_001",
        # missing --json, --source-url, --scheme, --last-updated
    ])
    assert rc == 2


def test_run_single_source_bad_json_exits_1(tmp_path, fake_db, connect, capsys):
    src_json = tmp_path / "bad.json"
    src_json.write_text("not json", encoding="utf-8")

    prod, fake_build = _make_pipeline_and_patch(fake_db, connect)
    with patch("phase_5_ingestion_cli.cli.build_prod_pipeline", fake_build):
        rc = cli.main([
            "run",
            "--config", "phase_5_ingestion_cli/config/phase5.yaml",
            "--source-id", "src_001",
            "--json", str(src_json),
            "--source-url", "https://example.com",
            "--scheme", "Test",
            "--last-updated", "2026-04-19",
            "--run-id", "bad_run",
        ])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["error"] == 1


# ---------------------------------------------------------------------------
# run — report mode
# ---------------------------------------------------------------------------

def test_run_report_mode_processes_changed_source(tmp_path, fake_db, connect, capsys):
    run_id = "ingest_20260419"
    corpus_dir = tmp_path / "corpus" / run_id
    corpus_dir.mkdir(parents=True)

    # Write structured JSON for src_002
    src_json = corpus_dir / "src_002.json"
    _write_json(src_json, {
        "source_id": "src_002",
        "scheme": "Bandhan Small Cap Fund Direct - Growth",
        "source_url": "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
        "last_updated": "2026-04-19",
        "facts": {"expense_ratio": "0.89%", "exit_load": "1% if < 1y"},
        "sections": [],
        "tables": [],
    })

    # Write scrape report referencing src_002 as changed
    report = {
        "run_id": run_id,
        "started_at": "2026-04-19T09:00:00Z",
        "results": [
            {"source_id": "src_001", "status": "unchanged"},
            {"source_id": "src_002", "status": "changed", "checksum": "sha256:abc"},
        ],
    }
    report_path = tmp_path / "scrape_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    prod, fake_build = _make_pipeline_and_patch(fake_db, connect)
    with patch("phase_5_ingestion_cli.cli.build_prod_pipeline", fake_build):
        rc = cli.main([
            "run",
            "--config", "phase_5_ingestion_cli/config/phase5.yaml",
            "--report", str(report_path),
            "--corpus-base-dir", str(tmp_path),
        ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["summary"]["ok"] == 1
    assert out["summary"].get("skipped", 0) == 0
    assert out["sources"][0]["source_id"] == "src_002"


def test_run_report_no_changed_sources_exits_0(tmp_path, fake_db, connect, capsys):
    run_id = "ingest_unchanged"
    report = {
        "run_id": run_id,
        "started_at": "2026-04-19T09:00:00Z",
        "results": [{"source_id": "src_001", "status": "unchanged"}],
    }
    report_path = tmp_path / "scrape_report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    prod, fake_build = _make_pipeline_and_patch(fake_db, connect)
    with patch("phase_5_ingestion_cli.cli.build_prod_pipeline", fake_build):
        rc = cli.main([
            "run",
            "--config", "phase_5_ingestion_cli/config/phase5.yaml",
            "--report", str(report_path),
            "--corpus-base-dir", str(tmp_path),
        ])
    assert rc == 0


# ---------------------------------------------------------------------------
# purge subcommand
# ---------------------------------------------------------------------------

def test_purge_exits_0(fake_db, connect, capsys):
    prod, fake_build = _make_pipeline_and_patch(fake_db, connect)
    with patch("phase_5_ingestion_cli.cli.build_prod_pipeline", fake_build):
        rc = cli.main([
            "purge",
            "--config", "phase_5_ingestion_cli/config/phase5.yaml",
            "--cutoff-days", "7",
        ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["cutoff_days"] == 7
    assert "rows_purged" in out


def test_purge_reports_deleted_rows(fake_db, connect, capsys):
    from phase_4_2_prod_wiring.adapters import PgVectorIndex

    prod, fake_build = _make_pipeline_and_patch(fake_db, connect)
    vi = PgVectorIndex(connect)

    # Insert and soft-delete a row directly to fake_db.
    vi.upsert([{
        "corpus_version": "cv_old",
        "chunk_id": "src_001#fact#exit_load",
        "source_id": "src_001",
        "scheme": "Test",
        "section": None,
        "segment_type": "fact_table",
        "text": "Test scheme exit load is 1%.",
        "embedding": "[" + ",".join(["0.0"] * 384) + "]",
        "embed_model_id": "fake/test@v1",
        "chunk_hash": "deadbeef",
        "source_url": "https://example.com",
        "last_updated": "2026-04-19",
        "dim": 384,
    }])
    vi.soft_delete(["src_001#fact#exit_load"])

    with patch("phase_5_ingestion_cli.cli.build_prod_pipeline", fake_build):
        rc = cli.main([
            "purge",
            "--config", "phase_5_ingestion_cli/config/phase5.yaml",
            "--cutoff-days", "7",
        ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["rows_purged"] == 1


# ---------------------------------------------------------------------------
# _validate_run_args
# ---------------------------------------------------------------------------

def test_validate_passes_with_report():
    import argparse
    ns = argparse.Namespace(
        command="run", report="foo.json", source_id=None,
        json=None, source_url=None, scheme=None, last_updated=None,
    )
    assert cli._validate_run_args(ns) is None


def test_validate_fails_missing_single_source_fields():
    import argparse
    ns = argparse.Namespace(
        command="run", report=None, source_id="src_001",
        json=None, source_url=None, scheme=None, last_updated=None,
    )
    err = cli._validate_run_args(ns)
    assert err is not None
    assert "json" in err
