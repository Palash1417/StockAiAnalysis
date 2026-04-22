"""Postgres FTS-backed BM25Index.

Phase 4.1's spec allows any sparse backend (rank_bm25, OpenSearch, ...); FTS
is the lowest-dependency option since we already need Postgres for pgvector.
Ranking in the retrieval step uses `ts_rank_cd(tsv, plainto_tsquery(...))`.
"""
from __future__ import annotations

import json
from typing import Any, Callable


class PgBM25Index:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def upsert(self, chunk_id: str, text: str, metadata: dict) -> None:
        sql = """
            INSERT INTO bm25_docs (chunk_id, text, metadata, tsv, updated_at)
            VALUES (%s, %s, %s::jsonb, to_tsvector('english', %s), NOW())
            ON CONFLICT (chunk_id) DO UPDATE SET
                text       = EXCLUDED.text,
                metadata   = EXCLUDED.metadata,
                tsv        = EXCLUDED.tsv,
                updated_at = NOW()
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (chunk_id, text, json.dumps(metadata), text))

    def delete(self, chunk_id: str) -> None:
        sql = "DELETE FROM bm25_docs WHERE chunk_id = %s"
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (chunk_id,))

    # ---- diagnostic helpers -----------------------------------------------
    def count(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM bm25_docs")
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def __contains__(self, chunk_id: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM bm25_docs WHERE chunk_id = %s LIMIT 1",
                (chunk_id,),
            )
            return cur.fetchone() is not None
