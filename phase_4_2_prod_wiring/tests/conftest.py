"""Test harness for phase 4.2.

The adapters all take a `connect()` factory, so the tests substitute a
fake psycopg that implements just enough of the contract: a few SQL
patterns used by the adapters, plus `executemany`, `fetchone`, `fetchall`,
and the context-manager protocol. The fake is not a full SQL engine — it
pattern-matches the specific queries each adapter issues. That's the same
trade-off phase 4.1 made with its in-memory stores.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# Make `phase_4_1_chunk_embed_index/ingestion_pipeline` importable so tests
# that touch the phase 4.1 protocols can do so without packaging.
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "phase_4_1_chunk_embed_index"))
sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fake psycopg
# ---------------------------------------------------------------------------
class FakeDB:
    """Shared in-memory state across all cursors opened from the same factory."""

    def __init__(self):
        # chunks: {(corpus_version, chunk_id) -> row dict}
        self.chunks: dict[tuple[str, str], dict[str, Any]] = {}
        # bm25_docs: {chunk_id -> row dict}
        self.bm25: dict[str, dict[str, Any]] = {}
        # fact_kv: {(scheme_id, field_name) -> row dict}
        self.fact_kv: dict[tuple[str, str], dict[str, Any]] = {}
        # embedding_cache: {chunk_hash -> (embedding bytes, dim)}
        self.embedding_cache: dict[str, tuple[bytes, int]] = {}
        # corpus_pointer single row
        self.pointer: str | None = None
        self.history: list[str] = []

    def connect(self):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, db: FakeDB):
        self.db = db

    def cursor(self):
        return FakeCursor(self.db)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeCursor:
    def __init__(self, db: FakeDB):
        self.db = db
        self._result: list[tuple] = []
        self.rowcount: int = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    # ---- execute / executemany ------------------------------------------
    def execute(self, sql: str, params: Any = None):
        sql_norm = _normalize(sql)
        for pattern, handler in _HANDLERS:
            if pattern.search(sql_norm):
                handler(self, params or ())
                return
        raise AssertionError(f"no FakeCursor handler for SQL:\n{sql}")

    def executemany(self, sql: str, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


def _normalize(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


# ---------------------------------------------------------------------------
# SQL handlers — one entry per statement shape the adapters issue
# ---------------------------------------------------------------------------
_HANDLERS: list[tuple[re.Pattern, Any]] = []


def _register(pattern: str):
    def deco(fn):
        _HANDLERS.append((re.compile(pattern), fn))
        return fn
    return deco


# ---- chunks (PgVectorIndex) ---------------------------------------------
@_register(r"insert into chunks")
def _h_chunks_upsert(cur: FakeCursor, p: dict):
    key = (p["corpus_version"], p["chunk_id"])
    cur.db.chunks[key] = {
        "corpus_version": p["corpus_version"],
        "chunk_id": p["chunk_id"],
        "source_id": p["source_id"],
        "scheme": p.get("scheme"),
        "section": p.get("section"),
        "segment_type": p["segment_type"],
        "text": p["text"],
        "embedding": p["embedding"],
        "embed_model_id": p["embed_model_id"],
        "chunk_hash": p["chunk_hash"],
        "source_url": p["source_url"],
        "last_updated": p["last_updated"],
        "dim": p["dim"],
        "deleted_at": None,
    }
    cur.rowcount = 1


@_register(r"update chunks set deleted_at = %s where chunk_id = any\(%s\)")
def _h_chunks_soft_delete(cur: FakeCursor, params: tuple):
    now, ids = params
    n = 0
    for key, row in cur.db.chunks.items():
        if row["chunk_id"] in ids and row["deleted_at"] is None:
            row["deleted_at"] = now
            n += 1
    cur.rowcount = n


@_register(r"select chunk_id from chunks where source_id = %s and corpus_version = %s and deleted_at is null")
def _h_chunks_ids_for_source(cur: FakeCursor, params: tuple):
    source_id, cv = params
    cur._result = [
        (row["chunk_id"],)
        for row in cur.db.chunks.values()
        if row["source_id"] == source_id
        and row["corpus_version"] == cv
        and row["deleted_at"] is None
    ]


@_register(r"select count\(\*\) from chunks where corpus_version = %s and deleted_at is null")
def _h_chunks_count(cur: FakeCursor, params: tuple):
    (cv,) = params
    n = sum(
        1
        for row in cur.db.chunks.values()
        if row["corpus_version"] == cv and row["deleted_at"] is None
    )
    cur._result = [(n,)]


@_register(r"select distinct source_id from chunks where corpus_version = %s and deleted_at is null")
def _h_chunks_distinct_sources(cur: FakeCursor, params: tuple):
    (cv,) = params
    ids = {
        row["source_id"]
        for row in cur.db.chunks.values()
        if row["corpus_version"] == cv and row["deleted_at"] is None
    }
    cur._result = [(i,) for i in sorted(ids)]


@_register(r"delete from chunks where deleted_at is not null")
def _h_chunks_hard_purge(cur: FakeCursor, params: tuple):
    # In tests we treat any row with deleted_at set as eligible for purge.
    (_days,) = params
    to_drop = [k for k, row in cur.db.chunks.items() if row["deleted_at"] is not None]
    for k in to_drop:
        del cur.db.chunks[k]
    cur.rowcount = len(to_drop)


# ---- bm25_docs ----------------------------------------------------------
@_register(r"insert into bm25_docs")
def _h_bm25_upsert(cur: FakeCursor, params: tuple):
    chunk_id, text, metadata_json, _tsv_text = params
    cur.db.bm25[chunk_id] = {
        "chunk_id": chunk_id,
        "text": text,
        "metadata": json.loads(metadata_json),
    }
    cur.rowcount = 1


@_register(r"delete from bm25_docs where chunk_id = %s")
def _h_bm25_delete(cur: FakeCursor, params: tuple):
    (chunk_id,) = params
    if chunk_id in cur.db.bm25:
        del cur.db.bm25[chunk_id]
        cur.rowcount = 1
    else:
        cur.rowcount = 0


@_register(r"select count\(\*\) from bm25_docs")
def _h_bm25_count(cur: FakeCursor, params: tuple):
    cur._result = [(len(cur.db.bm25),)]


@_register(r"select 1 from bm25_docs where chunk_id = %s limit 1")
def _h_bm25_contains(cur: FakeCursor, params: tuple):
    (chunk_id,) = params
    cur._result = [(1,)] if chunk_id in cur.db.bm25 else []


# ---- fact_kv ------------------------------------------------------------
@_register(r"insert into fact_kv")
def _h_fact_upsert(cur: FakeCursor, params: tuple):
    scheme_id, field_name, value, source_url, last_updated = params
    cur.db.fact_kv[(scheme_id, field_name)] = {
        "value": value,
        "source_url": source_url,
        "last_updated": last_updated,
    }
    cur.rowcount = 1


@_register(r"select value, source_url, last_updated from fact_kv")
def _h_fact_get(cur: FakeCursor, params: tuple):
    scheme_id, field_name = params
    row = cur.db.fact_kv.get((scheme_id, field_name))
    cur._result = (
        [(row["value"], row["source_url"], row["last_updated"])] if row else []
    )


# ---- embedding_cache ----------------------------------------------------
@_register(r"select chunk_hash, embedding, dim from embedding_cache")
def _h_cache_get(cur: FakeCursor, params: tuple):
    (hashes,) = params
    cur._result = [
        (h, *cur.db.embedding_cache[h])
        for h in hashes
        if h in cur.db.embedding_cache
    ]


@_register(r"insert into embedding_cache")
def _h_cache_put(cur: FakeCursor, params: tuple):
    chunk_hash, blob, dim = params
    cur.db.embedding_cache[chunk_hash] = (blob, dim)
    cur.rowcount = 1


# ---- corpus_pointer / corpus_history ------------------------------------
@_register(r"select live from corpus_pointer where id = 1")
def _h_pointer_get(cur: FakeCursor, params: tuple):
    cur._result = [(cur.db.pointer,)]


@_register(r"insert into corpus_history")
def _h_history_insert(cur: FakeCursor, params: tuple):
    (cv,) = params
    if cv not in cur.db.history:
        cur.db.history.append(cv)
    cur.rowcount = 1


@_register(r"update corpus_pointer set live = %s")
def _h_pointer_set(cur: FakeCursor, params: tuple):
    (cv,) = params
    cur.db.pointer = cv
    cur.rowcount = 1


@_register(r"select corpus_version from corpus_history order by created_at asc")
def _h_history_list(cur: FakeCursor, params: tuple):
    cur._result = [(cv,) for cv in cur.db.history]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_db() -> FakeDB:
    return FakeDB()


@pytest.fixture
def connect(fake_db):
    return fake_db.connect
