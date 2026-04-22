"""Phase 7 generation data models — §7.3."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from phase_6_retrieval.models import CandidateChunk  # noqa: F401 — re-exported


@dataclass
class GenerationRequest:
    """Everything the Generator needs to produce one answer."""
    query: str
    candidates: list[CandidateChunk]
    # True when the retriever signalled all scores are below threshold.
    below_threshold: bool = False
    # Last 4 turns as [{"role": "user"|"assistant", "content": "..."}].
    # Injected into the message list for coreference resolution (§9.2).
    thread_history: list[dict[str, str]] = field(default_factory=list)


@dataclass
class GenerationResponse:
    """Structured answer — matches the §7.3 output schema."""
    answer: str
    citation_url: str
    last_updated: str          # ISO-8601 date of the cited source
    confidence: float          # 0.0–1.0 self-assessed by the LLM
    used_chunk_ids: list[str]  # chunk_ids the LLM cited
    sentinel: str | None = None  # "INSUFFICIENT_CONTEXT" or None

    @property
    def is_sufficient(self) -> bool:
        return self.sentinel is None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "answer": self.answer,
            "citation_url": self.citation_url,
            "last_updated": self.last_updated,
            "confidence": self.confidence,
            "used_chunk_ids": self.used_chunk_ids,
        }
        if self.sentinel:
            d["sentinel"] = self.sentinel
        return d


def insufficient_context_response() -> GenerationResponse:
    """Standard refusal when the retriever found nothing useful."""
    return GenerationResponse(
        answer=(
            "I couldn't find this information in the mutual fund sources I have access to. "
            "For general guidance please visit AMFI's investor education page."
        ),
        citation_url="https://www.amfiindia.com/investor-corner",
        last_updated="",
        confidence=0.0,
        used_chunk_ids=[],
        sentinel="INSUFFICIENT_CONTEXT",
    )
