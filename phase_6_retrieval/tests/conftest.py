"""Phase 6 test harness.

Provides shared fixtures:
  - sample_rows: 5 pre-built chunk dicts with FakeDeterministicEmbedder vectors
  - dense_retriever / sparse_retriever: InMemory adapters pre-loaded with sample_rows
  - corpus_version / live_pointer
  - embedder: FakeDeterministicEmbedder (64-dim, no network)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make repo root + phase_4_1 importable
# parents[0] = tests/, parents[1] = phase_6_retrieval/, parents[2] = repo root
_ROOT = Path(__file__).resolve().parents[2]
_P41 = _ROOT / "phase_4_1_chunk_embed_index"
for _p in (str(_ROOT), str(_P41)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ingestion_pipeline.embedder.embedder import FakeDeterministicEmbedder  # noqa: E402

from phase_6_retrieval.adapters.in_memory_retriever import (  # noqa: E402
    InMemoryBM25Retriever,
    InMemoryDenseRetriever,
)

CORPUS_VERSION = "corpus_v_test"

FAKE_EMBEDDER = FakeDeterministicEmbedder(dim=64)

# ---------------------------------------------------------------------------
# Seed data — 5 chunks covering 3 scheme facts + 2 narrative sections
# ---------------------------------------------------------------------------
_SEED_TEXTS = [
    "Bandhan Small Cap Fund Direct - Growth has an expense ratio of 0.41%.",
    "Bandhan Small Cap Fund Direct - Growth has an exit load of 1% if redeemed within 1 year.",
    "HDFC Mid Cap Opportunities Fund Direct - Growth has an expense ratio of 0.79%.",
    "Investment objective: The scheme seeks to generate long-term capital appreciation.",
    "Benchmark: Nifty Midcap 150 TRI is the benchmark for HDFC Mid Cap Fund.",
]
_SEED_META = [
    {"source_id": "src_002", "scheme": "Bandhan Small Cap Fund Direct - Growth",
     "section": None, "segment_type": "fact_table",
     "source_url": "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
     "last_updated": "2026-04-19"},
    {"source_id": "src_002", "scheme": "Bandhan Small Cap Fund Direct - Growth",
     "section": None, "segment_type": "fact_table",
     "source_url": "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
     "last_updated": "2026-04-19"},
    {"source_id": "src_003", "scheme": "HDFC Mid Cap Opportunities Fund Direct - Growth",
     "section": "Expense Ratio", "segment_type": "fact_table",
     "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
     "last_updated": "2026-04-19"},
    {"source_id": "src_003", "scheme": "HDFC Mid Cap Opportunities Fund Direct - Growth",
     "section": "About", "segment_type": "section_text",
     "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
     "last_updated": "2026-04-19"},
    {"source_id": "src_003", "scheme": "HDFC Mid Cap Opportunities Fund Direct - Growth",
     "section": "Benchmark", "segment_type": "section_text",
     "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
     "last_updated": "2026-04-19"},
]


def _build_rows() -> list[dict]:
    rows = []
    for i, (text, meta) in enumerate(zip(_SEED_TEXTS, _SEED_META)):
        chunk_id = f"{meta['source_id']}#chunk{i}"
        embedding = FAKE_EMBEDDER.embed_batch([text])[0]
        rows.append({"chunk_id": chunk_id, "text": text, "embedding": embedding, **meta})
    return rows


_ROWS = _build_rows()


@pytest.fixture
def sample_rows() -> list[dict]:
    return list(_ROWS)


@pytest.fixture
def corpus_version() -> str:
    return CORPUS_VERSION


@pytest.fixture
def embedder() -> FakeDeterministicEmbedder:
    return FAKE_EMBEDDER


@pytest.fixture
def dense_retriever(sample_rows, corpus_version) -> InMemoryDenseRetriever:
    dr = InMemoryDenseRetriever()
    dr.add(corpus_version, sample_rows)
    return dr


@pytest.fixture
def sparse_retriever(sample_rows, corpus_version) -> InMemoryBM25Retriever:
    sr = InMemoryBM25Retriever()
    sr.add(corpus_version, sample_rows)
    return sr


class _FakePointer:
    def __init__(self, version: str):
        self._v = version

    def get_live(self) -> str:
        return self._v

    def set_live(self, v: str) -> None:
        self._v = v

    def history(self) -> list[str]:
        return [self._v]


@pytest.fixture
def live_pointer(corpus_version) -> _FakePointer:
    return _FakePointer(corpus_version)
