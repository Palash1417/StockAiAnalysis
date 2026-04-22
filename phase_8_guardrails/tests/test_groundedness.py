import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_8_guardrails.groundedness import GroundednessChecker, build_groundedness_checker


def _mock_client(response: dict) -> MagicMock:
    content = json.dumps(response)
    msg = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=msg)
    completion = SimpleNamespace(choices=[choice])
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


def _candidate(text: str = "The expense ratio is 0.67%."):
    return SimpleNamespace(text=text)


class TestPassthrough:
    def test_no_client_always_grounded(self):
        checker = GroundednessChecker(client=None)
        r = checker.check("q", "answer", [_candidate()])
        assert r.grounded
        assert r.score == 1.0
        assert r.reason == "passthrough"

    def test_empty_candidates_passthrough(self):
        client = _mock_client({"grounded": True, "score": 1.0, "reason": "ok"})
        checker = GroundednessChecker(client=client)
        r = checker.check("q", "answer", [])
        assert r.grounded


class TestLLMGrounded:
    def test_grounded_true_passes(self):
        client = _mock_client({"grounded": True, "score": 0.95, "reason": "Supported."})
        checker = GroundednessChecker(client=client, threshold=0.7)
        r = checker.check("q", "The expense ratio is 0.67%.", [_candidate()])
        assert r.grounded
        assert r.score == pytest.approx(0.95)

    def test_low_score_fails(self):
        client = _mock_client({"grounded": False, "score": 0.4, "reason": "Unsupported claim."})
        checker = GroundednessChecker(client=client, threshold=0.7)
        r = checker.check("q", "answer", [_candidate()])
        assert not r.grounded
        assert r.score == pytest.approx(0.4)

    def test_score_above_threshold_with_grounded_true(self):
        client = _mock_client({"grounded": True, "score": 0.8, "reason": "ok"})
        checker = GroundednessChecker(client=client, threshold=0.7)
        r = checker.check("q", "ans", [_candidate()])
        assert r.grounded


class TestErrorHandling:
    def test_llm_exception_passthrough(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = RuntimeError("timeout")
        checker = GroundednessChecker(client=client, threshold=0.7)
        r = checker.check("q", "answer", [_candidate()])
        assert r.grounded
        assert r.reason == "error_passthrough"

    def test_build_factory_disabled(self):
        checker = build_groundedness_checker({"enabled": False})
        assert checker._client is None
