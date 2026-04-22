"""Tests for HybridRetriever end-to-end (in-memory stores, no network)."""
from __future__ import annotations

import pytest

from phase_6_retrieval.reranker import PassthroughReranker
from phase_6_retrieval.retriever import HybridRetriever


@pytest.fixture
def retriever(embedder, dense_retriever, sparse_retriever, live_pointer):
    return HybridRetriever(
        embedder=embedder,
        dense=dense_retriever,
        sparse=sparse_retriever,
        reranker=PassthroughReranker(),
        corpus_pointer=live_pointer,
    )


class TestRetrieverBasic:
    def test_returns_candidates(self, retriever, corpus_version):
        # score_threshold=0.0 because PassthroughReranker keeps RRF scores
        # (~0.016–0.033), which are well below the prod threshold of 0.35
        # (designed for cross-encoder outputs). The threshold gate is tested
        # separately in TestRetrieverBelowThreshold.
        result = retriever.retrieve(
            "expense ratio Bandhan Small Cap",
            corpus_version=corpus_version,
            score_threshold=0.0,
        )
        assert result.candidates, "expected at least one candidate"
        assert result.corpus_version == corpus_version

    def test_top_candidate_has_required_fields(self, retriever, corpus_version):
        result = retriever.retrieve(
            "expense ratio Bandhan Small Cap",
            corpus_version=corpus_version,
            score_threshold=0.0,
        )
        top = result.top()
        assert top is not None
        assert top.chunk_id
        assert top.text
        assert top.source_url
        assert top.last_updated

    def test_candidates_sorted_by_score_desc(self, retriever, corpus_version):
        result = retriever.retrieve(
            "expense ratio", corpus_version=corpus_version, score_threshold=0.0
        )
        scores = [c.score for c in result.candidates]
        assert scores == sorted(scores, reverse=True)

    def test_top_n_respected(self, retriever, corpus_version):
        result = retriever.retrieve(
            "fund",
            corpus_version=corpus_version,
            top_n_rerank=2,
            score_threshold=0.0,
        )
        assert len(result.candidates) <= 2

    def test_retrieved_at_is_iso8601(self, retriever, corpus_version):
        from datetime import datetime
        result = retriever.retrieve(
            "expense", corpus_version=corpus_version, score_threshold=0.0
        )
        dt = datetime.fromisoformat(result.retrieved_at)
        assert dt is not None


class TestRetrieverSchemeFilter:
    def test_scheme_filter_limits_results(
        self, embedder, sparse_retriever, live_pointer, corpus_version, sample_rows
    ):
        from phase_6_retrieval.adapters.in_memory_retriever import InMemoryDenseRetriever

        dr = InMemoryDenseRetriever()
        dr.add(corpus_version, sample_rows)
        r = HybridRetriever(
            embedder=embedder,
            dense=dr,
            sparse=sparse_retriever,
            reranker=PassthroughReranker(),
            corpus_pointer=live_pointer,
        )
        result = r.retrieve(
            "expense ratio",
            corpus_version=corpus_version,
            scheme_filter="Bandhan Small Cap Fund Direct - Growth",
            score_threshold=0.0,
        )
        assert result.candidates
        for c in result.candidates:
            assert c.scheme == "Bandhan Small Cap Fund Direct - Growth"


class TestRetrieverBelowThreshold:
    def test_below_threshold_returns_empty_candidates(
        self, embedder, sparse_retriever, live_pointer, corpus_version, sample_rows
    ):
        from phase_6_retrieval.adapters.in_memory_retriever import InMemoryDenseRetriever

        dr = InMemoryDenseRetriever()
        dr.add(corpus_version, sample_rows)
        r = HybridRetriever(
            embedder=embedder,
            dense=dr,
            sparse=sparse_retriever,
            reranker=PassthroughReranker(),
            corpus_pointer=live_pointer,
        )
        # threshold of 99.0 forces below-threshold for any real result
        result = r.retrieve(
            "expense ratio",
            corpus_version=corpus_version,
            score_threshold=99.0,
        )
        assert result.below_threshold is True
        assert result.candidates == []


class TestRetrieverQueryRewrite:
    def test_rewriter_called(self, retriever, corpus_version):
        class _SpyRewriter:
            called_with: list[str] = []

            def rewrite(self, query, history=None):
                self.called_with.append(query)
                return query + " expanded"

        spy = _SpyRewriter()
        retriever._rewriter = spy
        retriever.retrieve(
            "SIP investment", corpus_version=corpus_version, score_threshold=0.0
        )
        assert "SIP investment" in spy.called_with

    def test_no_rewriter_still_works(self, embedder, dense_retriever, sparse_retriever, live_pointer, corpus_version):
        r = HybridRetriever(
            embedder=embedder,
            dense=dense_retriever,
            sparse=sparse_retriever,
            reranker=PassthroughReranker(),
            corpus_pointer=live_pointer,
            query_rewriter=None,
        )
        result = r.retrieve("expense ratio", corpus_version=corpus_version)
        assert result.rewritten_query is None


class TestRetrieverCorpusPointer:
    def test_uses_live_version_from_pointer(self, embedder, sample_rows):
        from phase_6_retrieval.adapters.in_memory_retriever import (
            InMemoryBM25Retriever,
            InMemoryDenseRetriever,
        )

        v2 = "corpus_v_new"
        dr = InMemoryDenseRetriever()
        sr = InMemoryBM25Retriever()
        dr.add(v2, sample_rows)
        sr.add(v2, sample_rows)

        class _Ptr:
            def get_live(self):
                return v2

        r = HybridRetriever(
            embedder=embedder,
            dense=dr,
            sparse=sr,
            reranker=PassthroughReranker(),
            corpus_pointer=_Ptr(),
        )
        result = r.retrieve("expense ratio")
        assert result.corpus_version == v2
