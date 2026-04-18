"""Embedding cache — §5.5.

Postgres-backed in prod (`embedding_cache(chunk_hash PK, embedding BYTEA, dim,
created_at)`). The in-memory implementation below satisfies the same
protocol and is used in dev + tests.
"""
from __future__ import annotations

from typing import Iterable, Protocol


class EmbeddingCache(Protocol):
    def get_many(self, chunk_hashes: Iterable[str]) -> dict[str, tuple[list[float], int]]: ...
    def put_many(self, rows: dict[str, tuple[list[float], int]]) -> None: ...


class InMemoryEmbeddingCache:
    def __init__(self) -> None:
        self._store: dict[str, tuple[list[float], int]] = {}

    def get_many(self, chunk_hashes):
        return {h: self._store[h] for h in chunk_hashes if h in self._store}

    def put_many(self, rows):
        self._store.update(rows)

    def __contains__(self, chunk_hash: str) -> bool:
        return chunk_hash in self._store

    def __len__(self) -> int:
        return len(self._store)
