from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

ScrapeStatus = Literal["changed", "unchanged", "degraded", "failed"]


@dataclass
class Source:
    id: str
    url: str
    type: str
    scheme: str
    category: str
    source_class: str
    fetched_at: Optional[str] = None
    checksum: Optional[str] = None


@dataclass
class ParsedDocument:
    source_id: str
    scheme: str
    facts: dict[str, Any] = field(default_factory=dict)
    sections: list[dict[str, Any]] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "scheme": self.scheme,
            "facts": self.facts,
            "sections": self.sections,
            "tables": self.tables,
        }


@dataclass
class ScrapeResult:
    source_id: str
    status: ScrapeStatus
    checksum: Optional[str] = None
    fields_extracted: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class ScrapeReport:
    run_id: str
    started_at: str
    finished_at: Optional[str] = None
    results: list[ScrapeResult] = field(default_factory=list)

    @property
    def summary(self) -> dict[str, int]:
        s = {"changed": 0, "unchanged": 0, "degraded": 0, "failed": 0}
        for r in self.results:
            s[r.status] = s.get(r.status, 0) + 1
        return s

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
        }


@dataclass
class DocumentChangedEvent:
    run_id: str
    source_id: str
    source_url: str
    scheme: str
    structured_json_path: str
    html_path: str
    checksum: str
    emitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
