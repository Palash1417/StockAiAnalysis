"""PII scrubber — §8.1 step 1.

Detects and redacts: PAN, Aadhaar, email, Indian mobile number.
Returns a PIIResult; the caller decides whether to refuse or pass through
the scrubbed text.
"""
from __future__ import annotations

import re

from .models import PIIResult

# PAN: 5 uppercase letters, 4 digits, 1 uppercase letter (e.g. ABCDE1234F)
_PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")

# Aadhaar: 12 digits, optionally grouped as 4-4-4 with spaces or hyphens
_AADHAAR_RE = re.compile(
    r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b"
)

# Email
_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
)

# Indian mobile: optional +91/0 prefix, then 10 digits starting with 6–9
_PHONE_RE = re.compile(
    r"(?:\+91[\s\-]?|0)?[6-9]\d{9}\b"
)

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("PAN", _PAN_RE),
    ("phone", _PHONE_RE),   # phone before Aadhaar: +91XXXXXXXXXX is 12 digits and would match Aadhaar
    ("Aadhaar", _AADHAAR_RE),
    ("email", _EMAIL_RE),
]


def scrub(text: str) -> PIIResult:
    """Scan *text* for PII patterns.

    Returns a PIIResult with found=True if any PII is detected, along with
    the redacted text and the list of detected PII type names.
    """
    found_types: list[str] = []
    scrubbed = text

    for label, pattern in _PATTERNS:
        if pattern.search(scrubbed):
            found_types.append(label)
            scrubbed = pattern.sub(f"[REDACTED_{label.upper()}]", scrubbed)

    return PIIResult(
        found=bool(found_types),
        types=found_types,
        scrubbed_text=scrubbed,
    )
