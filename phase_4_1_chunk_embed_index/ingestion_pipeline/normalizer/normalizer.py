"""Normalization per §5.4. Intentionally light — no stemming, no stopwords."""
from __future__ import annotations

import re
import unicodedata

_CURRENCY_RE = re.compile(r"(?:Rs\.?|INR)\s*", re.IGNORECASE)
_PCT_RE = re.compile(r"(\d)\s+%")
_WS_RE = re.compile(r"\s+")


def normalize_for_display(text: str) -> str:
    """Normalization applied before embedding (preserves case)."""
    t = unicodedata.normalize("NFKC", text)
    t = _CURRENCY_RE.sub("₹", t)
    t = _PCT_RE.sub(r"\1%", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def normalize_for_hash(text: str) -> str:
    """Normalization applied before hashing (lowercased for cache stability)."""
    return normalize_for_display(text).lower()
