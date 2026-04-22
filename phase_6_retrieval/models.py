"""Phase 6 retrieval data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RetrievalQuery:
    text: str
    original_text: str | None = None
    scheme_filter: str | None = None
    category_filter: str | None = None
    corpus_version: str | None = None  # None = use live pointer
    top_k_dense: int = 20
    top_k_sparse: int = 20
    top_k_rrf: int = 15
    top_n_rerank: int = 5
    score_threshold: float = 0.35


@dataclass
class CandidateChunk:
    chunk_id: str
    source_id: str
    scheme: str | None
    section: str | None
    segment_type: str
    text: str
    source_url: str
    last_updated: str
    score: float
    dense_score: float | None = None
    sparse_score: float | None = None
    rrf_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "source_id": self.source_id,
            "scheme": self.scheme,
            "section": self.section,
            "segment_type": self.segment_type,
            "text": self.text,
            "source_url": self.source_url,
            "last_updated": self.last_updated,
            "score": self.score,
        }


@dataclass
class RetrievalResult:
    query: str
    rewritten_query: str | None
    candidates: list[CandidateChunk]
    corpus_version: str
    retrieved_at: str
    below_threshold: bool = False

    def top(self) -> CandidateChunk | None:
        return self.candidates[0] if self.candidates else None
