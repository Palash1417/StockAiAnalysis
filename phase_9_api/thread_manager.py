"""Thread manager — CRUD + per-thread async in-flight lock.

The in-flight lock prevents concurrent requests on the same thread from
producing interleaved message history. For multi-instance deployments the
lock would need to be a Redis distributed lock; the interface is the same.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from .models import Message, Thread, ThreadMetadata, ThreadSummary
from .session_store import SessionStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ThreadManager:
    def __init__(self, store: SessionStore):
        self._store = store
        self._locks: dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Thread lifecycle
    # ------------------------------------------------------------------

    def create_thread(self) -> Thread:
        thread = Thread(
            thread_id=str(uuid.uuid4()),
            created_at=_now_iso(),
        )
        self._store.save(thread)
        return thread

    def get_thread(self, thread_id: str) -> Thread | None:
        return self._store.get(thread_id)

    def delete_thread(self, thread_id: str) -> None:
        self._store.delete(thread_id)

    def list_summaries(self) -> list[ThreadSummary]:
        threads = self._store.list_all()
        summaries = []
        for t in threads:
            first_q = next(
                (m.content for m in t.messages if m.role == "user"), None
            )
            preview = (first_q[:50] + "…") if first_q and len(first_q) > 50 else first_q
            summaries.append(
                ThreadSummary(
                    thread_id=t.thread_id,
                    created_at=t.created_at,
                    message_count=len(t.messages),
                    preview=preview,
                )
            )
        return summaries

    # ------------------------------------------------------------------
    # Message management
    # ------------------------------------------------------------------

    def append_message(self, thread_id: str, message: Message) -> Thread:
        thread = self._store.get(thread_id)
        if thread is None:
            raise KeyError(f"Thread {thread_id!r} not found")
        thread.messages.append(message)
        self._store.save(thread)
        return thread

    def get_last_n_turns(
        self, thread_id: str, n: int = 4
    ) -> list[dict[str, str]]:
        """Return the last *n* user+assistant turn pairs as message dicts.

        Only `role` and `content` are included (suitable for passing to the
        query rewriter as conversation history — §9.2).
        """
        thread = self._store.get(thread_id)
        if thread is None:
            return []
        msgs = thread.messages
        # Each turn = 1 user + 1 assistant message; last n turns = last 2n messages
        last = msgs[-(n * 2):]
        return [{"role": m.role, "content": m.content} for m in last]

    def update_metadata(self, thread_id: str, **kwargs: str) -> None:
        thread = self._store.get(thread_id)
        if thread is None:
            return
        for k, v in kwargs.items():
            setattr(thread.metadata, k, v)
        self._store.save(thread)

    # ------------------------------------------------------------------
    # Per-thread in-flight lock (§9.2)
    # ------------------------------------------------------------------

    @asynccontextmanager
    async def request_lock(self, thread_id: str):
        """Async context manager — acquires the per-thread lock.

        Prevents two concurrent requests on the same thread from producing
        interleaved message history.
        """
        async with self._meta_lock:
            if thread_id not in self._locks:
                self._locks[thread_id] = asyncio.Lock()
            lock = self._locks[thread_id]
        async with lock:
            yield
