from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..models import ParsedDocument


@dataclass
class ValidationResult:
    ok: bool
    missing_required: list[str]
    extraction_ratio: float
    error: Optional[str] = None


class Validator:
    """Validates a ParsedDocument against required + tracked fields.

    - Missing any required field  → ok=False, caller marks source `degraded`.
    - extraction_ratio = fraction of tracked fields extracted; used for drift alerts.
    """

    def __init__(self, required_fields: list[str], tracked_fields: list[str]):
        self.required_fields = required_fields
        self.tracked_fields = tracked_fields

    def validate(self, doc: ParsedDocument) -> ValidationResult:
        missing = [f for f in self.required_fields if not doc.facts.get(f)]
        extracted = sum(1 for f in self.tracked_fields if doc.facts.get(f))
        ratio = extracted / len(self.tracked_fields) if self.tracked_fields else 1.0
        return ValidationResult(
            ok=not missing,
            missing_required=missing,
            extraction_ratio=ratio,
            error=f"missing field: {missing[0]}" if missing else None,
        )
