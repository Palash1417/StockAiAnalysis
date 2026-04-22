"""Reranker implementations — §6.3.

PassthroughReranker  — no cross-encoder; sorts by existing score (dev/tests).
CrossEncoderReranker — sentence-transformers CrossEncoder (bge-reranker-base).
build_reranker(config) factory keyed by config['provider'].
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

_SCORE_FIELD = "score"
_RERANK_FIELD = "rerank_score"


class PassthroughReranker:
    """Returns top_n candidates sorted by their current score.

    Satisfies the Reranker protocol without requiring sentence-transformers.
    Useful in dev when bge-reranker-base is not installed and in all unit tests.
    """

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        ranked = sorted(candidates, key=lambda d: d.get(_SCORE_FIELD, 0.0), reverse=True)
        out = []
        for doc in ranked[:top_n]:
            d = doc.copy()
            d[_RERANK_FIELD] = d.get(_SCORE_FIELD, 0.0)
            out.append(d)
        return out


class CrossEncoderReranker:
    """sentence-transformers CrossEncoder — loads lazily (§6.3).

    Supports BAAI/bge-reranker-base (default) and Cohere-compatible models.
    For Cohere Rerank v3 use the separate CohereReranker class (not yet impl).
    """

    def __init__(self, model: str = "BAAI/bge-reranker-base"):
        self._model_name = model
        self._model = None  # lazy-loaded

    def _load(self) -> None:
        if self._model is None:
            from sentence_transformers import CrossEncoder  # type: ignore
            self._model = CrossEncoder(self._model_name)

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        *,
        top_n: int = 5,
    ) -> list[dict[str, Any]]:
        if not candidates:
            return []
        self._load()
        pairs = [(query, doc["text"]) for doc in candidates]
        scores = self._model.predict(pairs)  # type: ignore[union-attr]
        scored = [(doc, float(sc)) for doc, sc in zip(candidates, scores)]
        scored.sort(key=lambda x: x[1], reverse=True)
        out = []
        for doc, sc in scored[:top_n]:
            d = doc.copy()
            d[_RERANK_FIELD] = sc
            d[_SCORE_FIELD] = sc
            out.append(d)
        return out


def build_reranker(config: dict[str, Any]) -> PassthroughReranker | CrossEncoderReranker:
    """Factory: provider ∈ {passthrough, cross_encoder}."""
    provider = config.get("provider", "passthrough")
    if provider == "passthrough":
        return PassthroughReranker()
    if provider == "cross_encoder":
        return CrossEncoderReranker(model=config.get("model", "BAAI/bge-reranker-base"))
    raise ValueError(f"unknown reranker provider: {provider!r}")
