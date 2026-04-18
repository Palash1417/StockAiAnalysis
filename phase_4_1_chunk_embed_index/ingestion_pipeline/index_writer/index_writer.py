"""Index writer — §5.8.

Three stores, atomic per chunk:
  Vector DB     → cosine dense retrieval         keyed by chunk_id
  BM25 index    → sparse retrieval               keyed by chunk_id
  Fact KV store → (scheme_id, field_name) lookup

Production uses pgvector + OpenSearch/rank_bm25 + a KV table. The in-memory
implementations here satisfy the protocols and back the unit tests.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Protocol

from ..models import EmbeddedChunk, UpsertReport

log = logging.getLogger(__name__)


class DuplicateChunkIdError(Exception):
    """Raised when two sources attempt to upsert the same chunk_id in one run."""


# ---------------------------------------------------------------------------
# Store protocols
# ---------------------------------------------------------------------------
class VectorIndex(Protocol):
    def upsert(self, rows: list[dict[str, Any]]) -> None: ...
    def soft_delete(self, chunk_ids: list[str]) -> int: ...
    def chunk_ids_for_source(self, source_id: str, corpus_version: str) -> list[str]: ...
    def count(self, corpus_version: str) -> int: ...


class BM25Index(Protocol):
    def upsert(self, chunk_id: str, text: str, metadata: dict) -> None: ...
    def delete(self, chunk_id: str) -> None: ...


class FactKVStore(Protocol):
    def put(
        self,
        scheme_id: str,
        field_name: str,
        value: str,
        source_url: str,
        last_updated: str,
    ) -> None: ...
    def get(self, scheme_id: str, field_name: str) -> dict | None: ...


# ---------------------------------------------------------------------------
# In-memory reference implementations
# ---------------------------------------------------------------------------
class InMemoryVectorIndex:
    def __init__(self) -> None:
        # (corpus_version, chunk_id) → row
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._deleted: dict[tuple[str, str], str] = {}  # deleted_at ISO

    def upsert(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            key = (row["corpus_version"], row["chunk_id"])
            self._rows[key] = row
            self._deleted.pop(key, None)

    def soft_delete(self, chunk_ids: list[str]) -> int:
        now = datetime.now(timezone.utc).isoformat()
        n = 0
        for key in list(self._rows.keys()):
            cv, cid = key
            if cid in chunk_ids and key not in self._deleted:
                self._deleted[key] = now
                n += 1
        return n

    def chunk_ids_for_source(self, source_id: str, corpus_version: str) -> list[str]:
        return [
            cid for (cv, cid), row in self._rows.items()
            if cv == corpus_version and row["source_id"] == source_id
            and (cv, cid) not in self._deleted
        ]

    def count(self, corpus_version: str) -> int:
        return sum(
            1 for (cv, cid) in self._rows
            if cv == corpus_version and (cv, cid) not in self._deleted
        )

    def rows(self, corpus_version: str) -> list[dict[str, Any]]:
        return [
            row for (cv, cid), row in self._rows.items()
            if cv == corpus_version and (cv, cid) not in self._deleted
        ]


class InMemoryBM25:
    """Lightweight BM25 placeholder — tokenizes + stores inverted counts.

    Real impl uses rank_bm25 or OpenSearch. For 4.1 we just need a store
    that the writer can push into and tests can read back.
    """

    _TOKEN_RE = re.compile(r"[a-z0-9]+")

    def __init__(self) -> None:
        self._docs: dict[str, tuple[list[str], dict]] = {}

    def upsert(self, chunk_id: str, text: str, metadata: dict) -> None:
        tokens = self._TOKEN_RE.findall(text.lower())
        self._docs[chunk_id] = (tokens, metadata)

    def delete(self, chunk_id: str) -> None:
        self._docs.pop(chunk_id, None)

    def __contains__(self, chunk_id: str) -> bool:
        return chunk_id in self._docs

    def __len__(self) -> int:
        return len(self._docs)


class InMemoryFactKV:
    def __init__(self) -> None:
        self._store: dict[tuple[str, str], dict] = {}

    def put(
        self,
        scheme_id: str,
        field_name: str,
        value: str,
        source_url: str,
        last_updated: str,
    ) -> None:
        self._store[(scheme_id, field_name)] = {
            "value": value,
            "source_url": source_url,
            "last_updated": last_updated,
        }

    def get(self, scheme_id: str, field_name: str) -> dict | None:
        return self._store.get((scheme_id, field_name))

    def __len__(self) -> int:
        return len(self._store)


# ---------------------------------------------------------------------------
# IndexWriter
# ---------------------------------------------------------------------------
class IndexWriter:
    def __init__(
        self,
        vector: VectorIndex,
        bm25: BM25Index,
        fact_kv: FactKVStore,
    ):
        self.vector = vector
        self.bm25 = bm25
        self.fact_kv = fact_kv

    def upsert(
        self,
        embedded: list[EmbeddedChunk],
        *,
        corpus_version: str,
        source_id: str,
        source_url: str,
        last_updated: str,
    ) -> UpsertReport:
        # Collision guard: duplicate chunk_id within this call
        seen: set[str] = set()
        for ec in embedded:
            if ec.chunk.chunk_id in seen:
                raise DuplicateChunkIdError(
                    f"duplicate chunk_id in run: {ec.chunk.chunk_id}"
                )
            seen.add(ec.chunk.chunk_id)

        vector_rows: list[dict[str, Any]] = []
        bm25_writes = 0
        fact_kv_writes = 0

        for ec in embedded:
            c = ec.chunk
            vector_rows.append(
                {
                    "chunk_id": c.chunk_id,
                    "source_id": c.source_id,
                    "scheme": c.scheme,
                    "section": c.section,
                    "segment_type": c.segment_type,
                    "text": c.normalized_text or c.text,
                    "embedding": ec.embedding,
                    "embed_model_id": ec.embed_model_id,
                    "chunk_hash": c.chunk_hash,
                    "source_url": source_url,
                    "last_updated": last_updated,
                    "corpus_version": corpus_version,
                    "dim": ec.dim,
                }
            )

            self.bm25.upsert(
                c.chunk_id,
                c.normalized_text or c.text,
                {"scheme": c.scheme, "segment_type": c.segment_type,
                 "source_id": c.source_id},
            )
            bm25_writes += 1

            if c.segment_type == "fact_table":
                field_name = c.metadata.get("field_name")
                raw_value = c.metadata.get("raw_value")
                if field_name and raw_value is not None:
                    self.fact_kv.put(
                        scheme_id=c.source_id,
                        field_name=field_name,
                        value=str(raw_value),
                        source_url=source_url,
                        last_updated=last_updated,
                    )
                    fact_kv_writes += 1

        self.vector.upsert(vector_rows)

        # Soft-delete orphans: chunks from prior runs of this source that
        # didn't appear in the current batch.
        current_ids = {ec.chunk.chunk_id for ec in embedded}
        existing_ids = set(
            self.vector.chunk_ids_for_source(source_id, corpus_version)
        )
        orphans = list(existing_ids - current_ids)
        soft_deleted = self.vector.soft_delete(orphans)
        for cid in orphans:
            self.bm25.delete(cid)

        return UpsertReport(
            corpus_version=corpus_version,
            chunks_upserted=len(embedded),
            chunks_soft_deleted=soft_deleted,
            fact_kv_writes=fact_kv_writes,
            bm25_writes=bm25_writes,
        )
