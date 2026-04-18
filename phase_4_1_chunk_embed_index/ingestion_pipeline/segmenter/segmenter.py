"""Document Segmenter — §5.2.

Input: ParsedDocument from the scraper.
Output: typed segments: fact_table | section_text | table.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import ParsedDocument, SegmentType


@dataclass
class Segment:
    segment_type: SegmentType
    source_id: str
    scheme: str
    section: str | None
    doc_anchor: str | None
    payload: dict[str, Any] = field(default_factory=dict)


class DocumentSegmenter:
    def segment(self, doc: ParsedDocument) -> list[Segment]:
        out: list[Segment] = []

        if doc.facts:
            out.append(
                Segment(
                    segment_type="fact_table",
                    source_id=doc.source_id,
                    scheme=doc.scheme,
                    section="facts",
                    doc_anchor="facts",
                    payload={"facts": dict(doc.facts)},
                )
            )

        for sec in doc.sections:
            heading = sec.get("heading") or ""
            body = sec.get("body") or ""
            if not body.strip():
                continue
            out.append(
                Segment(
                    segment_type="section_text",
                    source_id=doc.source_id,
                    scheme=doc.scheme,
                    section=heading,
                    doc_anchor=_slugify(heading),
                    payload={"heading": heading, "body": body,
                             "level": sec.get("level", 2)},
                )
            )

        for tbl in doc.tables:
            caption = tbl.get("caption") or f"table_{tbl.get('index', 0)}"
            out.append(
                Segment(
                    segment_type="table",
                    source_id=doc.source_id,
                    scheme=doc.scheme,
                    section=caption,
                    doc_anchor=_slugify(caption),
                    payload={
                        "headers": tbl.get("headers") or [],
                        "rows": tbl.get("rows") or [],
                        "caption": caption,
                    },
                )
            )

        return out


def _slugify(text: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "untitled"
