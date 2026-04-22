"""Tests for RRF fusion — pure logic, no external dependencies."""
from __future__ import annotations

import pytest

from phase_6_retrieval.fusion import rrf_fuse


def _doc(chunk_id: str, score: float = 1.0, **kwargs) -> dict:
    return {
        "chunk_id": chunk_id,
        "source_id": "src_001",
        "scheme": "Test Fund",
        "section": None,
        "segment_type": "fact_table",
        "text": f"text for {chunk_id}",
        "source_url": "https://example.com",
        "last_updated": "2026-04-19",
        "score": score,
        **kwargs,
    }


class TestRRFEmpty:
    def test_both_empty(self):
        assert rrf_fuse([], []) == []

    def test_dense_empty(self):
        sparse = [_doc("a", 0.9), _doc("b", 0.5)]
        result = rrf_fuse([], sparse, top_k=5)
        assert [r["chunk_id"] for r in result] == ["a", "b"]

    def test_sparse_empty(self):
        dense = [_doc("x", 0.8), _doc("y", 0.3)]
        result = rrf_fuse(dense, [], top_k=5)
        assert [r["chunk_id"] for r in result] == ["x", "y"]


class TestRRFScoring:
    def test_chunk_in_both_lists_ranks_higher(self):
        # "c" is #1 in sparse, #3 in dense; "a" is #1 in dense only
        dense = [_doc("a"), _doc("b"), _doc("c")]
        sparse = [_doc("c"), _doc("d")]
        result = rrf_fuse(dense, sparse, k=60, top_k=10)
        ids = [r["chunk_id"] for r in result]
        # c appears in both lists → should rank above a (dense only)
        assert ids.index("c") < ids.index("a")

    def test_rrf_score_monotone_decreasing(self):
        dense = [_doc(f"d{i}") for i in range(5)]
        sparse = [_doc(f"s{i}") for i in range(5)]
        result = rrf_fuse(dense, sparse, k=60, top_k=10)
        scores = [r["rrf_score"] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_rrf_score_additive(self):
        # a chunk in both lists gets a higher score than one in one list
        dense = [_doc("both"), _doc("dense_only")]
        sparse = [_doc("both"), _doc("sparse_only")]
        result = rrf_fuse(dense, sparse, k=60, top_k=10)
        scores = {r["chunk_id"]: r["rrf_score"] for r in result}
        assert scores["both"] > scores["dense_only"]
        assert scores["both"] > scores["sparse_only"]


class TestRRFTopK:
    def test_top_k_respected(self):
        dense = [_doc(f"d{i}") for i in range(10)]
        sparse = [_doc(f"s{i}") for i in range(10)]
        result = rrf_fuse(dense, sparse, top_k=5)
        assert len(result) <= 5

    def test_top_k_zero(self):
        dense = [_doc("a"), _doc("b")]
        result = rrf_fuse(dense, [], top_k=0)
        assert result == []


class TestRRFMetadata:
    def test_metadata_preserved(self):
        dense = [_doc("chunk1", scheme="My Fund", section="Expense Ratio")]
        result = rrf_fuse(dense, [], top_k=5)
        assert result[0]["scheme"] == "My Fund"
        assert result[0]["section"] == "Expense Ratio"
        assert result[0]["source_url"] == "https://example.com"

    def test_dense_score_backfilled(self):
        dense = [_doc("a", score=0.9)]
        result = rrf_fuse(dense, [], top_k=5)
        assert result[0].get("dense_score") == pytest.approx(0.9)

    def test_sparse_score_backfilled_when_in_both(self):
        dense = [_doc("a", score=0.9)]
        sparse = [_doc("a", score=0.5)]
        result = rrf_fuse(dense, sparse, top_k=5)
        assert result[0].get("sparse_score") == pytest.approx(0.5)

    def test_embedding_not_exposed(self):
        dense = [dict(_doc("a"), embedding=[0.1, 0.2, 0.3])]
        result = rrf_fuse(dense, [], top_k=5)
        assert "embedding" not in result[0]

    def test_rrf_score_and_score_fields_set(self):
        dense = [_doc("a")]
        result = rrf_fuse(dense, [], top_k=5)
        assert "rrf_score" in result[0]
        assert result[0]["score"] == result[0]["rrf_score"]
