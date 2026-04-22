"""pgvector-backed VectorIndex — satisfies phase 4.1's VectorIndex protocol.

Uses a composite PK (corpus_version, chunk_id) so the same chunk_id can co-exist
across two corpus versions during a shadow rebuild (§5.9). Soft-delete flips
`deleted_at`; `count()` and `chunk_ids_for_source()` ignore deleted rows.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Iterable


class PgVectorIndex:
    """`connect` is a zero-arg factory returning a psycopg.Connection.

    The adapter does not own its connection pool — the composition layer
    provides a factory. That keeps tests trivial (hand in a fake) and lets
    prod share a pool across adapters.
    """

    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    # ---- VectorIndex protocol --------------------------------------------
    def upsert(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return
        sql = """
            INSERT INTO chunks (
                corpus_version, chunk_id, source_id, scheme, section,
                segment_type, text, embedding, embed_model_id, chunk_hash,
                source_url, last_updated, dim, deleted_at
            ) VALUES (
                %(corpus_version)s, %(chunk_id)s, %(source_id)s, %(scheme)s,
                %(section)s, %(segment_type)s, %(text)s, %(embedding)s,
                %(embed_model_id)s, %(chunk_hash)s, %(source_url)s,
                %(last_updated)s, %(dim)s, NULL
            )
            ON CONFLICT (corpus_version, chunk_id) DO UPDATE SET
                source_id      = EXCLUDED.source_id,
                scheme         = EXCLUDED.scheme,
                section        = EXCLUDED.section,
                segment_type   = EXCLUDED.segment_type,
                text           = EXCLUDED.text,
                embedding      = EXCLUDED.embedding,
                embed_model_id = EXCLUDED.embed_model_id,
                chunk_hash     = EXCLUDED.chunk_hash,
                source_url     = EXCLUDED.source_url,
                last_updated   = EXCLUDED.last_updated,
                dim            = EXCLUDED.dim,
                deleted_at     = NULL
        """
        params = [self._row_to_params(r) for r in rows]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(sql, params)

    def soft_delete(self, chunk_ids: list[str]) -> int:
        if not chunk_ids:
            return 0
        now = datetime.now(timezone.utc)
        sql = """
            UPDATE chunks
               SET deleted_at = %s
             WHERE chunk_id = ANY(%s)
               AND deleted_at IS NULL
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (now, list(chunk_ids)))
            return cur.rowcount or 0

    def chunk_ids_for_source(
        self, source_id: str, corpus_version: str
    ) -> list[str]:
        sql = """
            SELECT chunk_id
              FROM chunks
             WHERE source_id = %s
               AND corpus_version = %s
               AND deleted_at IS NULL
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (source_id, corpus_version))
            return [row[0] for row in cur.fetchall()]

    def count(self, corpus_version: str) -> int:
        sql = """
            SELECT COUNT(*) FROM chunks
             WHERE corpus_version = %s AND deleted_at IS NULL
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (corpus_version,))
            row = cur.fetchone()
            return int(row[0]) if row else 0

    # ---- Helpers used by the smoke runner --------------------------------
    def distinct_source_ids(self, corpus_version: str) -> list[str]:
        sql = """
            SELECT DISTINCT source_id FROM chunks
             WHERE corpus_version = %s AND deleted_at IS NULL
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (corpus_version,))
            return sorted(row[0] for row in cur.fetchall())

    def hard_purge_older_than(self, cutoff_days: int = 7) -> int:
        """Permanently removes rows soft-deleted before the cutoff (§5.8)."""
        sql = """
            DELETE FROM chunks
             WHERE deleted_at IS NOT NULL
               AND deleted_at < NOW() - make_interval(days => %s)
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (cutoff_days,))
            return cur.rowcount or 0

    # ----------------------------------------------------------------------
    @staticmethod
    def _row_to_params(row: dict[str, Any]) -> dict[str, Any]:
        embedding = row["embedding"]
        if isinstance(embedding, list):
            # pgvector accepts Python lists only when the `pgvector.psycopg`
            # type registration has been installed on the connection. The
            # fallback string form `[0.1,0.2,...]` works without it.
            embedding = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"
        return {
            "corpus_version": row["corpus_version"],
            "chunk_id": row["chunk_id"],
            "source_id": row["source_id"],
            "scheme": row.get("scheme"),
            "section": row.get("section"),
            "segment_type": row["segment_type"],
            "text": row["text"],
            "embedding": embedding,
            "embed_model_id": row["embed_model_id"],
            "chunk_hash": row["chunk_hash"],
            "source_url": row["source_url"],
            "last_updated": row["last_updated"],
            "dim": row["dim"],
        }
