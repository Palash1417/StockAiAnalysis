"""Router tests — FastAPI endpoints with a mocked RAGPipeline."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from phase_9_api.router import router
from phase_9_api.session_store import SQLiteSessionStore
from phase_9_api.thread_manager import ThreadManager
from phase_9_api.models import ChatResponse


URL_001 = "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth"


def _make_app(pipeline=None) -> FastAPI:
    """Build a minimal FastAPI test app with mocked state."""
    app = FastAPI()
    store = SQLiteSessionStore(db_path=":memory:")
    app.state.thread_manager = ThreadManager(store=store)
    app.state.pipeline = pipeline or _mock_pipeline()
    app.include_router(router)
    return app


def _mock_pipeline(answer: str = "The expense ratio is 0.67%.") -> MagicMock:
    pipeline = MagicMock()

    async def _run(thread_id, query, thread_history):
        return ChatResponse(
            thread_id=thread_id,
            answer=answer,
            citation_url=URL_001,
            last_updated="2026-04-21",
            confidence=0.9,
            used_chunk_ids=["src_001#fact#expense_ratio"],
        )

    pipeline.run = _run
    return pipeline


@pytest.fixture
def client():
    return TestClient(_make_app())


class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestThreadCRUD:
    def test_create_thread(self, client):
        r = client.post("/threads")
        assert r.status_code == 201
        data = r.json()
        assert "thread_id" in data
        assert data["thread_id"]

    def test_get_thread(self, client):
        tid = client.post("/threads").json()["thread_id"]
        r = client.get(f"/threads/{tid}")
        assert r.status_code == 200
        assert r.json()["thread_id"] == tid

    def test_get_missing_thread_404(self, client):
        r = client.get("/threads/does-not-exist")
        assert r.status_code == 404

    def test_list_threads_empty(self, client):
        r = client.get("/threads")
        assert r.status_code == 200
        assert r.json() == []

    def test_list_threads_after_create(self, client):
        client.post("/threads")
        r = client.get("/threads")
        assert len(r.json()) == 1

    def test_delete_thread(self, client):
        tid = client.post("/threads").json()["thread_id"]
        r = client.delete(f"/threads/{tid}")
        assert r.status_code == 204
        assert client.get(f"/threads/{tid}").status_code == 404

    def test_delete_missing_thread_404(self, client):
        r = client.delete("/threads/nonexistent")
        assert r.status_code == 404


class TestChat:
    def test_chat_returns_answer(self, client):
        tid = client.post("/threads").json()["thread_id"]
        r = client.post(f"/threads/{tid}/chat", json={"query": "What is expense ratio?"})
        assert r.status_code == 200
        data = r.json()
        assert data["answer"] == "The expense ratio is 0.67%."
        assert data["citation_url"] == URL_001

    def test_chat_persists_messages(self, client):
        tid = client.post("/threads").json()["thread_id"]
        client.post(f"/threads/{tid}/chat", json={"query": "What is expense ratio?"})
        thread = client.get(f"/threads/{tid}").json()
        assert len(thread["messages"]) == 2   # user + assistant
        assert thread["messages"][0]["role"] == "user"
        assert thread["messages"][1]["role"] == "assistant"

    def test_chat_missing_thread_404(self, client):
        r = client.post("/threads/bad-id/chat", json={"query": "hello"})
        assert r.status_code == 404

    def test_chat_empty_query_422(self, client):
        tid = client.post("/threads").json()["thread_id"]
        r = client.post(f"/threads/{tid}/chat", json={"query": ""})
        assert r.status_code == 422

    def test_chat_refusal_pipeline(self, client):
        refusal_pipeline = MagicMock()

        async def _run(thread_id, query, thread_history):
            return ChatResponse(
                thread_id=thread_id,
                answer="I can only answer factual questions.",
                citation_url="https://www.amfiindia.com/investor-corner",
                last_updated="",
                confidence=0.0,
                sentinel="REFUSAL",
                refusal=True,
            )

        refusal_pipeline.run = _run
        app = _make_app(pipeline=refusal_pipeline)
        c = TestClient(app)
        tid = c.post("/threads").json()["thread_id"]
        r = c.post(f"/threads/{tid}/chat", json={"query": "Should I invest?"})
        assert r.status_code == 200
        data = r.json()
        assert data["refusal"] is True

    def test_thread_id_in_response(self, client):
        tid = client.post("/threads").json()["thread_id"]
        r = client.post(f"/threads/{tid}/chat", json={"query": "What is exit load?"})
        assert r.json()["thread_id"] == tid

    def test_multiple_messages_in_thread(self, client):
        tid = client.post("/threads").json()["thread_id"]
        client.post(f"/threads/{tid}/chat", json={"query": "Q1"})
        client.post(f"/threads/{tid}/chat", json={"query": "Q2"})
        thread = client.get(f"/threads/{tid}").json()
        assert len(thread["messages"]) == 4   # 2 user + 2 assistant
