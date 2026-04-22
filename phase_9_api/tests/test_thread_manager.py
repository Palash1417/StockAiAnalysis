import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_9_api.session_store import SQLiteSessionStore
from phase_9_api.thread_manager import ThreadManager
from phase_9_api.models import Message


@pytest.fixture
def mgr():
    store = SQLiteSessionStore(db_path=":memory:")
    return ThreadManager(store=store)


class TestThreadLifecycle:
    def test_create_thread_returns_thread(self, mgr):
        t = mgr.create_thread()
        assert t.thread_id
        assert t.created_at

    def test_created_thread_is_persisted(self, mgr):
        t = mgr.create_thread()
        fetched = mgr.get_thread(t.thread_id)
        assert fetched is not None
        assert fetched.thread_id == t.thread_id

    def test_get_missing_thread_returns_none(self, mgr):
        assert mgr.get_thread("nonexistent") is None

    def test_delete_thread(self, mgr):
        t = mgr.create_thread()
        mgr.delete_thread(t.thread_id)
        assert mgr.get_thread(t.thread_id) is None

    def test_list_summaries_empty(self, mgr):
        assert mgr.list_summaries() == []

    def test_list_summaries_includes_created_thread(self, mgr):
        t = mgr.create_thread()
        summaries = mgr.list_summaries()
        ids = [s.thread_id for s in summaries]
        assert t.thread_id in ids

    def test_summary_preview_from_first_user_message(self, mgr):
        t = mgr.create_thread()
        mgr.append_message(t.thread_id, Message(role="user", content="What is expense ratio?", ts="ts"))
        summaries = mgr.list_summaries()
        s = next(s for s in summaries if s.thread_id == t.thread_id)
        assert s.preview == "What is expense ratio?"


class TestMessageManagement:
    def test_append_message(self, mgr):
        t = mgr.create_thread()
        msg = Message(role="user", content="Hello", ts="ts")
        updated = mgr.append_message(t.thread_id, msg)
        assert len(updated.messages) == 1

    def test_append_to_missing_thread_raises(self, mgr):
        with pytest.raises(KeyError):
            mgr.append_message("bad-id", Message(role="user", content="x", ts="ts"))

    def test_get_last_n_turns_empty_when_no_messages(self, mgr):
        t = mgr.create_thread()
        assert mgr.get_last_n_turns(t.thread_id) == []

    def test_get_last_n_turns_returns_pairs(self, mgr):
        t = mgr.create_thread()
        mgr.append_message(t.thread_id, Message(role="user", content="Q1", ts="ts"))
        mgr.append_message(t.thread_id, Message(role="assistant", content="A1", ts="ts"))
        turns = mgr.get_last_n_turns(t.thread_id, n=4)
        assert len(turns) == 2
        assert turns[0]["role"] == "user"
        assert turns[1]["role"] == "assistant"

    def test_get_last_n_turns_capped(self, mgr):
        t = mgr.create_thread()
        for i in range(10):
            mgr.append_message(t.thread_id, Message(role="user", content=f"Q{i}", ts="ts"))
            mgr.append_message(t.thread_id, Message(role="assistant", content=f"A{i}", ts="ts"))
        turns = mgr.get_last_n_turns(t.thread_id, n=4)
        assert len(turns) == 8   # last 4 pairs = 8 messages


class TestInFlightLock:
    def test_lock_acquired_and_released(self, mgr):
        t = mgr.create_thread()

        async def _run():
            async with mgr.request_lock(t.thread_id):
                pass   # just test it doesn't deadlock

        asyncio.run(_run())

    def test_concurrent_requests_serialised(self, mgr):
        t = mgr.create_thread()
        results = []

        async def _worker(val: int):
            async with mgr.request_lock(t.thread_id):
                await asyncio.sleep(0.01)
                results.append(val)

        async def _run():
            await asyncio.gather(_worker(1), _worker(2), _worker(3))

        asyncio.run(_run())
        assert sorted(results) == [1, 2, 3]
