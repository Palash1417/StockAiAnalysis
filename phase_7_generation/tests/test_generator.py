"""Tests for phase_7_generation.generator — Generator class + _parse_response."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_6_retrieval.models import CandidateChunk
from phase_7_generation.generator import Generator, _parse_response, build_generator
from phase_7_generation.models import GenerationRequest, GenerationResponse

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

URL_001 = "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth"
URL_002 = "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth"
URL_003 = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"


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


def _mock_client(response_json: dict) -> MagicMock:
    """Return a mock Groq client that yields response_json as the completion content."""
    content = json.dumps(response_json)
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    completion = SimpleNamespace(choices=[choice])
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


def _good_response(chunk_id: str = "src_001#fact#expense_ratio") -> dict:
    return {
        "answer": (
            "The expense ratio of Nippon India Taiwan Equity Fund Direct - Growth is 0.67%. "
            "Last updated from sources: 2026-04-20"
        ),
        "citation_url": URL_001,
        "last_updated": "2026-04-20",
        "confidence": 0.92,
        "used_chunk_ids": [chunk_id],
    }


# ---------------------------------------------------------------------------
# Generator.generate — happy path
# ---------------------------------------------------------------------------

class TestGeneratorHappyPath:
    def _gen(self, response: dict) -> tuple[Generator, GenerationRequest]:
        client = _mock_client(response)
        gen = Generator(client=client, model="llama-3.3-70b-versatile", temperature=0.1)
        req = GenerationRequest(query="What is the expense ratio?", candidates=[_chunk()])
        return gen, req

    def test_returns_generation_response(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert isinstance(result, GenerationResponse)

    def test_answer_populated(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert "0.67%" in result.answer

    def test_citation_url_correct(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert result.citation_url == URL_001

    def test_confidence_correct(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert result.confidence == pytest.approx(0.92)

    def test_used_chunk_ids_populated(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert "src_001#fact#expense_ratio" in result.used_chunk_ids

    def test_is_sufficient_true(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert result.is_sufficient is True

    def test_sentinel_none(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert result.sentinel is None

    def test_last_updated_from_response(self):
        gen, req = self._gen(_good_response())
        result = gen.generate(req)
        assert result.last_updated == "2026-04-20"


# ---------------------------------------------------------------------------
# Insufficient context paths
# ---------------------------------------------------------------------------

class TestInsufficientContext:
    def test_empty_candidates_returns_insufficient(self):
        gen = Generator(client=MagicMock(), model="x")
        req = GenerationRequest(query="q", candidates=[])
        result = gen.generate(req)
        assert result.sentinel == "INSUFFICIENT_CONTEXT"
        assert result.is_sufficient is False

    def test_below_threshold_returns_insufficient(self):
        gen = Generator(client=MagicMock(), model="x")
        req = GenerationRequest(query="q", candidates=[_chunk()], below_threshold=True)
        result = gen.generate(req)
        assert result.sentinel == "INSUFFICIENT_CONTEXT"

    def test_llm_sentinel_response_returns_insufficient(self):
        client = _mock_client({"sentinel": "INSUFFICIENT_CONTEXT"})
        gen = Generator(client=client, model="x")
        req = GenerationRequest(query="q", candidates=[_chunk()])
        result = gen.generate(req)
        assert result.sentinel == "INSUFFICIENT_CONTEXT"

    def test_insufficient_confidence_zero(self):
        gen = Generator(client=MagicMock(), model="x")
        req = GenerationRequest(query="q", candidates=[])
        result = gen.generate(req)
        assert result.confidence == 0.0

    def test_insufficient_used_chunk_ids_empty(self):
        gen = Generator(client=MagicMock(), model="x")
        req = GenerationRequest(query="q", candidates=[])
        result = gen.generate(req)
        assert result.used_chunk_ids == []


# ---------------------------------------------------------------------------
# Error / fallback paths
# ---------------------------------------------------------------------------

class TestFallbackPaths:
    def test_llm_exception_returns_insufficient(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("API timeout")
        gen = Generator(client=client, model="x")
        req = GenerationRequest(query="q", candidates=[_chunk()])
        result = gen.generate(req)
        assert result.sentinel == "INSUFFICIENT_CONTEXT"

    def test_malformed_json_returns_insufficient(self):
        msg = SimpleNamespace(content="not valid json {{{{")
        choice = SimpleNamespace(message=msg)
        completion = SimpleNamespace(choices=[choice])
        client = MagicMock()
        client.chat.completions.create.return_value = completion
        gen = Generator(client=client, model="x")
        req = GenerationRequest(query="q", candidates=[_chunk()])
        result = gen.generate(req)
        assert result.sentinel == "INSUFFICIENT_CONTEXT"

    def test_empty_answer_raises_then_falls_back(self):
        client = _mock_client({"answer": "", "citation_url": URL_001,
                                "last_updated": "2026-04-20", "confidence": 0.5,
                                "used_chunk_ids": []})
        gen = Generator(client=client, model="x")
        req = GenerationRequest(query="q", candidates=[_chunk()])
        result = gen.generate(req)
        assert result.sentinel == "INSUFFICIENT_CONTEXT"


# ---------------------------------------------------------------------------
# Citation URL validation
# ---------------------------------------------------------------------------

class TestCitationValidation:
    def test_unknown_url_falls_back_to_top_chunk_url(self):
        resp = _good_response()
        resp["citation_url"] = "https://evil.com/phishing"
        candidates = [_chunk(source_url=URL_002)]
        result = _parse_response(json.dumps(resp), candidates)
        assert result.citation_url == URL_002

    def test_known_url_accepted(self):
        for url in (URL_001, URL_002, URL_003):
            resp = _good_response()
            resp["citation_url"] = url
            result = _parse_response(json.dumps(resp), [_chunk(source_url=url)])
            assert result.citation_url == url

    def test_missing_citation_falls_back_to_top_chunk(self):
        resp = _good_response()
        del resp["citation_url"]
        candidates = [_chunk(source_url=URL_003)]
        result = _parse_response(json.dumps(resp), candidates)
        assert result.citation_url == URL_003


# ---------------------------------------------------------------------------
# last_updated derivation
# ---------------------------------------------------------------------------

class TestLastUpdated:
    def test_last_updated_from_response_used_when_present(self):
        resp = _good_response()
        resp["last_updated"] = "2026-01-15"
        result = _parse_response(json.dumps(resp), [_chunk()])
        assert result.last_updated == "2026-01-15"

    def test_last_updated_derived_from_cited_chunk_when_missing(self):
        resp = _good_response()
        resp["last_updated"] = ""
        resp["citation_url"] = URL_001
        chunk = _chunk(source_url=URL_001, last_updated="2025-12-01")
        result = _parse_response(json.dumps(resp), [chunk])
        assert result.last_updated == "2025-12-01"


# ---------------------------------------------------------------------------
# Confidence clamping
# ---------------------------------------------------------------------------

class TestConfidenceClamping:
    def test_confidence_above_1_clamped(self):
        resp = _good_response()
        resp["confidence"] = 5.0
        result = _parse_response(json.dumps(resp), [_chunk()])
        assert result.confidence == 1.0

    def test_confidence_below_0_clamped(self):
        resp = _good_response()
        resp["confidence"] = -0.5
        result = _parse_response(json.dumps(resp), [_chunk()])
        assert result.confidence == 0.0

    def test_confidence_defaults_to_0_5_when_missing(self):
        resp = _good_response()
        del resp["confidence"]
        result = _parse_response(json.dumps(resp), [_chunk()])
        assert result.confidence == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# GenerationResponse helpers
# ---------------------------------------------------------------------------

class TestGenerationResponseHelpers:
    def test_to_dict_has_required_keys(self):
        resp = GenerationResponse(
            answer="test", citation_url=URL_001, last_updated="2026-04-20",
            confidence=0.9, used_chunk_ids=["c1"],
        )
        d = resp.to_dict()
        for key in ("answer", "citation_url", "last_updated", "confidence", "used_chunk_ids"):
            assert key in d

    def test_to_dict_sentinel_included_when_set(self):
        resp = GenerationResponse(
            answer="x", citation_url=URL_001, last_updated="",
            confidence=0.0, used_chunk_ids=[], sentinel="INSUFFICIENT_CONTEXT",
        )
        assert resp.to_dict()["sentinel"] == "INSUFFICIENT_CONTEXT"

    def test_to_dict_sentinel_absent_when_none(self):
        resp = GenerationResponse(
            answer="x", citation_url=URL_001, last_updated="2026-04-20",
            confidence=0.8, used_chunk_ids=[],
        )
        assert "sentinel" not in resp.to_dict()

    def test_is_sufficient_false_for_sentinel(self):
        resp = GenerationResponse(
            answer="x", citation_url="", last_updated="",
            confidence=0.0, used_chunk_ids=[], sentinel="INSUFFICIENT_CONTEXT",
        )
        assert resp.is_sufficient is False

    def test_is_sufficient_true_without_sentinel(self):
        resp = GenerationResponse(
            answer="x", citation_url=URL_001, last_updated="2026-04-20",
            confidence=0.9, used_chunk_ids=[],
        )
        assert resp.is_sufficient is True


# ---------------------------------------------------------------------------
# build_generator
# ---------------------------------------------------------------------------

class TestBuildGenerator:
    def test_returns_generator_instance(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            gen = build_generator({"generation": {"model": "llama-3.3-70b-versatile"}})
        assert isinstance(gen, Generator)

    def test_model_name_propagated(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            gen = build_generator({"generation": {"model": "custom-model", "temperature": 0.0}})
        assert gen._model == "custom-model"

    def test_temperature_propagated(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            gen = build_generator({"generation": {"temperature": 0.2}})
        assert gen._temperature == pytest.approx(0.2)
