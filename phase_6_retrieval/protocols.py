"""Retrieval protocols — §6.1.

DenseRetriever, SparseRetriever, and Reranker are structural (Protocol) so any
class that has the right method signatures satisfies the interface without
explicit subclassing. The in-memory and Pg adapters both conform.
"""
from __future__ import annotations

from typing import Any, Protocol


class DenseRetriever(Protocol):
    """Returns top-K chunks by cosine similarity, ranked best-first."""

    def search(
        self,
        embedding: list[float],
        corpus_version: str,
        top_k: int,
        *,
        scheme_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Each result dict must contain: chunk_id, source_id, scheme, section,
        segment_type, text, source_url, last_updated, score (cosine sim 0–1),
        dense_score (same as score).
        """
        ...


class SparseRetriever(Protocol):
    """Returns top-K chunks by BM25 / FTS score, ranked best-first."""

    def search(
        self,
        query: str,
        corpus_version: str,
        top_k: int,
        *,
        scheme_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Each result dict must contain the same fields as DenseRetriever plus
        sparse_score (BM25/ts_rank score).
        """
        ...


class Reranker(Protocol):
    """Cross-encoder or passthrough reranker."""

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        """Returns up to top_n candidates sorted by rerank score descending.
        Each dict gets 'score' and 'rerank_score' fields updated.
        """
        ...
