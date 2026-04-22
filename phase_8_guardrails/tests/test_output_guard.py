import sys
from pathlib import Path
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pytest
from phase_8_guardrails.groundedness import GroundednessChecker
from phase_8_guardrails.output_guard import OutputGuard

URL_001 = "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth"
URL_002 = "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth"
URL_003 = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
URL_BAD = "https://evil.com/phishing"


@dataclass
class FakeResponse:
    answer: str
    citation_url: str


@dataclass
class FakeCandidate:
    text: str = "The expense ratio is 0.67%."


def _passthrough_guard() -> OutputGuard:
    return OutputGuard(groundedness=GroundednessChecker(client=None), max_sentences=3)


def _good_response() -> FakeResponse:
    return FakeResponse(
        answer=(
            "The expense ratio of Nippon India Taiwan Equity Fund Direct - Growth is 0.67%. "
            "Last updated from sources: 2026-04-20."
        ),
        citation_url=URL_001,
    )


class TestHappyPath:
    def test_valid_response_passes(self):
        guard = _passthrough_guard()
        r = guard.check("What is expense ratio?", _good_response(), [FakeCandidate()])
        assert r.passed

    def test_sanitized_answer_returned(self):
        guard = _passthrough_guard()
        r = guard.check("What is expense ratio?", _good_response(), [FakeCandidate()])
        assert r.sanitized_answer is not None

    def test_all_known_urls_accepted(self):
        guard = _passthrough_guard()
        for url in (URL_001, URL_002, URL_003):
            resp = FakeResponse(answer="The expense ratio is 0.67%.", citation_url=url)
            r = guard.check("q", resp, [FakeCandidate()])
            assert r.passed


class TestAdviceBlocking:
    def test_advisory_answer_blocked(self):
        guard = _passthrough_guard()
        resp = FakeResponse(
            answer="I recommend investing in this fund for long-term growth.",
            citation_url=URL_001,
        )
        r = guard.check("q", resp, [FakeCandidate()])
        assert not r.passed
        assert any("advisory_language" in issue for issue in r.issues)


class TestCitationValidation:
    def test_invalid_citation_blocked(self):
        guard = _passthrough_guard()
        resp = FakeResponse(answer="The expense ratio is 0.67%.", citation_url=URL_BAD)
        r = guard.check("q", resp, [FakeCandidate()])
        assert not r.passed
        assert "citation_url_invalid" in r.issues


class TestLengthTruncation:
    def test_four_sentence_answer_truncated(self):
        guard = _passthrough_guard()
        resp = FakeResponse(
            answer="One. Two. Three. Four.",
            citation_url=URL_001,
        )
        r = guard.check("q", resp, [FakeCandidate()])
        assert r.passed
        assert "answer_truncated" in r.issues
        # sanitized_answer should have ≤ 3 sentences
        from phase_8_guardrails.length_enforcer import split_sentences
        assert len(split_sentences(r.sanitized_answer)) <= 3

    def test_within_limit_not_flagged(self):
        guard = _passthrough_guard()
        r = guard.check("q", _good_response(), [FakeCandidate()])
        assert "answer_truncated" not in r.issues


class TestGroundednessBlocking:
    def test_not_grounded_blocks(self):
        from unittest.mock import MagicMock
        from phase_8_guardrails.models import GroundednessResult

        checker = MagicMock()
        checker.check.return_value = GroundednessResult(grounded=False, score=0.3, reason="Unsupported.")
        guard = OutputGuard(groundedness=checker, max_sentences=3)
        r = guard.check("q", _good_response(), [FakeCandidate()])
        assert not r.passed
        assert any("not_grounded" in issue for issue in r.issues)
