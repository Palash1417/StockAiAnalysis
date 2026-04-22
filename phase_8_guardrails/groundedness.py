"""Groundedness checker — §8.2 step 4.

LLM-as-judge: verifies that every factual claim in the generated answer
is supported by the retrieved context chunks. Uses Groq (optional).
Falls back to grounded=True when disabled or on error, so it never
silently blocks a valid answer.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from .models import GroundednessResult

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a groundedness evaluator for a Mutual Fund FAQ assistant.

You will be given:
1. A user question
2. A generated answer
3. Source context chunks used for retrieval

Your task: decide whether every factual claim in the answer is supported
by the provided context. Do NOT penalise the answer for being concise.
Only flag claims that directly contradict or are absent from the context.

Return ONLY a JSON object (no markdown, no explanation):
{
  "grounded": true | false,
  "score": <float 0.0–1.0>,
  "reason": "<one sentence>"
}"""


def _format_context(candidates: list[Any]) -> str:
    parts = []
    for i, c in enumerate(candidates, 1):
        text = getattr(c, "text", str(c))
        parts.append(f"[{i}] {text}")
    return "\n".join(parts)


class GroundednessChecker:
    """Wraps a Groq client to run LLM-as-judge groundedness checks.

    If *client* is None the checker always returns grounded=True (passthrough),
    which is the safe default when the feature is disabled in config.
    """

    def __init__(
        self,
        client: Any = None,
        model: str = "llama-3.3-70b-versatile",
        threshold: float = 0.7,
    ):
        self._client = client
        self._model = model
        self._threshold = threshold

    def check(
        self,
        query: str,
        answer: str,
        candidates: list[Any],
    ) -> GroundednessResult:
        if self._client is None or not candidates:
            return GroundednessResult(grounded=True, score=1.0, reason="passthrough")

        context = _format_context(candidates)
        user_msg = (
            f"Question: {query}\n\n"
            f"Answer: {answer}\n\n"
            f"Context:\n{context}"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=128,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            score = float(data.get("score", 1.0))
            grounded = bool(data.get("grounded", True)) and score >= self._threshold
            return GroundednessResult(
                grounded=grounded,
                score=score,
                reason=str(data.get("reason", "")),
            )
        except Exception as exc:
            log.warning("groundedness check failed (%s) — passing through", exc)
            return GroundednessResult(grounded=True, score=1.0, reason="error_passthrough")


def build_groundedness_checker(config: dict[str, Any]) -> GroundednessChecker:
    """Factory. enabled=false (default) → passthrough checker (no LLM call)."""
    if not config.get("enabled", False):
        return GroundednessChecker(client=None)
    threshold = float(config.get("threshold", 0.7))
    try:
        import groq  # type: ignore
        client = groq.Groq()
        return GroundednessChecker(
            client=client,
            model=config.get("model", "llama-3.3-70b-versatile"),
            threshold=threshold,
        )
    except Exception:
        log.warning("groq unavailable; groundedness checker disabled")
        return GroundednessChecker(client=None)
