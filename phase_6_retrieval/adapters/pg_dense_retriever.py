"""pgvector cosine-similarity dense retrieval — §6.1.

Uses the `<=>` (cosine distance) operator from pgvector. Cosine similarity
= 1 − cosine_distance, so the ORDER BY is ascending (closest first) while
the returned `score` is the similarity (higher = better).

Connection factory pattern matches phase 4.2 adapters so the same pool can
be shared across ingestion and retrieval at composition time.
"""
from __future__ import annotations

from typing import Any, Callable


class PgDenseRetriever:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def search(
        self,
        embedding: list[float],
        corpus_version: str,
        top_k: int,
        *,
        scheme_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        vec_str = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        params: list[Any] = [vec_str, corpus_version]
        scheme_clause = ""
        if scheme_filter:
            scheme_clause = "AND scheme = %s"
            params.append(scheme_filter)
        params.extend([vec_str, top_k])

        sql = f"""
            SELECT chunk_id, source_id, scheme, section, segment_type,
                   text, source_url, last_updated,
                   1 - (embedding <=> %s::vector) AS score
              FROM chunks
             WHERE corpus_version = %s
               AND deleted_at IS NULL
               {scheme_clause}
             ORDER BY embedding <=> %s::vector
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
                "dense_score": float(r[8]),
            }
            for r in rows
        ]
