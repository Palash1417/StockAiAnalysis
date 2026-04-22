"""Prompt-injection filter — §8.1 step 3.

Detects known jailbreak / instruction-override patterns in user input.
Rule-based; no LLM call needed.
"""
from __future__ import annotations

import re

from .models import InjectionResult

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "instruction_override",
        re.compile(
            r"\b(ignore|disregard|forget|override|bypass)\b.{0,30}"
            r"\b(previous|prior|above|all|any|your|the)\b.{0,20}"
            r"\b(instructions?|prompt|rules?|constraints?|guidelines?|context)\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "persona_override",
        re.compile(
            r"\b(you are now|act as|pretend (to be|you are)|roleplay as|"
            r"simulate being|imagine you are|behave as)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "system_prompt_leak",
        re.compile(
            r"(^|\n)\s*system\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
    ),
    (
        "jailbreak_keyword",
        re.compile(
            r"\b(jailbreak|DAN mode|do anything now|unrestricted mode|"
            r"developer mode|god mode|no restrictions|no limits)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "new_instructions",
        re.compile(
            r"\b(new instructions?|updated instructions?|revised instructions?)\s*:",
            re.IGNORECASE,
        ),
    ),
]


def check(text: str) -> InjectionResult:
    """Return InjectionResult(detected=True, reason=<label>) on first match."""
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            return InjectionResult(detected=True, reason=label)
    return InjectionResult(detected=False)
