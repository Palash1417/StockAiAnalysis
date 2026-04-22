"""In-memory DenseRetriever and SparseRetriever for unit tests and local dev.

InMemoryDenseRetriever — exact cosine similarity over stored rows (O(n) scan).
InMemoryBM25Retriever  — BM25 scoring (k1=1.5, b=0.75) over stored rows.

Both implement the DenseRetriever / SparseRetriever protocols without any
external dependencies so they run in CI without a database or GPU.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _strip_embedding(row: dict[str, Any]) -> dict[str, Any]:
    d = row.copy()
    d.pop("embedding", None)
    return d


class InMemoryDenseRetriever:
    """For tests: O(n) cosine scan over pre-loaded row dicts.

    Each row dict must have an 'embedding' key (list[float]) plus the standard
    metadata fields (chunk_id, source_id, scheme, section, segment_type, text,
    source_url, last_updated).  Call add() to load rows before searching.
    """

    def __init__(self) -> None:
        # (corpus_version, chunk_id) → row dict (including embedding)
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}

    def add(self, corpus_version: str, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            self._rows[(corpus_version, row["chunk_id"])] = row

    def search(
        self,
        embedding: list[float],
        corpus_version: str,
        top_k: int,
        *,
        scheme_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        candidates = [
            row for (cv, _), row in self._rows.items()
            if cv == corpus_version
            and (scheme_filter is None or row.get("scheme") == scheme_filter)
        ]
        scored = []
        for row in candidates:
            sim = _cosine(embedding, row["embedding"])
            out = _strip_embedding(row)
            out["score"] = sim
            out["dense_score"] = sim
            scored.append(out)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]


class InMemoryBM25Retriever:
    """BM25 (k1=1.5, b=0.75) over pre-loaded row dicts.

    Each row dict must have 'chunk_id' and 'text' keys, plus the standard
    metadata fields. Call add() to load rows before searching.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self._k1 = k1
        self._b = b
        self._rows: dict[tuple[str, str], dict[str, Any]] = {}
        self._tokens: dict[tuple[str, str], list[str]] = {}

    def add(self, corpus_version: str, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            key = (corpus_version, row["chunk_id"])
            self._rows[key] = row
            self._tokens[key] = _tokenize(row["text"])

    def search(
        self,
        query: str,
        corpus_version: str,
        top_k: int,
        *,
        scheme_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return []

        cv_keys = {
            key for key in self._rows
            if key[0] == corpus_version
            and (scheme_filter is None or self._rows[key].get("scheme") == scheme_filter)
        }
        if not cv_keys:
            return []

        N = len(cv_keys)
        avg_dl = sum(len(self._tokens[k]) for k in cv_keys) / N if N else 1.0

        scored = []
        for key in cv_keys:
            tokens = self._tokens[key]
            dl = len(tokens)
            tf_counts = Counter(tokens)
            score = 0.0
            for qt in q_tokens:
                tf = tf_counts.get(qt, 0)
                df = sum(1 for k in cv_keys if qt in self._tokens[k])
                idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
                tf_norm = (
                    tf * (self._k1 + 1)
                    / (tf + self._k1 * (1 - self._b + self._b * dl / avg_dl))
                )
                score += idf * tf_norm
            if score > 0:
                out = _strip_embedding(self._rows[key])
                out["score"] = score
                out["sparse_score"] = score
                scored.append(out)

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]
