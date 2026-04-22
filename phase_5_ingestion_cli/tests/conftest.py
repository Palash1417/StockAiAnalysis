"""Phase 5 test harness.

Re-exports the FakeDB / FakeConnection / FakeCursor fixtures from phase 4.2's
conftest so phase 5 tests get prod-backend fakes for free, without duplicating
any SQL handler logic.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make project root and phase_4_1 importable.
_ROOT = Path(__file__).resolve().parents[3]
_P41 = _ROOT / "phase_4_1_chunk_embed_index"
for _p in (_ROOT, str(_P41)):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# Re-import FakeDB and friends from phase 4.2's conftest.
# We use importlib so we don't need to have phase_4_2 installed as a package.
import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "phase_4_2_tests_conftest",
    _ROOT / "phase_4_2_prod_wiring" / "tests" / "conftest.py",
)
_mod = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]

FakeDB = _mod.FakeDB
FakeConnection = _mod.FakeConnection
FakeCursor = _mod.FakeCursor


@pytest.fixture
def fake_db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def connect(fake_db: FakeDB):
    return fake_db.connect


# ---- minimal ProdPipeline builder for tests ---------------------------------

from phase_4_2_prod_wiring.adapters import (  # noqa: E402
    PgBM25Index,
    PgCorpusPointer,
    PgEmbeddingCache,
    PgFactKV,
    PgVectorIndex,
    S3Storage,
)
from phase_4_2_prod_wiring.composition import ProdPipeline  # noqa: E402
from phase_4_2_prod_wiring.smoke import build_smoke_runner  # noqa: E402


_SMOKE_CFG = {
    "min_chunks": 1,
    "required_sources": ["src_001"],
    "required_facts": [["src_001", "expense_ratio"]],
}

_EMBEDDER_CFG = {
    "provider": "fake",
    "dim": 64,
    "batch_size": 64,
    "hard_cap_per_run": 1000,
    "retry_backoff_seconds": [0],
    "max_attempts": 1,
}

_SNAPSHOT_CFG = {"keep_versions": 7}


def make_prod_pipeline(connect_fn) -> ProdPipeline:
    """Build a ProdPipeline wired to the in-memory fake psycopg."""
    vi = PgVectorIndex(connect_fn)
    bm = PgBM25Index(connect_fn)
    fk = PgFactKV(connect_fn)
    ec = PgEmbeddingCache(connect_fn)
    cp = PgCorpusPointer(connect_fn)
    smoke = build_smoke_runner(_SMOKE_CFG, vi, fk)

    return ProdPipeline(
        vector_index=vi,
        bm25_index=bm,
        fact_kv=fk,
        embedding_cache=ec,
        corpus_pointer=cp,
        storage=None,   # S3 not exercised by composition/purge tests
        smoke_runner=smoke,
        connect=connect_fn,
        config={
            "embedder": _EMBEDDER_CFG,
            "snapshot": _SNAPSHOT_CFG,
        },
    )


@pytest.fixture
def prod_pipeline(connect) -> ProdPipeline:
    return make_prod_pipeline(connect)
