"""Phase 9 — Pydantic request/response schemas and thread data model."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    ts: str
    citation_url: str | None = None
    last_updated: str | None = None
    used_chunk_ids: list[str] = Field(default_factory=list)


class ThreadMetadata(BaseModel):
    last_scheme: str | None = None


class Thread(BaseModel):
    thread_id: str
    created_at: str
    messages: list[Message] = Field(default_factory=list)
    metadata: ThreadMetadata = Field(default_factory=ThreadMetadata)


class ThreadSummary(BaseModel):
    thread_id: str
    created_at: str
    message_count: int
    preview: str | None = None   # first user message, truncated


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    thread_id: str
    answer: str
    citation_url: str
    last_updated: str
    confidence: float
    used_chunk_ids: list[str] = Field(default_factory=list)
    sentinel: str | None = None
    refusal: bool = False
