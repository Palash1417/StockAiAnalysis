"""Reciprocal Rank Fusion — §6.1.

RRF(d) = Σ  1 / (k + rank_in_list_i)

Both input lists are assumed ranked best-first. Each dict must have a
'chunk_id' key. Metadata (scheme, text, source_url, etc.) is carried forward
from the first list that contained the chunk; sparse_score is backfilled when
the chunk also appears in the sparse list.
"""
from __future__ import annotations

from typing import Any


def rrf_fuse(
    dense: list[dict[str, Any]],
    sparse: list[dict[str, Any]],
    *,
    k: int = 60,
    top_k: int = 15,
) -> list[dict[str, Any]]:
    rrf_scores: dict[str, float] = {}
    metadata: dict[str, dict[str, Any]] = {}

    for rank, doc in enumerate(dense, start=1):
        cid = doc["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in metadata:
            meta = doc.copy()
            meta["dense_score"] = doc.get("score")
            meta.pop("embedding", None)  # never expose raw vectors
            metadata[cid] = meta

    for rank, doc in enumerate(sparse, start=1):
        cid = doc["chunk_id"]
        rrf_scores[cid] = rrf_scores.get(cid, 0.0) + 1.0 / (k + rank)
        if cid not in metadata:
            meta = doc.copy()
            meta["sparse_score"] = doc.get("score")
            meta.pop("embedding", None)
            metadata[cid] = meta
        else:
            metadata[cid]["sparse_score"] = doc.get("score")

    top_ids = sorted(rrf_scores, key=lambda cid: rrf_scores[cid], reverse=True)[:top_k]

    result: list[dict[str, Any]] = []
    for cid in top_ids:
        doc = metadata[cid].copy()
        doc["rrf_score"] = rrf_scores[cid]
        doc["score"] = rrf_scores[cid]
        result.append(doc)

    return result
