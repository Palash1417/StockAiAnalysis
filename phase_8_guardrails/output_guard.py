"""Output guard — §8.2: post-generation checks.

Pipeline (in order):
  1. Advice detector  — block if answer contains advisory language
  2. Length enforcer  — truncate to ≤ max_sentences (default 3)
  3. Citation validator — citation_url must be in the known source registry
  4. Groundedness     — LLM-as-judge (optional, disabled by default)

Returns OutputGuardResult. passed=False means the answer must be replaced
by a refusal before returning to the user.
"""
from __future__ import annotations

from typing import Any

from . import advice_detector as _adv
from . import length_enforcer as _len
from .groundedness import GroundednessChecker
from .models import OutputGuardResult

_KNOWN_SOURCE_URLS = {
    "https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth",
    "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
    "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
}


class OutputGuard:
    def __init__(
        self,
        groundedness: GroundednessChecker,
        max_sentences: int = 3,
    ):
        self._groundedness = groundedness
        self._max_sentences = max_sentences

    def check(
        self,
        query: str,
        response: Any,          # GenerationResponse
        candidates: list[Any],  # list[CandidateChunk]
    ) -> OutputGuardResult:
        issues: list[str] = []
        answer: str = response.answer

        # 1. Advice detector
        advice = _adv.check(answer)
        if advice.detected:
            issues.append(f"advisory_language:{','.join(advice.flagged_phrases)}")
            return OutputGuardResult(passed=False, issues=issues)

        # 2. Length enforcer
        enforced = _len.enforce(answer, self._max_sentences)
        if enforced != answer:
            issues.append("answer_truncated")
        answer = enforced

        # 3. Citation validator
        if response.citation_url not in _KNOWN_SOURCE_URLS:
            issues.append("citation_url_invalid")
            return OutputGuardResult(passed=False, issues=issues)

        # 4. Groundedness (no-op passthrough when disabled)
        g = self._groundedness.check(query, answer, candidates)
        if not g.grounded:
            issues.append(f"not_grounded:score={g.score:.2f}")
            return OutputGuardResult(passed=False, issues=issues)

        return OutputGuardResult(passed=True, issues=issues, sanitized_answer=answer)


def build_output_guard(config: dict[str, Any]) -> OutputGuard:
    from .groundedness import build_groundedness_checker
    groundedness = build_groundedness_checker(config.get("groundedness", {}))
    max_sentences = int(config.get("length", {}).get("max_sentences", 3))
    return OutputGuard(groundedness=groundedness, max_sentences=max_sentences)
