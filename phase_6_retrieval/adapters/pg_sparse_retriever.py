"""Postgres FTS-backed sparse retrieval — §6.1.

Joins bm25_docs (tsvector) with chunks (metadata + corpus_version / soft-delete
filter) so we never surface deleted or wrong-version rows.

ts_rank_cd scores are not bounded to [0, 1] but are comparable within a result
set — the RRF fusion only uses rank position, not the raw score, so this is fine.
"""
from __future__ import annotations

from typing import Any, Callable


class PgSparseRetriever:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def search(
        self,
        query: str,
        corpus_version: str,
        top_k: int,
        *,
        scheme_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [query, corpus_version]
        scheme_clause = ""
        if scheme_filter:
            scheme_clause = "AND c.scheme = %s"
            params.append(scheme_filter)
        params.extend([query, query, top_k])

        sql = f"""
            SELECT c.chunk_id, c.source_id, c.scheme, c.section, c.segment_type,
                   c.text, c.source_url, c.last_updated,
                   ts_rank_cd(b.tsv, plainto_tsquery('english', %s)) AS score
              FROM bm25_docs b
              JOIN chunks c ON c.chunk_id = b.chunk_id
             WHERE c.corpus_version = %s
               AND c.deleted_at IS NULL
               {scheme_clause}
               AND b.tsv @@ plainto_tsquery('english', %s)
             ORDER BY score DESC
             LIMIT %s
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

        return [
            {
                "chunk_id": r[0],
                "source_id": r[1],
                "scheme": r[2],
                "section": r[3],
                "segment_type": r[4],
                "text": r[5],
                "source_url": r[6],
                "last_updated": r[7],
                "score": float(r[8]),
                "sparse_score": float(r[8]),
            }
            for r in rows
        ]
