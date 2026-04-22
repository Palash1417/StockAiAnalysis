"""Phase 8 — Guardrails data models."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    FACTUAL = "FACTUAL"
    ADVISORY = "ADVISORY"
    PERFORMANCE_CALC = "PERFORMANCE_CALC"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


@dataclass
class PIIResult:
    found: bool
    types: list[str]
    scrubbed_text: str


@dataclass
class InjectionResult:
    detected: bool
    reason: str = ""


@dataclass
class IntentResult:
    intent: Intent
    confidence: float = 1.0


@dataclass
class AdviceResult:
    detected: bool
    flagged_phrases: list[str] = field(default_factory=list)


@dataclass
class GroundednessResult:
    grounded: bool
    score: float = 1.0
    reason: str = ""


@dataclass
class InputGuardResult:
    """Result of all pre-retrieval checks."""
    passed: bool
    intent: Intent | None = None
    pii_found: bool = False
    pii_types: list[str] = field(default_factory=list)
    injection_detected: bool = False
    refusal_response: str | None = None
    scrubbed_query: str | None = None


@dataclass
class OutputGuardResult:
    """Result of all post-generation checks."""
    passed: bool
    issues: list[str] = field(default_factory=list)
    sanitized_answer: str | None = None
