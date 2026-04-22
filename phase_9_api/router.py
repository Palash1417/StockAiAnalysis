"""FastAPI routes — §16 request lifecycle.

Endpoints:
  POST /threads                       → create thread
  GET  /threads                       → list thread summaries
  GET  /threads/{thread_id}           → get thread (full history)
  POST /threads/{thread_id}/chat      → send message, get answer
  DELETE /threads/{thread_id}         → delete thread
  GET  /health                        → liveness probe
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from .models import ChatRequest, ChatResponse, Message, Thread, ThreadSummary

router = APIRouter()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_mgr(request: Request):
    return request.app.state.thread_manager


def _get_pipeline(request: Request):
    return request.app.state.pipeline


# ---------------------------------------------------------------------------
# Thread management
# ---------------------------------------------------------------------------

@router.post("/threads", response_model=Thread, status_code=201)
async def create_thread(request: Request):
    mgr = _get_mgr(request)
    return mgr.create_thread()


@router.get("/threads", response_model=list[ThreadSummary])
async def list_threads(request: Request):
    mgr = _get_mgr(request)
    return mgr.list_summaries()


@router.get("/threads/{thread_id}", response_model=Thread)
async def get_thread(thread_id: str, request: Request):
    mgr = _get_mgr(request)
    thread = mgr.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id!r} not found")
    return thread


@router.delete("/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request):
    mgr = _get_mgr(request)
    if mgr.get_thread(thread_id) is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id!r} not found")
    mgr.delete_thread(thread_id)


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

@router.post("/threads/{thread_id}/chat", response_model=ChatResponse)
async def chat(thread_id: str, body: ChatRequest, request: Request):
    mgr = _get_mgr(request)
    pipeline = _get_pipeline(request)

    thread = mgr.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail=f"Thread {thread_id!r} not found")

    async with mgr.request_lock(thread_id):
        # Append user message
        user_msg = Message(role="user", content=body.query, ts=_now_iso())
        mgr.append_message(thread_id, user_msg)

        # Last 4 turns for query rewrite context (§9.2)
        history = mgr.get_last_n_turns(thread_id, n=4)

        # Run RAG pipeline
        response: ChatResponse = await pipeline.run(
            thread_id=thread_id,
            query=body.query,
            thread_history=history,
        )

        # Append assistant message
        assistant_msg = Message(
            role="assistant",
            content=response.answer,
            ts=_now_iso(),
            citation_url=response.citation_url,
            last_updated=response.last_updated,
            used_chunk_ids=response.used_chunk_ids,
        )
        mgr.append_message(thread_id, assistant_msg)

    return response


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    return {"status": "ok"}
