"""Length enforcer — §8.2 step 2.

Enforces the ≤ 3 sentence limit on generated answers (§7.1).
Splits on sentence-ending punctuation followed by whitespace + capital letter,
which is robust enough for the short, factual answers this system produces.
"""
from __future__ import annotations

import re

# Split after .!? when followed by whitespace then an uppercase letter or quote.
# This avoids splitting on abbreviations like "0.67%" or "Rs. 500".
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\u2018\u201C])')


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def enforce(text: str, max_sentences: int = 3) -> str:
    """Return *text* truncated to *max_sentences* sentences.

    If the text is already within the limit it is returned unchanged.
    The last retained sentence keeps its original trailing punctuation.
    """
    sentences = split_sentences(text)
    if len(sentences) <= max_sentences:
        return text
    kept = sentences[:max_sentences]
    result = " ".join(kept)
    # Ensure the result ends with punctuation from the last kept sentence
    if result and result[-1] not in ".!?":
        result += "."
    return result
