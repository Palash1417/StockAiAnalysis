"""Local scheduler runner — mirrors the GitHub Actions ingest workflow.

Runs the full pipeline locally:
  Phase 4.3  →  Scrape → Chunk → Embed → Push to Chroma Cloud

Usage (from project root):
    python run_local.py [--force] [--log-level DEBUG|INFO|WARNING]

Flags:
    --force       Re-scrape even if content is unchanged.
    --log-level   Override log verbosity (default: INFO).

Exit codes:
    0  All phases completed successfully.
    1  One or more sources failed; check logs/ for details.

Log files are written to  logs/scheduler_<timestamp>.log
Ingest report is written to  phase_4_3_push_to_chroma/ingest_report.json
"""
from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT = Path(__file__).parent
LOGS_DIR = ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

_RUN_TS = int(time.time())
LOG_FILE = LOGS_DIR / f"scheduler_{_RUN_TS}.log"

# ---------------------------------------------------------------------------
# Logging — file + console
# ---------------------------------------------------------------------------
_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)

_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_fh, _ch])
log = logging.getLogger("run_local")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(title: str) -> None:
    bar = "=" * 60
    log.info(bar)
    log.info("  %s", title)
    log.info(bar)


def _check_prereqs() -> list[str]:
    """Return list of missing prerequisites."""
    missing: list[str] = []
    if not shutil.which("python") and not shutil.which("python3"):
        missing.append("python not found on PATH")
    dotenv_path = ROOT / ".env"
    if not dotenv_path.exists():
        missing.append(".env file not found — copy .env.example and fill CHROMA_API_KEY")
    else:
        content = dotenv_path.read_text(encoding="utf-8")
        if "CHROMA_API_KEY" not in content or "CHROMA_API_KEY=" not in content:
            missing.append(".env exists but CHROMA_API_KEY is not set")
        for line in content.splitlines():
            if line.startswith("CHROMA_API_KEY="):
                val = line.split("=", 1)[1].strip()
                if not val or val in ("your_key_here", ""):
                    missing.append("CHROMA_API_KEY value is empty in .env")
    return missing


def _phase_header(phase: str, description: str) -> None:
    log.info("")
    log.info("──────────────────────────────────────────────────────────")
    log.info("  PHASE %s — %s", phase, description)
    log.info("──────────────────────────────────────────────────────────")


def _phase_result(phase: str, ok: bool, duration_s: float, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    msg = f"  [{status}] Phase {phase} — {duration_s:.1f}s"
    if detail:
        msg += f" — {detail}"
    if ok:
        log.info(msg)
    else:
        log.error(msg)


# ---------------------------------------------------------------------------
# Phase runners
# ---------------------------------------------------------------------------

def run_phase_43(force: bool) -> tuple[bool, float, str]:
    """Scrape → Chunk → Embed → Push to Chroma (phase_4_3_push_to_chroma/run.py)."""
    t0 = time.time()
    cmd = [sys.executable, str(ROOT / "phase_4_3_push_to_chroma" / "run.py")]
    if force:
        cmd.append("--force")

    log.info("running: %s", " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(ROOT))
    duration = time.time() - t0

    ok = result.returncode == 0
    detail = "exit=0 all sources ok" if ok else f"exit={result.returncode} check logs above"
    return ok, duration, detail


def check_ingest_report() -> tuple[bool, str]:
    """Validate the ingest report produced by phase 4.3."""
    import json

    report_path = ROOT / "phase_4_3_push_to_chroma" / "ingest_report.json"
    if not report_path.exists():
        return False, "ingest_report.json not found"

    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"could not parse ingest_report.json: {exc}"

    status = report.get("status", "unknown")
    sources_ok = report.get("sources_ok", 0)
    sources_total = report.get("sources_total", 0)
    chunks_pushed = report.get("chunks_pushed", 0)
    chroma_total = report.get("chroma_total", 0)
    run_id = report.get("run_id", "?")

    log.info("  report.run_id        = %s", run_id)
    log.info("  report.status        = %s", status)
    log.info("  report.sources_ok    = %d / %d", sources_ok, sources_total)
    log.info("  report.chunks_pushed = %d", chunks_pushed)
    log.info("  report.chroma_total  = %d", chroma_total)

    for src in report.get("sources", []):
        src_status = src.get("status", "?")
        lvl = logging.INFO if src_status == "ok" else logging.ERROR
        log.log(
            lvl,
            "    source %-10s status=%-8s facts=%s chunks=%s duration=%.1fs",
            src.get("source_id", "?"),
            src_status,
            src.get("facts_extracted", "N/A"),
            src.get("chunks", "N/A"),
            src.get("duration_s", 0.0),
        )
        if src_status == "error":
            log.error("    error: %s", src.get("error", ""))

    ok = status in ("ok", "partial") and chunks_pushed > 0
    summary = (
        f"status={status} sources={sources_ok}/{sources_total} "
        f"chunks={chunks_pushed} chroma_total={chroma_total}"
    )
    return ok, summary


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local ingestion scheduler")
    ap.add_argument("--force", action="store_true", help="Re-scrape all sources unconditionally")
    ap.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log verbosity (default: INFO)",
    )
    args = ap.parse_args(argv)

    logging.getLogger().setLevel(getattr(logging, args.log_level))

    started_at = datetime.now(timezone.utc)
    _banner(f"LOCAL INGEST RUN  {started_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    log.info("log file  : %s", LOG_FILE)
    log.info("project   : %s", ROOT)
    log.info("force     : %s", args.force)

    # ------------------------------------------------------------------
    # Pre-flight checks
    # ------------------------------------------------------------------
    _phase_header("0", "Pre-flight checks")
    t0 = time.time()
    issues = _check_prereqs()
    if issues:
        for issue in issues:
            log.error("  MISSING: %s", issue)
        _phase_result("0", False, time.time() - t0, "pre-flight failed")
        log.error("Aborting — fix the issues above and retry.")
        return 1
    _phase_result("0", True, time.time() - t0, "all prereqs satisfied")

    # ------------------------------------------------------------------
    # Phase 4.3 — Scrape → Chunk → Embed → Push
    # ------------------------------------------------------------------
    _phase_header("4.3", "Scrape → Chunk → Embed → Push to Chroma Cloud")
    ok43, dur43, detail43 = run_phase_43(force=args.force)
    _phase_result("4.3", ok43, dur43, detail43)

    # ------------------------------------------------------------------
    # Report validation
    # ------------------------------------------------------------------
    _phase_header("R", "Ingest report validation")
    t0 = time.time()
    report_ok, report_summary = check_ingest_report()
    _phase_result("R", report_ok, time.time() - t0, report_summary)

    # ------------------------------------------------------------------
    # Final summary
    # ------------------------------------------------------------------
    total_s = (datetime.now(timezone.utc) - started_at).total_seconds()
    overall_ok = ok43 and report_ok
    _banner(f"FINISHED in {total_s:.1f}s — {'ALL PHASES PASSED' if overall_ok else 'SOME PHASES FAILED'}")
    log.info("log file  : %s", LOG_FILE)
    log.info("report    : %s", ROOT / 'phase_4_3_push_to_chroma' / 'ingest_report.json')

    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
