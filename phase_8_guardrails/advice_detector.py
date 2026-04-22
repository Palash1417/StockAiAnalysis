"""Advice detector — §8.2 step 3.

Detects advisory language in *generated answers* (output guard).
Looks for phrases that indicate the assistant is recommending, suggesting,
or opining rather than stating facts.
"""
from __future__ import annotations

import re

from .models import AdviceResult

# Phrases that constitute advisory output from the model
_ADVICE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("i_recommend", re.compile(r"\bI\s+recommend\b", re.IGNORECASE)),
    ("i_suggest", re.compile(r"\bI\s+suggest\b", re.IGNORECASE)),
    ("i_advise", re.compile(r"\bI\s+advise\b", re.IGNORECASE)),
    ("you_should_invest", re.compile(r"\byou\s+should\s+invest\b", re.IGNORECASE)),
    ("would_recommend", re.compile(r"\bwould\s+recommend\b", re.IGNORECASE)),
    ("better_than", re.compile(r"\bbetter\s+than\b.{0,30}\bfund\b", re.IGNORECASE | re.DOTALL)),
    ("best_fund", re.compile(r"\bbest\s+fund\b", re.IGNORECASE)),
    ("worth_investing", re.compile(r"\bworth\s+investing\b", re.IGNORECASE)),
    ("consider_investing", re.compile(r"\bconsider\s+investing\b", re.IGNORECASE)),
    ("suitable_for_you", re.compile(r"\bsuitable\s+for\s+you\b", re.IGNORECASE)),
    ("go_with", re.compile(r"\bgo\s+with\s+(this|the)\s+fund\b", re.IGNORECASE)),
]


def check(text: str) -> AdviceResult:
    """Return AdviceResult(detected=True, flagged_phrases=[...]) if advisory language found."""
    flagged: list[str] = []
    for label, pattern in _ADVICE_PATTERNS:
        if pattern.search(text):
            flagged.append(label)
    return AdviceResult(detected=bool(flagged), flagged_phrases=flagged)
