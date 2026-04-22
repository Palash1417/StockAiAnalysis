"""Tests for phase_7_generation.prompt — context formatter + message builder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_6_retrieval.models import CandidateChunk
from phase_7_generation.models import GenerationRequest
from phase_7_generation.prompt import SYSTEM_PROMPT, build_messages, format_context

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

URL_001 = "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth"
URL_002 = "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth"


def _chunk(
    chunk_id: str = "src_001#fact#expense_ratio",
    source_id: str = "src_001",
    scheme: str = "Nippon India Taiwan Equity Fund Direct - Growth",
    segment_type: str = "fact_table",
    text: str = "Nippon India Taiwan Equity Fund Direct - Growth has an expense ratio of 0.67%.",
    source_url: str = URL_001,
    last_updated: str = "2026-04-20",
    score: float = 0.92,
) -> CandidateChunk:
    return CandidateChunk(
        chunk_id=chunk_id,
        source_id=source_id,
        scheme=scheme,
        section=None,
        segment_type=segment_type,
        text=text,
        source_url=source_url,
        last_updated=last_updated,
        score=score,
    )


# ---------------------------------------------------------------------------
# format_context
# ---------------------------------------------------------------------------

class TestFormatContext:
    def test_empty_returns_no_chunks_marker(self):
        out = format_context([])
        assert "(no chunks retrieved)" in out
        assert "<context>" in out

    def test_single_chunk_contains_chunk_id(self):
        c = _chunk()
        out = format_context([c])
        assert "src_001#fact#expense_ratio" in out

    def test_single_chunk_contains_text(self):
        c = _chunk()
        out = format_context([c])
        assert "expense ratio of 0.67%" in out

    def test_single_chunk_contains_source_url(self):
        c = _chunk()
        out = format_context([c])
        assert URL_001 in out

    def test_single_chunk_contains_last_updated(self):
        c = _chunk()
        out = format_context([c])
        assert "2026-04-20" in out

    def test_multiple_chunks_numbered(self):
        chunks = [_chunk(chunk_id=f"src_00{i}#fact#x", score=0.9 - i * 0.1) for i in range(1, 4)]
        out = format_context(chunks)
        assert "[1]" in out
        assert "[2]" in out
        assert "[3]" in out

    def test_wrapped_in_context_tags(self):
        out = format_context([_chunk()])
        assert out.startswith("<context>")
        assert out.endswith("</context>")

    def test_score_included(self):
        c = _chunk(score=0.856)
        out = format_context([c])
        assert "0.856" in out


# ---------------------------------------------------------------------------
# build_messages
# ---------------------------------------------------------------------------

class TestBuildMessages:
    def _request(self, **kw) -> GenerationRequest:
        return GenerationRequest(
            query=kw.get("query", "What is the expense ratio of Nippon Taiwan fund?"),
            candidates=kw.get("candidates", [_chunk()]),
            thread_history=kw.get("thread_history", []),
        )

    def test_first_message_is_system(self):
        msgs = build_messages(self._request())
        assert msgs[0]["role"] == "system"

    def test_system_content_is_system_prompt(self):
        msgs = build_messages(self._request())
        assert msgs[0]["content"] == SYSTEM_PROMPT

    def test_last_message_is_user(self):
        msgs = build_messages(self._request())
        assert msgs[-1]["role"] == "user"

    def test_user_message_contains_query(self):
        msgs = build_messages(self._request(query="What is exit load?"))
        assert "What is exit load?" in msgs[-1]["content"]

    def test_user_message_contains_context(self):
        msgs = build_messages(self._request())
        assert "<context>" in msgs[-1]["content"]
        assert "expense ratio of 0.67%" in msgs[-1]["content"]

    def test_history_injected_before_user_turn(self):
        history = [
            {"role": "user", "content": "What is the min SIP?"},
            {"role": "assistant", "content": "The minimum SIP is ₹100."},
        ]
        req = self._request(thread_history=history)
        msgs = build_messages(req)
        # system, history[0], history[1], user
        assert len(msgs) == 4
        assert msgs[1]["role"] == "user"
        assert msgs[2]["role"] == "assistant"

    def test_history_capped_at_8_messages(self):
        history = [{"role": "user", "content": f"q{i}"} for i in range(20)]
        req = self._request(thread_history=history)
        msgs = build_messages(req)
        # system + 8 history + user = 10
        assert len(msgs) == 10

    def test_empty_history_gives_two_messages(self):
        msgs = build_messages(self._request(thread_history=[]))
        assert len(msgs) == 2  # system + user
