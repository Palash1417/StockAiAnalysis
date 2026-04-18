from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

SegmentType = Literal["fact_table", "section_text", "table"]


@dataclass
class ParsedDocument:
    """Input contract: what the scraper hands us via DocumentChangedEvent."""
    source_id: str
    scheme: str
    source_url: str
    last_updated: str  # ISO-8601 date
    facts: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    scheme: str
    section: str | None
    segment_type: SegmentType
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    # Populated by hasher
    normalized_text: str | None = None
    chunk_hash: str | None = None


@dataclass
class EmbeddedChunk:
    chunk: Chunk
    embedding: list[float]
    embed_model_id: str
    dim: int


@dataclass
class UpsertReport:
    corpus_version: str
    chunks_upserted: int
    chunks_soft_deleted: int
    fact_kv_writes: int
    bm25_writes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "corpus_version": self.corpus_version,
            "chunks_upserted": self.chunks_upserted,
            "chunks_soft_deleted": self.chunks_soft_deleted,
            "fact_kv_writes": self.fact_kv_writes,
            "bm25_writes": self.bm25_writes,
        }
