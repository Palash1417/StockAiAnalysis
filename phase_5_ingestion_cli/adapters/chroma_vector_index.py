"""Chroma Cloud–backed VectorIndex — satisfies the phase 4.1 VectorIndex protocol.

Connects to Chroma Cloud (api.trychroma.com) via the chromadb Python client.
One collection per corpus — the collection name encodes the deployment, not
the corpus_version (versions are stored as metadata so a single collection
holds every version, enabling shadow-rebuild and atomic pointer swap without
creating/deleting collections).

Soft-delete stores `deleted: "true"` + `deleted_at_ts` (Unix epoch int) in
metadata so hard_purge_older_than can filter by age using Chroma's numeric
`$lte` operator.

Why not pgvector?
  * No self-hosted Postgres with the pgvector extension required.
  * Chroma Cloud is managed (HNSW, backups, scaling) — zero infra for the
    vector dimension of the stack.
  * All other stores (BM25, fact_kv, embedding_cache, corpus_pointer) remain
    in Postgres because Chroma has no relational/FTS capability.
"""
from __future__ import annotations

import time
from typing import Any


class ChromaVectorIndex:
    """Chroma Cloud implementation of the VectorIndex protocol (§5.8).

    Parameters
    ----------
    api_key:
        Chroma Cloud API key (`CHROMA_API_KEY` env var in prod).
    collection_name:
        Logical name for the collection (e.g. ``"mf_rag"``).  One collection
        for the whole deployment; corpus_version lives in row metadata.
    tenant:
        Chroma Cloud tenant (default ``"default_tenant"``).
    database:
        Chroma Cloud database within the tenant (default ``"default_database"``).
    """

    def __init__(
        self,
        api_key: str,
        collection_name: str = "mf_rag",
        tenant: str = "default_tenant",
        database: str = "default_database",
    ):
        import chromadb  # lazy — not needed for phase 4.x tests

        self._client = chromadb.HttpClient(
            host="api.trychroma.com",
            ssl=True,
            headers={"x-chroma-token": api_key},
            tenant=tenant,
            database=database,
        )
        self._collection_name = collection_name
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ---- VectorIndex protocol --------------------------------------------

    def upsert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        self._col.upsert(
            ids=[r["chunk_id"] for r in rows],
            embeddings=[_parse_embedding(r["embedding"]) for r in rows],
            documents=[r["text"] for r in rows],
            metadatas=[_to_chroma_meta(r) for r in rows],
        )

    def soft_delete(self, chunk_ids: list[str]) -> int:
        if not chunk_ids:
            return 0
        now_ts = int(time.time())
        # `update` patches metadata without re-uploading embeddings.
        existing = self._col.get(ids=chunk_ids, include=["metadatas"])
        if not existing["ids"]:
            return 0
        updated_metas = []
        for meta in existing["metadatas"]:
            m = dict(meta)
            m["deleted"] = "true"
            m["deleted_at_ts"] = now_ts
            updated_metas.append(m)
        self._col.update(ids=existing["ids"], metadatas=updated_metas)
        return len(existing["ids"])

    def chunk_ids_for_source(
        self, source_id: str, corpus_version: str
    ) -> list[str]:
        result = self._col.get(
            where={
                "$and": [
                    {"source_id": {"$eq": source_id}},
                    {"corpus_version": {"$eq": corpus_version}},
                    {"deleted": {"$eq": "false"}},
                ]
            },
            include=[],
        )
        return result["ids"]

    def count(self, corpus_version: str) -> int:
        result = self._col.get(
            where={
                "$and": [
                    {"corpus_version": {"$eq": corpus_version}},
                    {"deleted": {"$eq": "false"}},
                ]
            },
            include=[],
        )
        return len(result["ids"])

    # ---- Helpers used by the smoke runner --------------------------------

    def distinct_source_ids(self, corpus_version: str) -> list[str]:
        result = self._col.get(
            where={
                "$and": [
                    {"corpus_version": {"$eq": corpus_version}},
                    {"deleted": {"$eq": "false"}},
                ]
            },
            include=["metadatas"],
        )
        return sorted({m["source_id"] for m in result["metadatas"]})

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 20,
        corpus_version: str = "",
        scheme_filter: str | None = None,
    ) -> list[dict]:
        """Vector similarity search — returns rows sorted by cosine score descending.

        ``corpus_version`` is ignored when empty (Chroma collection holds one
        live version; the ingestion pipeline owns version management).
        Chroma cosine distance = 1 - similarity, so score = 1 - distance.
        """
        where: dict | None = None
        filters: list[dict] = [{"deleted": {"$eq": "false"}}]
        if corpus_version:
            filters.append({"corpus_version": {"$eq": corpus_version}})
        if scheme_filter:
            filters.append({"scheme": {"$eq": scheme_filter}})
        if len(filters) == 1:
            where = filters[0]
        elif len(filters) > 1:
            where = {"$and": filters}

        result = self._col.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._col.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        rows: list[dict] = []
        ids       = result["ids"][0]
        docs      = result["documents"][0]
        metas     = result["metadatas"][0]
        distances = result["distances"][0]
        for chunk_id, text, meta, dist in zip(ids, docs, metas, distances):
            score = max(0.0, 1.0 - dist)
            rows.append({
                "chunk_id":     chunk_id,
                "text":         text,
                "source_id":    meta.get("source_id", ""),
                "scheme":       meta.get("scheme", ""),
                "section":      meta.get("section", ""),
                "segment_type": meta.get("segment_type", ""),
                "source_url":   meta.get("source_url", ""),
                "last_updated": meta.get("last_updated", ""),
                "score":        score,
                "dense_score":  score,
            })
        return rows

    def hard_purge_older_than(self, cutoff_days: int) -> int:
        """Permanently delete rows soft-deleted more than ``cutoff_days`` ago."""
        cutoff_ts = int(time.time()) - cutoff_days * 86400
        result = self._col.get(
            where={
                "$and": [
                    {"deleted": {"$eq": "true"}},
                    {"deleted_at_ts": {"$lte": cutoff_ts}},
                ]
            },
            include=[],
        )
        if not result["ids"]:
            return 0
        self._col.delete(ids=result["ids"])
        return len(result["ids"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_embedding(emb: Any) -> list[float]:
    """Accept both a Python list and the pgvector string form '[0.1,...]'."""
    if isinstance(emb, list):
        return [float(x) for x in emb]
    return [float(x) for x in str(emb).strip("[]").split(",")]


def _to_chroma_meta(row: dict[str, Any]) -> dict[str, Any]:
    """Convert an IndexWriter row dict to Chroma-compatible metadata.

    Chroma metadata values must be str, int, float, or bool — no None.
    """
    return {
        "corpus_version":  row["corpus_version"],
        "source_id":       row["source_id"],
        "scheme":          row.get("scheme") or "",
        "section":         row.get("section") or "",
        "segment_type":    row["segment_type"],
        "embed_model_id":  row["embed_model_id"],
        "chunk_hash":      row["chunk_hash"],
        "source_url":      row["source_url"],
        "last_updated":    row["last_updated"],
        "dim":             int(row["dim"]),
        "deleted":         "false",
        "deleted_at_ts":   0,          # 0 = not deleted
    }
