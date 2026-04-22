"""Tests for phase_5_ingestion_cli.purge — hard-purge of soft-deleted rows."""
from __future__ import annotations

import pytest

from phase_5_ingestion_cli.purge import hard_purge_deleted_chunks, PurgeReport
from .conftest import FakeDB, make_prod_pipeline


# ---------------------------------------------------------------------------
# Helper: fake vector index with a controllable hard_purge_older_than
# ---------------------------------------------------------------------------

class _StubVectorIndex:
    def __init__(self, rows_to_purge: int = 0):
        self._rows = rows_to_purge
        self.last_cutoff: int | None = None

    def hard_purge_older_than(self, cutoff_days: int) -> int:
        self.last_cutoff = cutoff_days
        return self._rows


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_purge_returns_report():
    stub = _StubVectorIndex(rows_to_purge=5)
    report = hard_purge_deleted_chunks(stub, cutoff_days=7)
    assert isinstance(report, PurgeReport)
    assert report.cutoff_days == 7
    assert report.rows_purged == 5


def test_purge_passes_cutoff_days_through():
    stub = _StubVectorIndex(rows_to_purge=3)
    hard_purge_deleted_chunks(stub, cutoff_days=14)
    assert stub.last_cutoff == 14


def test_purge_zero_rows():
    stub = _StubVectorIndex(rows_to_purge=0)
    report = hard_purge_deleted_chunks(stub, cutoff_days=7)
    assert report.rows_purged == 0


def test_purge_rejects_zero_cutoff():
    stub = _StubVectorIndex()
    with pytest.raises(ValueError, match="cutoff_days must be >= 1"):
        hard_purge_deleted_chunks(stub, cutoff_days=0)


def test_purge_to_dict():
    stub = _StubVectorIndex(rows_to_purge=2)
    report = hard_purge_deleted_chunks(stub, cutoff_days=3)
    d = report.to_dict()
    assert d == {"cutoff_days": 3, "rows_purged": 2}


def test_purge_against_fake_pg(connect, fake_db: FakeDB):
    """End-to-end: soft-delete a chunk then hard-purge it via PgVectorIndex."""
    from phase_4_2_prod_wiring.adapters import PgVectorIndex

    vi = PgVectorIndex(connect)

    # Upsert a row, then soft-delete it.
    vi.upsert([{
        "corpus_version": "cv_old",
        "chunk_id": "src_001#fact#expense_ratio",
        "source_id": "src_001",
        "scheme": "Test",
        "section": None,
        "segment_type": "fact_table",
        "text": "Test scheme has an expense ratio of 0.5%.",
        "embedding": "[" + ",".join(["0.1"] * 384) + "]",
        "embed_model_id": "fake/test@v1",
        "chunk_hash": "abc123",
        "source_url": "https://example.com",
        "last_updated": "2026-04-19",
        "dim": 384,
    }])
    vi.soft_delete(["src_001#fact#expense_ratio"])

    assert len(fake_db.chunks) == 1
    report = hard_purge_deleted_chunks(vi, cutoff_days=7)
    # Fake DB hard purge removes any row with deleted_at set.
    assert report.rows_purged == 1
    assert len(fake_db.chunks) == 0
