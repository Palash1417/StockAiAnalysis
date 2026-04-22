"""Tests for reranker implementations."""
from __future__ import annotations

import pytest

from phase_6_retrieval.reranker import PassthroughReranker, build_reranker


def _candidate(chunk_id: str, score: float, text: str = "some text") -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": "src_001",
        "scheme": "Test Fund",
        "section": None,
        "segment_type": "fact_table",
        "text": text,
        "source_url": "https://example.com",
        "last_updated": "2026-04-19",
        "score": score,
        "rrf_score": score,
    }


class TestPassthroughReranker:
    def test_empty_input(self):
        r = PassthroughReranker()
        assert r.rerank("query", []) == []

    def test_top_n_respected(self):
        r = PassthroughReranker()
        candidates = [_candidate(f"c{i}", float(10 - i)) for i in range(10)]
        result = r.rerank("query", candidates, top_n=3)
        assert len(result) == 3

    def test_sorted_by_score_descending(self):
        r = PassthroughReranker()
        candidates = [
            _candidate("low", 0.2),
            _candidate("high", 0.9),
            _candidate("mid", 0.5),
        ]
        result = r.rerank("query", candidates, top_n=5)
        scores = [d["score"] for d in result]
        assert scores == sorted(scores, reverse=True)

    def test_top_chunk_is_highest_score(self):
        r = PassthroughReranker()
        candidates = [_candidate("a", 0.3), _candidate("b", 0.8), _candidate("c", 0.1)]
        result = r.rerank("query", candidates, top_n=3)
        assert result[0]["chunk_id"] == "b"

    def test_rerank_score_field_set(self):
        r = PassthroughReranker()
        candidates = [_candidate("x", 0.7)]
        result = r.rerank("query", candidates, top_n=1)
        assert "rerank_score" in result[0]
        assert result[0]["rerank_score"] == pytest.approx(0.7)

    def test_original_candidate_not_mutated(self):
        r = PassthroughReranker()
        original = _candidate("x", 0.5)
        original_copy = dict(original)
        r.rerank("query", [original], top_n=1)
        assert original == original_copy

    def test_fewer_candidates_than_top_n(self):
        r = PassthroughReranker()
        candidates = [_candidate("a", 0.9)]
        result = r.rerank("query", candidates, top_n=5)
        assert len(result) == 1


class TestBuildReranker:
    def test_passthrough_factory(self):
        r = build_reranker({"provider": "passthrough"})
        assert isinstance(r, PassthroughReranker)

    def test_default_is_passthrough(self):
        r = build_reranker({})
        assert isinstance(r, PassthroughReranker)

    def test_unknown_provider_raises(self):
        with pytest.raises(ValueError, match="unknown reranker provider"):
            build_reranker({"provider": "unicorn"})
