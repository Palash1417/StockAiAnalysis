import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_9_api.session_store import SQLiteSessionStore
from phase_9_api.models import Thread


@pytest.fixture
def store():
    return SQLiteSessionStore(db_path=":memory:")


def _thread(tid: str = "tid-1") -> Thread:
    return Thread(thread_id=tid, created_at="2026-04-21T00:00:00+00:00")


class TestSQLiteSessionStore:
    def test_get_missing_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_save_and_get_roundtrip(self, store):
        t = _thread("abc")
        store.save(t)
        result = store.get("abc")
        assert result is not None
        assert result.thread_id == "abc"

    def test_save_overwrites_existing(self, store):
        t = _thread("abc")
        store.save(t)
        from phase_9_api.models import Message
        t.messages.append(Message(role="user", content="hello", ts="ts"))
        store.save(t)
        result = store.get("abc")
        assert len(result.messages) == 1

    def test_delete_removes_thread(self, store):
        store.save(_thread("x"))
        store.delete("x")
        assert store.get("x") is None

    def test_delete_missing_no_error(self, store):
        store.delete("does-not-exist")   # should not raise

    def test_list_all_empty(self, store):
        assert store.list_all() == []

    def test_list_all_returns_saved_threads(self, store):
        store.save(_thread("a"))
        store.save(_thread("b"))
        threads = store.list_all()
        ids = {t.thread_id for t in threads}
        assert ids == {"a", "b"}

    def test_ttl_expires_old_thread(self):
        store = SQLiteSessionStore(db_path=":memory:", ttl_seconds=0)
        store.save(_thread("old"))
        import time; time.sleep(0.01)
        assert store.get("old") is None

    def test_metadata_preserved(self, store):
        t = _thread("m")
        t.metadata.last_scheme = "HDFC Mid Cap Fund"
        store.save(t)
        result = store.get("m")
        assert result.metadata.last_scheme == "HDFC Mid Cap Fund"

    def test_messages_preserved(self, store):
        from phase_9_api.models import Message
        t = _thread("msgs")
        t.messages.append(Message(role="user", content="What is expense ratio?", ts="ts1"))
        store.save(t)
        result = store.get("msgs")
        assert len(result.messages) == 1
        assert result.messages[0].content == "What is expense ratio?"
