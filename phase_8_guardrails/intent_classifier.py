"""Intent classifier — §8.1 step 2.

Labels a user query as one of:
  FACTUAL          → proceed to retrieval
  ADVISORY         → refuse with AMFI/SEBI educational link
  PERFORMANCE_CALC → redirect to scheme Groww page (no computed returns)
  OUT_OF_SCOPE     → polite refusal

Two modes:
  - Rule-based (default): fast, no network, covers the clear cases.
  - LLM-backed (optional): Groq single call; falls back to rules on error.

build_intent_classifier(config) → IntentClassifier
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .models import Intent, IntentResult

log = logging.getLogger(__name__)

# Schemes in corpus (lowercase for matching)
_KNOWN_SCHEMES = {
    "nippon india taiwan equity fund",
    "nippon taiwan",
    "bandhan small cap fund",
    "bandhan small cap",
    "hdfc mid cap fund",
    "hdfc mid cap",
    "hdfc midcap",
}

# Advisory patterns — user is asking for a recommendation or opinion
_ADVISORY_PATTERNS = re.compile(
    r"\b("
    r"should i|should i invest|should i buy|should i put"
    r"|recommend|i recommend|would recommend"
    r"|advise|advice|suggestion|suggest"
    r"|which is better|which fund is better|better fund"
    r"|best fund|best option|good fund|good investment"
    r"|worth investing|worth it|is it good|is it safe"
    r"|suitable for me|right for me|right for my"
    r"|compare funds|which one should"
    r")\b",
    re.IGNORECASE,
)

# Performance / return-calculation patterns
_PERFORMANCE_PATTERNS = re.compile(
    r"\b("
    r"return|returns|how much will i get|how much will i earn"
    r"|cagr|xirr|absolute return|annualized return"
    r"|performance|outperform|underperform|beat the market"
    r"|past performance|historical performance|past returns"
    r"|how has .{0,30} performed|how is .{0,30} performing"
    r")\b",
    re.IGNORECASE,
)

# Out-of-scope: clearly non-MF topics or funds not in corpus.
# We flag queries that mention a *named fund* or *fund house* other than our 3.
_NAMED_FUND_RE = re.compile(
    r"\b("
    r"sbi|icici|axis|kotak|mirae|parag parikh|ppfas|uti|dsp|franklin|tata"
    r"|nifty 50 index|nifty next 50|sensex fund|large cap fund|flexi cap"
    r"|motilal|quant|whiteoak"
    r")\b",
    re.IGNORECASE,
)

# Clearly non-financial topic indicators
_NON_MF_PATTERNS = re.compile(
    r"\b("
    r"cricket|football|weather|recipe|movie|song|news|politics|health"
    r"|covid|hospital|election|cricket|ipl|stock market|equity share"
    r"|cryptocurrency|bitcoin|ethereum|forex|gold etf|sgb|fd|fixed deposit"
    r"|ppf|nps|insurance|term plan|ulip"
    r")\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "You are an intent classifier for a Mutual Fund FAQ assistant. "
    "Classify the user query into exactly ONE of these intents:\n"
    "  FACTUAL         — factual question about a mutual fund scheme (expense ratio, exit load, SIP, etc.)\n"
    "  ADVISORY        — asking for investment advice, recommendation, or opinion\n"
    "  PERFORMANCE_CALC — asking to compute, compare, or explain historical returns\n"
    "  OUT_OF_SCOPE    — unrelated topic or fund not in the knowledge base\n\n"
    "Return ONLY a JSON object: {\"intent\": \"<INTENT>\", \"confidence\": <0.0-1.0>}\n"
    "No explanation, no extra text."
)


def _rule_based(query: str) -> IntentResult:
    """Fast rule-based classification."""
    if _ADVISORY_PATTERNS.search(query):
        return IntentResult(intent=Intent.ADVISORY, confidence=0.9)

    if _PERFORMANCE_PATTERNS.search(query):
        return IntentResult(intent=Intent.PERFORMANCE_CALC, confidence=0.9)

    # Check for known out-of-scope signals
    q_lower = query.lower()
    if _NON_MF_PATTERNS.search(query):
        return IntentResult(intent=Intent.OUT_OF_SCOPE, confidence=0.85)

    # Query mentions a named fund/AMC not in our corpus
    if _NAMED_FUND_RE.search(query):
        # Only flag OUT_OF_SCOPE if none of our known schemes appear
        in_corpus = any(s in q_lower for s in _KNOWN_SCHEMES)
        if not in_corpus:
            return IntentResult(intent=Intent.OUT_OF_SCOPE, confidence=0.8)

    return IntentResult(intent=Intent.FACTUAL, confidence=0.8)


class IntentClassifier:
    """Classify query intent; optionally uses Groq for ambiguous cases."""

    def __init__(self, client: Any = None, model: str = "llama-3.3-70b-versatile"):
        self._client = client
        self._model = model

    def classify(self, query: str) -> IntentResult:
        if self._client is None:
            return _rule_based(query)
        try:
            return self._llm_classify(query)
        except Exception as exc:
            log.warning("intent LLM call failed (%s) — rule-based fallback", exc)
            return _rule_based(query)

    def _llm_classify(self, query: str) -> IntentResult:
        import json

        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=64,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        intent = Intent(data["intent"])
        confidence = float(data.get("confidence", 0.9))
        return IntentResult(intent=intent, confidence=confidence)


def build_intent_classifier(config: dict[str, Any]) -> IntentClassifier:
    """Factory. use_llm=False (default) → rule-based only."""
    if not config.get("use_llm", False):
        return IntentClassifier(client=None)
    try:
        import groq  # type: ignore
        client = groq.Groq()
        return IntentClassifier(client=client, model=config.get("model", "llama-3.3-70b-versatile"))
    except Exception:
        log.warning("groq unavailable; using rule-based intent classifier")
        return IntentClassifier(client=None)
