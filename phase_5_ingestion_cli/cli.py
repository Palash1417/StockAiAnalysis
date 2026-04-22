"""Phase 5 ingestion CLI — composes phase 4.1 pipeline with phase 4.2 backends.

Usage (run from the project root):

    # Process all changed sources from a ScrapeReport
    python -m phase_5_ingestion_cli.cli run \\
        --report artifacts/scrape_report.json \\
        --corpus-base-dir phase_4_scheduler_scraping \\
        --config phase_5_ingestion_cli/config/phase5.yaml

    # Force re-ingest a single source by pointing directly at its JSON
    python -m phase_5_ingestion_cli.cli run \\
        --source-id src_002 \\
        --json corpus/ingest_abc/src_002.json \\
        --source-url https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth \\
        --scheme "Bandhan Small Cap Fund Direct - Growth" \\
        --last-updated 2026-04-19 \\
        --run-id ingest_abc \\
        --config phase_5_ingestion_cli/config/phase5.yaml

    # Hard-purge soft-deleted rows older than N days
    python -m phase_5_ingestion_cli.cli purge \\
        --config phase_5_ingestion_cli/config/phase5.yaml \\
        --cutoff-days 7

Exit codes:
    0   All sources ingested and pointer swapped successfully.
    1   One or more sources failed or smoke test blocked the swap.
    2   Bad arguments / config error.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import date
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path (composition.py does the same; safe to
# call twice — Path.__eq__ deduplicates).
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from phase_4_1_chunk_embed_index.ingestion_pipeline.models import ParsedDocument  # noqa: E402
from phase_4_2_prod_wiring.composition import build_prod_pipeline  # noqa: E402

from .composition import build_ingestion_pipeline  # noqa: E402
from .purge import hard_purge_deleted_chunks  # noqa: E402

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ingestion report
# ---------------------------------------------------------------------------

@dataclass
class SourceIngestionResult:
    source_id: str
    status: str          # "ok" | "smoke_failed" | "error"
    corpus_version: str | None = None
    swapped: bool = False
    upsert_report: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class IngestionRunReport:
    run_id: str
    config_path: str
    sources: list[SourceIngestionResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        s: dict[str, int] = {"ok": 0, "smoke_failed": 0, "error": 0, "skipped": 0}
        for r in self.sources:
            s[r.status] = s.get(r.status, 0) + 1
        return s

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "config_path": self.config_path,
            "sources": [r.to_dict() for r in self.sources],
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# Source loading helpers
# ---------------------------------------------------------------------------

def _load_doc_from_json(
    json_path: Path,
    source_id: str,
    source_url: str,
    scheme: str,
    last_updated: str,
) -> ParsedDocument:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return ParsedDocument(
        source_id=source_id,
        scheme=scheme,
        source_url=source_url,
        last_updated=last_updated,
        facts=data.get("facts", {}),
        sections=data.get("sections", []),
        tables=data.get("tables", []),
    )


def _sources_from_report(report_path: Path, corpus_base_dir: Path) -> list[dict]:
    """Return list of dicts with keys: source_id, json_path, source_url, scheme,
    last_updated, run_id — one per *changed* source in the scrape report."""
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    run_id: str = raw["run_id"]
    results = raw.get("results", [])

    sources: list[dict] = []
    for r in results:
        if r.get("status") != "changed":
            log.info("skip %s (status=%s)", r["source_id"], r.get("status"))
            continue

        source_id: str = r["source_id"]
        json_path = corpus_base_dir / "corpus" / run_id / f"{source_id}.json"
        if not json_path.exists():
            log.warning("structured JSON not found for %s: %s", source_id, json_path)
            continue

        meta = json.loads(json_path.read_text(encoding="utf-8"))
        sources.append(
            {
                "source_id": source_id,
                "json_path": json_path,
                "source_url": meta.get("source_url", ""),
                "scheme": meta.get("scheme", source_id),
                "last_updated": meta.get(
                    "last_updated", date.today().isoformat()
                ),
                "run_id": run_id,
            }
        )
    return sources


# ---------------------------------------------------------------------------
# Subcommand: run
# ---------------------------------------------------------------------------

def _cmd_run(args: argparse.Namespace) -> int:
    prod = build_prod_pipeline(args.config)
    pipeline = build_ingestion_pipeline(prod)

    report = IngestionRunReport(
        run_id=getattr(args, "run_id", "cli"),
        config_path=args.config,
    )

    # Collect sources to process
    if args.report:
        corpus_base = Path(args.corpus_base_dir) if args.corpus_base_dir else Path(".")
        sources = _sources_from_report(Path(args.report), corpus_base)
        if not sources:
            log.info("no changed sources in report — nothing to do")
            print(json.dumps(report.to_dict(), indent=2))
            return 0
    else:
        # Single-source mode
        sources = [
            {
                "source_id": args.source_id,
                "json_path": Path(args.json),
                "source_url": args.source_url,
                "scheme": args.scheme,
                "last_updated": args.last_updated,
                "run_id": args.run_id,
            }
        ]
        report.run_id = args.run_id

    any_failure = False
    for src in sources:
        sid = src["source_id"]
        log.info("ingesting %s …", sid)
        try:
            doc = _load_doc_from_json(
                json_path=Path(src["json_path"]),
                source_id=sid,
                source_url=src["source_url"],
                scheme=src["scheme"],
                last_updated=src["last_updated"],
            )
            result = pipeline.handle(run_id=src["run_id"], doc=doc)
            status = "ok" if result.swapped else "smoke_failed"
            if not result.swapped:
                any_failure = True
                log.error("smoke test blocked swap for %s: %s", sid, result.error)
            report.sources.append(
                SourceIngestionResult(
                    source_id=sid,
                    status=status,
                    corpus_version=result.corpus_version,
                    swapped=result.swapped,
                    upsert_report=result.upsert_report.to_dict(),
                    error=result.error,
                )
            )
        except Exception as exc:
            log.exception("failed to ingest %s", sid)
            any_failure = True
            report.sources.append(
                SourceIngestionResult(
                    source_id=sid,
                    status="error",
                    error=str(exc),
                )
            )

    print(json.dumps(report.to_dict(), indent=2))
    return 1 if any_failure else 0


# ---------------------------------------------------------------------------
# Subcommand: purge
# ---------------------------------------------------------------------------

def _cmd_purge(args: argparse.Namespace) -> int:
    prod = build_prod_pipeline(args.config)
    purge_report = hard_purge_deleted_chunks(
        prod.vector_index,
        cutoff_days=args.cutoff_days,
    )
    print(json.dumps(purge_report.to_dict(), indent=2))
    return 0


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="phase_5_ingestion_cli.cli",
        description="Phase 5 ingestion CLI — prod-backed ingest + purge.",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    # ---- run ---------------------------------------------------------------
    run_p = sub.add_parser("run", help="Ingest changed sources into prod stores.")
    run_p.add_argument(
        "--config", required=True,
        help="Path to phase5.yaml (prod config).",
    )
    # Option A: from a scrape report
    run_p.add_argument(
        "--report",
        help="Path to artifacts/scrape_report.json produced by the scraper.",
    )
    run_p.add_argument(
        "--corpus-base-dir", default="phase_4_scheduler_scraping",
        help="Directory that contains corpus/<run_id>/<source_id>.json files.",
    )
    # Option B: single source
    run_p.add_argument("--source-id")
    run_p.add_argument("--json",    help="Path to structured JSON for this source.")
    run_p.add_argument("--source-url")
    run_p.add_argument("--scheme")
    run_p.add_argument("--last-updated")
    run_p.add_argument("--run-id", default="local_dev")

    # ---- purge -------------------------------------------------------------
    purge_p = sub.add_parser(
        "purge",
        help="Hard-purge soft-deleted rows older than --cutoff-days.",
    )
    purge_p.add_argument(
        "--config", required=True,
        help="Path to phase5.yaml (prod config).",
    )
    purge_p.add_argument(
        "--cutoff-days", type=int, default=7,
        help="Remove rows soft-deleted more than this many days ago (default: 7).",
    )

    return ap


def _validate_run_args(args: argparse.Namespace) -> str | None:
    """Return an error message if the 'run' args are inconsistent."""
    if args.command != "run":
        return None
    if args.report:
        return None  # report mode — other args unused
    missing = [
        f for f in ("source_id", "json", "source_url", "scheme", "last_updated")
        if not getattr(args, f.replace("-", "_"), None)
    ]
    if missing:
        return (
            "single-source mode requires: "
            + ", ".join(f"--{f.replace('_', '-')}" for f in missing)
        )
    return None


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_parser().parse_args(argv if argv is not None else sys.argv[1:])

    err = _validate_run_args(args)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 2

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "purge":
        return _cmd_purge(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
