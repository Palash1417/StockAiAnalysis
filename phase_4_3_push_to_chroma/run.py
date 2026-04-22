"""Phase 4.3 — Scrape → Chunk → Embed → Push to Chroma Cloud.

Standalone runner: no Postgres required.
All Postgres-backed stores (BM25, fact_kv, embedding_cache, corpus_pointer)
are replaced with in-memory stubs so the only external service needed is
Chroma Cloud.

Run from the project root:
    python phase_4_3_push_to_chroma/run.py [--force]

Flags:
    --force   Re-scrape all sources even if content is unchanged (future use).

Exit codes:
    0  All sources ingested successfully.
    1  One or more sources failed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: add project root to path, load .env
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

# ---------------------------------------------------------------------------
# Logging — console + rotating file under logs/
# ---------------------------------------------------------------------------
_LOGS_DIR = _ROOT / "logs"
_LOGS_DIR.mkdir(exist_ok=True)

_LOG_FILE = _LOGS_DIR / f"ingest_{int(time.time())}.log"

_fmt = logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")

_file_handler = logging.FileHandler(_LOG_FILE, encoding="utf-8")
_file_handler.setFormatter(_fmt)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_fmt)

logging.basicConfig(level=logging.INFO, handlers=[_file_handler, _stream_handler])
log = logging.getLogger("phase_4_3")
log.info("log file: %s", _LOG_FILE)

# ---------------------------------------------------------------------------
# Sources (mirrored from phase_4_scheduler_scraping/config/sources.yaml)
# ---------------------------------------------------------------------------
SOURCES = [
    {
        "id": "src_001",
        "url": "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth",
        "scheme": "Nippon India Taiwan Equity Fund Direct - Growth",
    },
    {
        "id": "src_002",
        "url": "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
        "scheme": "Bandhan Small Cap Fund Direct - Growth",
    },
    {
        "id": "src_003",
        "url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
        "scheme": "HDFC Mid Cap Fund Direct - Growth",
    },
]

RUN_ID = f"phase43_{int(time.time())}"
TODAY = date.today().isoformat()
UA = "MutualFundFAQBot/1.0 (+contact: ops@example.com)"


# ---------------------------------------------------------------------------
# Step 1 — Fetch (Playwright primary, httpx fallback)
# ---------------------------------------------------------------------------

def fetch_page(url: str) -> str:
    log.info("fetching %s", url)
    try:
        return _fetch_playwright(url)
    except Exception as e:
        log.warning("Playwright failed (%s) — trying httpx fallback", e)
        return _fetch_httpx(url)


def _fetch_playwright(url: str) -> str:
    from playwright.sync_api import sync_playwright  # type: ignore
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=UA)
        page.goto(url, wait_until="networkidle", timeout=45_000)
        # wait for a key element to confirm JS hydration
        try:
            page.wait_for_selector("text=Expense Ratio", timeout=15_000)
        except Exception:
            log.warning("Expense Ratio selector not found — page may be partially rendered")
        html = page.content()
        browser.close()
    return html


def _fetch_httpx(url: str) -> str:
    import httpx  # type: ignore
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# Step 2 — Parse
# ---------------------------------------------------------------------------

def parse_html(source_id: str, scheme: str, url: str, html: str):
    """Return a phase-4.1 ParsedDocument."""
    from phase_4_scheduler_scraping.scraping_service.parser.groww_parser import (
        GrowwSchemePageParser,
    )
    from phase_4_scheduler_scraping.scraping_service.models import Source as ScraperSource
    from phase_4_1_chunk_embed_index.ingestion_pipeline.models import ParsedDocument

    scraper_source = ScraperSource(
        id=source_id,
        url=url,
        type="scheme_page",
        scheme=scheme,
        category="",
        source_class="groww",
    )
    scraper_doc = GrowwSchemePageParser().parse(scraper_source, html)

    log.info(
        "parsed %s: %d facts, %d sections, %d tables",
        source_id,
        len(scraper_doc.facts),
        len(scraper_doc.sections),
        len(scraper_doc.tables),
    )

    return ParsedDocument(
        source_id=source_id,
        scheme=scheme,
        source_url=url,
        last_updated=TODAY,
        facts=scraper_doc.facts,
        sections=scraper_doc.sections,
        tables=scraper_doc.tables,
    )


# ---------------------------------------------------------------------------
# Step 3 — Chunk → Hash → Embed (in-memory cache)
# ---------------------------------------------------------------------------

def build_pipeline():
    from phase_4_1_chunk_embed_index.ingestion_pipeline.segmenter import DocumentSegmenter
    from phase_4_1_chunk_embed_index.ingestion_pipeline.chunker import Chunker
    from phase_4_1_chunk_embed_index.ingestion_pipeline.hasher import ChunkHasher
    from phase_4_1_chunk_embed_index.ingestion_pipeline.embedder import (
        CachedEmbedder,
        build_embedder,
    )
    from phase_4_1_chunk_embed_index.ingestion_pipeline.embedding_cache import (
        InMemoryEmbeddingCache,
    )

    embedder_cfg = {
        "provider": "bge_local",
        "model": "BAAI/bge-small-en-v1.5",
        "dim": 384,
    }
    embedder_impl = build_embedder(embedder_cfg)
    log.info("embedder: %s (dim=%d)", embedder_impl.model_id, embedder_impl.dim)

    return (
        DocumentSegmenter(),
        Chunker(),
        ChunkHasher(embed_model_id=embedder_impl.model_id),
        CachedEmbedder(
            embedder=embedder_impl,
            cache=InMemoryEmbeddingCache(),
            batch_size=64,
            hard_cap=2000,
        ),
        embedder_impl.model_id,
    )


def chunk_and_embed(doc, segmenter, chunker, hasher, embedder):
    segments = segmenter.segment(doc)
    chunks = chunker.chunk(segments)
    hasher.apply(chunks)   # mutates in-place: sets chunk_hash + normalized_text
    embedded = embedder.embed(chunks)
    log.info(
        "  %s → %d chunks embedded (cache_hits=%d api_embeds=%d)",
        doc.source_id,
        len(embedded),
        embedder.cache_hits,
        embedder.api_embeds,
    )
    return embedded


# ---------------------------------------------------------------------------
# Step 4 — Push to Chroma Cloud
# ---------------------------------------------------------------------------

def push_to_chroma(all_embedded: list, corpus_version: str):
    from phase_5_ingestion_cli.adapters.chroma_vector_index import ChromaVectorIndex

    api_key = os.environ.get("CHROMA_API_KEY", "")
    tenant = os.environ.get("CHROMA_TENANT", "default_tenant")
    database = os.environ.get("CHROMA_DATABASE", "default_database")

    if not api_key:
        raise ValueError("CHROMA_API_KEY is not set in .env")

    log.info("connecting to Chroma Cloud (tenant=%s database=%s)", tenant, database)
    chroma = ChromaVectorIndex(
        api_key=api_key,
        collection_name="mf_rag",
        tenant=tenant,
        database=database,
    )

    rows = []
    for ec in all_embedded:
        rows.append({
            "chunk_id":       ec.chunk.chunk_id,
            "corpus_version": corpus_version,
            "source_id":      ec.chunk.source_id,
            "scheme":         ec.chunk.scheme,
            "section":        ec.chunk.section or "",
            "segment_type":   ec.chunk.segment_type,
            "text":           ec.chunk.text,
            "embedding":      ec.embedding,
            "embed_model_id": ec.embed_model_id,
            "chunk_hash":     ec.chunk.chunk_hash,
            "source_url":     ec.chunk.metadata.get("source_url", ""),
            "last_updated":   ec.chunk.metadata.get("last_updated", TODAY),
            "dim":            ec.dim,
        })

    log.info("upserting %d rows to Chroma (corpus_version=%s)", len(rows), corpus_version)
    # Chroma upsert in batches of 100 to stay well within payload limits
    batch_size = 100
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        chroma.upsert(batch)
        log.info("  upserted batch %d/%d", i // batch_size + 1, -(-len(rows) // batch_size))

    total = chroma.count(corpus_version)
    log.info("Chroma collection 'mf_rag' now has %d active chunks for version %s", total, corpus_version)
    return len(rows), total


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

_REPORT_PATH = Path(__file__).parent / "ingest_report.json"


def _write_report(report: dict) -> None:
    _REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("ingest report written to %s", _REPORT_PATH)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Phase 4.3 ingest pipeline")
    ap.add_argument(
        "--force", action="store_true",
        help="Re-scrape all sources even if content appears unchanged",
    )
    args = ap.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    log.info("=== Phase 4.3 — push to Chroma Cloud (run_id=%s) ===", RUN_ID)
    corpus_version = f"corpus_v_{RUN_ID}"

    segmenter, chunker, hasher, embedder, model_id = build_pipeline()

    all_embedded = []
    source_results: list[dict] = []
    failures: list[str] = []

    for src in SOURCES:
        src_start = time.time()
        try:
            html = fetch_page(src["url"])
            doc = parse_html(src["id"], src["scheme"], src["url"], html)
            embedded = chunk_and_embed(doc, segmenter, chunker, hasher, embedder)
            for ec in embedded:
                ec.chunk.metadata["source_url"] = src["url"]
                ec.chunk.metadata["last_updated"] = TODAY
            all_embedded.extend(embedded)
            source_results.append({
                "source_id": src["id"],
                "status": "ok",
                "facts_extracted": len(doc.facts),
                "chunks": len(embedded),
                "duration_s": round(time.time() - src_start, 1),
            })
        except Exception as exc:
            log.exception("failed to process %s", src["id"])
            failures.append(src["id"])
            source_results.append({
                "source_id": src["id"],
                "status": "error",
                "error": str(exc),
                "duration_s": round(time.time() - src_start, 1),
            })

    if not all_embedded:
        log.error("no chunks produced — aborting push")
        _write_report({
            "run_id": RUN_ID,
            "corpus_version": corpus_version,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "status": "aborted",
            "sources": source_results,
        })
        return 1

    upserted, total_in_chroma = push_to_chroma(all_embedded, corpus_version)

    report = {
        "run_id": RUN_ID,
        "corpus_version": corpus_version,
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if not failures else "partial",
        "embed_model": model_id,
        "sources_ok": len(SOURCES) - len(failures),
        "sources_total": len(SOURCES),
        "chunks_pushed": upserted,
        "chroma_total": total_in_chroma,
        "sources": source_results,
    }
    _write_report(report)

    print("\n" + "=" * 60)
    print(f"  Run ID       : {RUN_ID}")
    print(f"  Corpus ver.  : {corpus_version}")
    print(f"  Sources OK   : {len(SOURCES) - len(failures)}/{len(SOURCES)}")
    if failures:
        print(f"  Failures     : {', '.join(failures)}")
    print(f"  Chunks pushed: {upserted}")
    print(f"  Chroma total : {total_in_chroma}")
    print("=" * 60)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
