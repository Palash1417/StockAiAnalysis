"""Tests for phase_5_ingestion_cli.composition — wiring 4.1 onto 4.2 backends."""
from __future__ import annotations

import pytest

from phase_4_1_chunk_embed_index.ingestion_pipeline import IngestionPipeline
from phase_4_1_chunk_embed_index.ingestion_pipeline.models import ParsedDocument

from phase_5_ingestion_cli.composition import build_ingestion_pipeline
from .conftest import make_prod_pipeline, FakeDB


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DOC = ParsedDocument(
    source_id="src_001",
    scheme="Nippon India Taiwan Equity Fund Direct - Growth",
    source_url="https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth",
    last_updated="2026-04-19",
    facts={
        "expense_ratio": "0.59%",
        "exit_load": "1% if redeemed within 1 year",
    },
    sections=[
        {
            "heading": "About the Fund",
            "text": (
                "Nippon India Taiwan Equity Fund invests primarily in equities "
                "of companies listed in Taiwan. It benchmarks against the MSCI Taiwan index."
            ),
        }
    ],
    tables=[],
)


# ---------------------------------------------------------------------------
# build_ingestion_pipeline
# ---------------------------------------------------------------------------

def test_returns_ingestion_pipeline(prod_pipeline):
    pipeline = build_ingestion_pipeline(prod_pipeline)
    assert isinstance(pipeline, IngestionPipeline)


def test_pipeline_handle_writes_chunks(prod_pipeline, fake_db: FakeDB):
    pipeline = build_ingestion_pipeline(prod_pipeline)
    result = pipeline.handle(run_id="test_run_001", doc=SAMPLE_DOC)

    assert result.corpus_version == "corpus_v_test_run_001"
    # At minimum one fact chunk per fact key and one section chunk
    assert result.upsert_report.chunks_upserted >= 2
    # Fact KV should have expense_ratio entry for src_001
    assert fake_db.fact_kv.get(("src_001", "expense_ratio")) is not None


def test_pipeline_swaps_pointer_when_smoke_passes(prod_pipeline, fake_db: FakeDB):
    pipeline = build_ingestion_pipeline(prod_pipeline)
    result = pipeline.handle(run_id="test_run_002", doc=SAMPLE_DOC)

    assert result.swapped, f"expected pointer swap; error={result.error}"
    assert fake_db.pointer == "corpus_v_test_run_002"


def test_pointer_not_swapped_when_smoke_fails(connect, fake_db: FakeDB):
    """Smoke runner requires src_001 + expense_ratio; if the doc has no facts
    the fact_kv check fails → pass_rate < 1.0 → pointer not flipped."""
    # Build a prod pipeline that requires facts but receive a doc without them
    from phase_4_2_prod_wiring.composition import ProdPipeline
    from phase_4_2_prod_wiring.adapters import (
        PgVectorIndex, PgBM25Index, PgFactKV, PgEmbeddingCache, PgCorpusPointer,
    )
    from phase_4_2_prod_wiring.smoke import build_smoke_runner

    smoke_cfg = {
        "min_chunks": 50,          # more than empty doc will produce
        "required_sources": ["src_001"],
        "required_facts": [["src_001", "expense_ratio"]],
    }
    vi = PgVectorIndex(connect)
    fk = PgFactKV(connect)
    prod = ProdPipeline(
        vector_index=vi,
        bm25_index=PgBM25Index(connect),
        fact_kv=fk,
        embedding_cache=PgEmbeddingCache(connect),
        corpus_pointer=PgCorpusPointer(connect),
        storage=None,
        smoke_runner=build_smoke_runner(smoke_cfg, vi, fk),
        connect=connect,
        config={
            "embedder": {"provider": "fake", "dim": 64, "batch_size": 64,
                         "hard_cap_per_run": 1000, "retry_backoff_seconds": [0],
                         "max_attempts": 1},
            "snapshot": {"keep_versions": 7},
        },
    )

    from phase_5_ingestion_cli.composition import build_ingestion_pipeline
    pipeline = build_ingestion_pipeline(prod)
    empty_doc = ParsedDocument(
        source_id="src_001",
        scheme="Test Scheme",
        source_url="https://example.com",
        last_updated="2026-04-19",
        facts={},          # no facts → fact_kv check fails
        sections=[],
        tables=[],
    )
    result = pipeline.handle(run_id="run_smoke_fail", doc=empty_doc)
    assert not result.swapped
    assert result.error is not None
    assert fake_db.pointer is None    # pointer was never set


def test_embedder_uses_cache_on_second_run(prod_pipeline, fake_db: FakeDB):
    """Re-running the same doc should hit the embedding cache for existing chunks."""
    pipeline = build_ingestion_pipeline(prod_pipeline)
    pipeline.handle(run_id="run_a", doc=SAMPLE_DOC)
    first_api_embeds = pipeline.embedder.api_embeds

    pipeline.handle(run_id="run_b", doc=SAMPLE_DOC)
    second_api_embeds = pipeline.embedder.api_embeds - first_api_embeds

    # All chunks from the second run should be cache hits (zero new API calls).
    assert second_api_embeds == 0


def test_bm25_written_for_chunks(prod_pipeline, fake_db: FakeDB):
    pipeline = build_ingestion_pipeline(prod_pipeline)
    pipeline.handle(run_id="run_bm25", doc=SAMPLE_DOC)

    # At least one BM25 doc should exist.
    assert len(fake_db.bm25) >= 1
