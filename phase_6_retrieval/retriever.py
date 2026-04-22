"""HybridRetriever — §6 orchestrator.

Pipeline:
  query rewrite (optional LLM call)
  → embed query  (EmbedderProtocol.embed_batch)
  → dense search (DenseRetriever.search)
  + sparse search (SparseRetriever.search)
  → RRF fusion   (rrf_fuse)
  → rerank       (Reranker.rerank)
  → score threshold filter
  → RetrievalResult
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from .fusion import rrf_fuse
from .models import CandidateChunk, RetrievalResult

log = logging.getLogger(__name__)


class HybridRetriever:
    """Wires dense + sparse retrieval, RRF fusion, and reranking (§6.1–§6.4).

    Accepts any objects that satisfy the DenseRetriever, SparseRetriever,
    Reranker, CorpusPointer, and EmbedderProtocol structural protocols —
    no explicit subclassing required.

    corpus_pointer.get_live() resolves the live corpus version; pass a
    hardcoded version string instead via the corpus_version kwarg if needed
    (useful in tests).
    """

    def __init__(
        self,
        embedder: Any,
        dense: Any,
        sparse: Any,
        reranker: Any,
        corpus_pointer: Any,
        *,
        fact_kv: Any = None,
        query_rewriter: Any = None,
        rrf_k: int = 60,
        score_threshold: float = 0.35,
    ):
        self._embedder = embedder
        self._dense = dense
        self._sparse = sparse
        self._reranker = reranker
        self._pointer = corpus_pointer
        self._fact_kv = fact_kv
        self._rewriter = query_rewriter
        self._rrf_k = rrf_k
        self._score_threshold = score_threshold

    def retrieve(
        self,
        query: str,
        *,
        thread_history: list[dict[str, str]] | None = None,
        scheme_filter: str | None = None,
        top_k_dense: int = 20,
        top_k_sparse: int = 20,
        top_k_rrf: int = 15,
        top_n_rerank: int = 5,
        score_threshold: float | None = None,
        corpus_version: str | None = None,
    ) -> RetrievalResult:
        """Run the full retrieval pipeline (§6).

        Returns RetrievalResult. If no candidate exceeds score_threshold,
        candidates is empty and below_threshold=True — the caller should
        route to the 'not found' response path (§6.3).
        """
        # resolve threshold: caller override → instance default
        effective_threshold = score_threshold if score_threshold is not None else self._score_threshold

        # 1. Corpus version
        live_version = corpus_version or (self._pointer.get_live() or "")

        # 2. Query rewrite (optional LLM, falls back to abbrev expansion)
        rewritten = query
        if self._rewriter is not None:
            rewritten = self._rewriter.rewrite(query, history=thread_history)
            if rewritten != query:
                log.debug("query rewritten: %r → %r", query, rewritten)

        # 3. Embed query using the embedder's low-level batch API
        query_vec: list[float] = self._embedder.embed_batch([rewritten])[0]

        # 4. Dense retrieval (cosine, top_k_dense)
        dense_hits = self._dense.search(
            query_vec, live_version, top_k_dense, scheme_filter=scheme_filter
        )

        # 5. Sparse retrieval (BM25/FTS, top_k_sparse)
        sparse_hits = self._sparse.search(
            rewritten, live_version, top_k_sparse, scheme_filter=scheme_filter
        )

        # 6. RRF fusion → top_k_rrf
        fused = rrf_fuse(dense_hits, sparse_hits, k=self._rrf_k, top_k=top_k_rrf)

        # 7. Rerank → top_n_rerank
        reranked = self._reranker.rerank(rewritten, fused, top_n=top_n_rerank)

        # 8. Score threshold: if best score < threshold → below_threshold path
        candidates = _to_candidates(reranked)
        below_threshold = bool(candidates and candidates[0].score < effective_threshold)
        if below_threshold:
            log.debug(
                "top score %.3f < threshold %.3f — routing to 'not found'",
                candidates[0].score,
                effective_threshold,
            )
            candidates = []

        return RetrievalResult(
            query=query,
            rewritten_query=rewritten if rewritten != query else None,
            candidates=candidates,
            corpus_version=live_version,
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            below_threshold=below_threshold,
        )


def _to_candidates(docs: list[dict[str, Any]]) -> list[CandidateChunk]:
    return [
        CandidateChunk(
            chunk_id=d["chunk_id"],
            source_id=d["source_id"],
            scheme=d.get("scheme"),
            section=d.get("section"),
            segment_type=d.get("segment_type", ""),
            text=d["text"],
            source_url=d["source_url"],
            last_updated=d["last_updated"],
            score=float(d.get("score", 0.0)),
            dense_score=d.get("dense_score"),
            sparse_score=d.get("sparse_score"),
            rrf_score=d.get("rrf_score"),
        )
        for d in docs
    ]
