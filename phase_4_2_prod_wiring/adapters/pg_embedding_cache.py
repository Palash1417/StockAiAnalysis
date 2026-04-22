"""Postgres-backed EmbeddingCache — §5.5.

Embeddings are packed as little-endian float32 BYTEA so the row size stays
deterministic and the cache is backend-agnostic (no pgvector dependency on
the cache table itself). `chunk_hash` already encodes the embed_model_id,
so a model swap invalidates the cache without any migration.
"""
from __future__ import annotations

import struct
from typing import Any, Callable, Iterable


class PgEmbeddingCache:
    def __init__(self, connect: Callable[[], Any]):
        self._connect = connect

    def get_many(
        self, chunk_hashes: Iterable[str]
    ) -> dict[str, tuple[list[float], int]]:
        hashes = list(chunk_hashes)
        if not hashes:
            return {}
        sql = """
            SELECT chunk_hash, embedding, dim
              FROM embedding_cache
             WHERE chunk_hash = ANY(%s)
        """
        out: dict[str, tuple[list[float], int]] = {}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, (hashes,))
            for chunk_hash, blob, dim in cur.fetchall():
                out[chunk_hash] = (_unpack(blob, dim), dim)
        return out

    def put_many(self, rows: dict[str, tuple[list[float], int]]) -> None:
        if not rows:
            return
        sql = """
            INSERT INTO embedding_cache (chunk_hash, embedding, dim)
            VALUES (%s, %s, %s)
            ON CONFLICT (chunk_hash) DO UPDATE SET
                embedding = EXCLUDED.embedding,
                dim       = EXCLUDED.dim
        """
        params = [
            (chunk_hash, _pack(vec, dim), dim)
            for chunk_hash, (vec, dim) in rows.items()
        ]
        with self._connect() as conn, conn.cursor() as cur:
            cur.executemany(sql, params)


def _pack(vec: list[float], dim: int) -> bytes:
    if len(vec) != dim:
        raise ValueError(f"vector length {len(vec)} != declared dim {dim}")
    return struct.pack(f"<{dim}f", *vec)


def _unpack(blob: bytes, dim: int) -> list[float]:
    expected = dim * 4
    if len(blob) != expected:
        raise ValueError(
            f"cached blob length {len(blob)} != {expected} bytes for dim={dim}"
        )
    return list(struct.unpack(f"<{dim}f", blob))
