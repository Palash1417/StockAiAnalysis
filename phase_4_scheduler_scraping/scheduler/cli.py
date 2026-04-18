"""CLI entry point invoked by the GitHub Actions ingest workflow.

Usage:
    python -m scheduler.cli run [--force true|false] [--run-id ingest_xxx]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from scraping_service.persistence import LocalStorage
from scraping_service.service import (
    CircuitBreakerOpen,
    ScrapingService,
    load_scraper_config,
    load_sources,
)

PHASE_ROOT = Path(__file__).resolve().parent.parent
SOURCES_YAML = PHASE_ROOT / "config" / "sources.yaml"
SCRAPER_YAML = PHASE_ROOT / "config" / "scraper.yaml"
BASE_DIR = Path(os.environ.get("SCRAPER_BASE_DIR", str(PHASE_ROOT)))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="scheduler.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a full ingestion pass.")
    run_p.add_argument(
        "--force",
        type=str,
        default="false",
        help="If true, re-process even when checksum unchanged.",
    )
    run_p.add_argument(
        "--run-id",
        type=str,
        default=os.environ.get("RUN_ID") or f"ingest_{os.getpid()}",
    )
    run_p.add_argument(
        "--sources",
        type=str,
        default=None,
        help="Comma-separated source ids (optional; defaults to all).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "run":
        force = args.force.strip().lower() == "true"
        sources = load_sources(SOURCES_YAML)
        cfg = load_scraper_config(SCRAPER_YAML)
        storage = LocalStorage(base_dir=str(BASE_DIR))
        service = ScrapingService(
            sources=sources, scraper_config=cfg, storage=storage
        )

        wanted = args.sources.split(",") if args.sources else None
        try:
            report = service.run(run_id=args.run_id, source_ids=wanted, force=force)
        except CircuitBreakerOpen as e:
            logging.error("circuit breaker tripped: %s", e)
            return 2

        summary = report.summary
        print(
            f"run_id={report.run_id} "
            f"changed={summary['changed']} "
            f"unchanged={summary['unchanged']} "
            f"degraded={summary['degraded']} "
            f"failed={summary['failed']}"
        )
        if summary["failed"] > 0:
            return 1
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
