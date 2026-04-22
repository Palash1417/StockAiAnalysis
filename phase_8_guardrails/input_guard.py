"""Input guard — §8.1: composes PII scrubber + injection filter + intent classifier.

Runs in order:
  1. PII scrubber  → refuse if PII found
  2. Injection filter → refuse if injection detected
  3. Intent classifier → refuse if ADVISORY / PERFORMANCE_CALC / OUT_OF_SCOPE

Returns InputGuardResult. passed=True means the query is safe to proceed.
"""
from __future__ import annotations

from . import injection_filter, pii_scrubber
from .intent_classifier import IntentClassifier
from .models import InputGuardResult, Intent

_PII_REFUSAL = (
    "Your query appears to contain personal information (such as PAN, Aadhaar, "
    "email, or phone number). Please rephrase your question without personal details."
)

_INJECTION_REFUSAL = (
    "Your query contains patterns that cannot be processed. "
    "Please ask a factual question about mutual fund schemes."
)

_ADVISORY_REFUSAL = (
    "I can only share factual information from official mutual fund sources, "
    "so I can't offer investment recommendations or advice. "
    "For general guidance on choosing schemes, see AMFI's investor education: "
    "https://www.amfiindia.com/investor-corner"
)

_PERFORMANCE_REFUSAL = (
    "I don't compute or compare historical returns. "
    "For performance data, please visit the scheme's page directly on Groww."
)

_OUT_OF_SCOPE_REFUSAL = (
    "I can only answer factual questions about these mutual fund schemes: "
    "Nippon India Taiwan Equity Fund Direct - Growth, "
    "Bandhan Small Cap Fund Direct - Growth, and "
    "HDFC Mid Cap Fund Direct - Growth. "
    "Your question appears to be outside this scope."
)

_INTENT_REFUSALS = {
    Intent.ADVISORY: _ADVISORY_REFUSAL,
    Intent.PERFORMANCE_CALC: _PERFORMANCE_REFUSAL,
    Intent.OUT_OF_SCOPE: _OUT_OF_SCOPE_REFUSAL,
}


class InputGuard:
    def __init__(self, classifier: IntentClassifier):
        self._classifier = classifier

    def check(self, query: str) -> InputGuardResult:
        # 1. PII
        pii = pii_scrubber.scrub(query)
        if pii.found:
            return InputGuardResult(
                passed=False,
                pii_found=True,
                pii_types=pii.types,
                refusal_response=_PII_REFUSAL,
            )

        # 2. Injection
        inj = injection_filter.check(query)
        if inj.detected:
            return InputGuardResult(
                passed=False,
                injection_detected=True,
                refusal_response=_INJECTION_REFUSAL,
            )

        # 3. Intent
        intent_result = self._classifier.classify(query)
        if intent_result.intent != Intent.FACTUAL:
            return InputGuardResult(
                passed=False,
                intent=intent_result.intent,
                refusal_response=_INTENT_REFUSALS[intent_result.intent],
            )

        return InputGuardResult(
            passed=True,
            intent=Intent.FACTUAL,
            scrubbed_query=query,
        )


def build_input_guard(config: dict) -> InputGuard:
    from .intent_classifier import build_intent_classifier
    classifier = build_intent_classifier(config.get("intent", {}))
    return InputGuard(classifier=classifier)
