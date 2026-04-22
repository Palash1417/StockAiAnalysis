"""Query rewriter — §6.2.

Two modes:
 - Rule-based: abbreviation expansion only (no network, always works).
 - LLM-backed: 1 Groq call for full coreference resolution.
   Falls back to rule-based on any error.

build_query_rewriter(config) factory; use_llm=False → rule-based always.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# Mutual-fund domain abbreviations
_ABBREVS: dict[str, str] = {
    "ELSS": "Equity Linked Saving Scheme",
    "SIP": "Systematic Investment Plan",
    "NAV": "Net Asset Value",
    "TER": "Total Expense Ratio",
    "AUM": "Assets Under Management",
    "XIRR": "Extended Internal Rate of Return",
    "CAGR": "Compound Annual Growth Rate",
    "SWP": "Systematic Withdrawal Plan",
    "STP": "Systematic Transfer Plan",
    "AMC": "Asset Management Company",
    "KIM": "Key Information Memorandum",
    "SID": "Scheme Information Document",
    "NFO": "New Fund Offer",
    "FOF": "Fund of Funds",
    "ETF": "Exchange Traded Fund",
}

_ABBREV_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in _ABBREVS) + r")\b",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "You are a query rewriter for a Mutual Fund FAQ assistant. "
    "Your only job is to rewrite the user query so it is more specific and "
    "searchable against a corpus of mutual fund scheme facts. "
    "Rules:\n"
    "- Expand acronyms (SIP, TER, NAV, ELSS, AUM, etc.) in full.\n"
    "- Resolve co-references using conversation history "
    "(e.g., 'its expense ratio' → 'expense ratio of <scheme name>').\n"
    "- Keep the query factual and concise — one sentence.\n"
    "- Do NOT answer the query; ONLY rewrite it.\n"
    "- Return ONLY the rewritten query text, no explanation."
)


def expand_abbreviations(text: str) -> str:
    """Rule-based abbreviation expansion (case-insensitive, whole-word)."""
    def _replace(m: re.Match) -> str:
        word = m.group(0)
        return _ABBREVS.get(word.upper(), word)

    return _ABBREV_RE.sub(_replace, text)


class QueryRewriter:
    """Rewrites a query using Groq (1 call) + abbreviation expansion.

    `client` is a `groq.Groq()` instance or None (rule-based only).
    Only the last 4 turns (8 messages) of history are included in the prompt
    to avoid inflating token count (§6.2 / §9.2).
    """

    def __init__(self, client: Any = None, model: str = "llama-3.3-70b-versatile"):
        self._client = client
        self._model = model

    def rewrite(
        self,
        query: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Return a rewritten query string.

        history is a list of {"role": "user"|"assistant", "content": "..."}.
        """
        expanded = expand_abbreviations(query)

        if self._client is None:
            return expanded

        last_turns = (history or [])[-8:]  # last 4 user+assistant pairs

        try:
            messages = [
                {"role": "system", "content": _SYSTEM_PROMPT},
                *last_turns,
                {"role": "user", "content": f"Rewrite this query: {query}"},
            ]
            resp = self._client.chat.completions.create(
                model=self._model,
                max_tokens=256,
                messages=messages,
            )
            rewritten = resp.choices[0].message.content.strip()
            return rewritten if rewritten else expanded
        except Exception as exc:
            log.warning(
                "query rewrite LLM call failed (%s) — using rule-based fallback", exc
            )
            return expanded


def build_query_rewriter(config: dict[str, Any]) -> QueryRewriter:
    """Factory. If use_llm is False or the groq package is unavailable,
    the rewriter falls back to rule-based abbreviation expansion.
    """
    if not config.get("use_llm", True):
        return QueryRewriter(client=None)
    try:
        import groq  # type: ignore
        client = groq.Groq()
        return QueryRewriter(client=client, model=config.get("model", "llama-3.3-70b-versatile"))
    except Exception:
        log.warning("groq unavailable; using rule-based query rewriter")
        return QueryRewriter(client=None)
