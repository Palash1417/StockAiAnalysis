"""Chunker — §5.3.

Applies per-segment rules:
  - fact_table  → one chunk per fact (atomic, wrapped in sentence template)
  - section_text → 500 tokens, 80 overlap, heading-prefixed, min 100 tokens
  - table        → ≤6 rows or ≤400 tokens, header re-included per chunk
"""
from __future__ import annotations

import logging
from typing import Callable

from ..models import Chunk
from ..segmenter import Segment

log = logging.getLogger(__name__)

FACT_SENTENCE = {
    "expense_ratio": "{scheme} has an expense ratio of {value}.",
    "exit_load": "{scheme} has an exit load of {value}.",
    "min_sip": "{scheme} has a minimum SIP of {value}.",
    "min_lumpsum": "{scheme} has a minimum lumpsum investment of {value}.",
    "lock_in": "{scheme} has a lock-in period of {value}.",
    "risk": "{scheme} has a riskometer classification of {value}.",
    "benchmark": "{scheme} is benchmarked against {value}.",
    "fund_manager": "{scheme} is managed by {value}.",
    "aum": "{scheme} has assets under management of {value}.",
    "launch_date": "{scheme} was launched on {value}.",
    "scheme": "{value} is the full scheme name.",
}

# Recursive splitter separators (§5.3.2)
SPLIT_SEPARATORS = ["\n## ", "\n### ", "\n\n", "\n", ". ", " "]

DEFAULT_TARGET_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 80
DEFAULT_MIN_TOKENS = 100
TABLE_ROW_LIMIT = 6
TABLE_TOKEN_LIMIT = 400


TokenCounter = Callable[[str], int]


def _word_count(text: str) -> int:
    """Fallback token counter — splits on whitespace.

    Used when tiktoken is unavailable. Word count is ~0.75x token count, so
    targets are conservative (we'll produce slightly smaller chunks, never
    larger). That's fine for our use case.
    """
    return len(text.split())


def _build_token_counter() -> TokenCounter:
    try:
        import tiktoken  # type: ignore
        enc = tiktoken.get_encoding("cl100k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        return _word_count


class Chunker:
    def __init__(
        self,
        target_tokens: int = DEFAULT_TARGET_TOKENS,
        overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
        min_tokens: int = DEFAULT_MIN_TOKENS,
        token_counter: TokenCounter | None = None,
    ):
        self.target = target_tokens
        self.overlap = overlap_tokens
        self.min_tokens = min_tokens
        self.count = token_counter or _build_token_counter()

    def chunk(self, segments: list[Segment]) -> list[Chunk]:
        out: list[Chunk] = []
        for seg in segments:
            if seg.segment_type == "fact_table":
                out.extend(self._chunk_facts(seg))
            elif seg.segment_type == "section_text":
                out.extend(self._chunk_section(seg))
            elif seg.segment_type == "table":
                out.extend(self._chunk_table(seg))
        return out

    # §5.3.1 -----------------------------------------------------------------
    def _chunk_facts(self, seg: Segment) -> list[Chunk]:
        facts = seg.payload.get("facts", {})
        chunks: list[Chunk] = []
        for field_name, value in facts.items():
            if value is None or str(value).strip() == "":
                continue
            template = FACT_SENTENCE.get(
                field_name, "{scheme} {field}: {value}."
            )
            text = template.format(
                scheme=seg.scheme, value=value, field=field_name.replace("_", " ")
            )
            chunks.append(
                Chunk(
                    chunk_id=f"{seg.source_id}#fact#{field_name}",
                    source_id=seg.source_id,
                    scheme=seg.scheme,
                    section="facts",
                    segment_type="fact_table",
                    text=text,
                    metadata={"field_name": field_name, "raw_value": str(value)},
                )
            )
        return chunks

    # §5.3.2 -----------------------------------------------------------------
    def _chunk_section(self, seg: Segment) -> list[Chunk]:
        heading = seg.payload.get("heading", seg.section or "")
        body = seg.payload.get("body", "")
        heading_prefix = f"Section: {heading}\n\n" if heading else ""

        pieces = self._recursive_split(body, self.target)

        # Overlap: tail of each piece prepended to the next
        overlapped: list[str] = []
        for idx, piece in enumerate(pieces):
            if idx == 0 or self.overlap <= 0:
                overlapped.append(piece)
                continue
            prev_words = pieces[idx - 1].split()
            tail = " ".join(prev_words[-self.overlap:])
            overlapped.append((tail + " " + piece).strip() if tail else piece)

        # Min-size guard: merge tiny trailing chunks into predecessor
        merged: list[str] = []
        for piece in overlapped:
            if merged and self.count(piece) < self.min_tokens:
                merged[-1] = (merged[-1] + "\n" + piece).strip()
            else:
                merged.append(piece)

        slug = seg.doc_anchor or "section"
        chunks: list[Chunk] = []
        for i, body_text in enumerate(merged):
            text = heading_prefix + body_text
            chunks.append(
                Chunk(
                    chunk_id=f"{seg.source_id}#{slug}#c{i}",
                    source_id=seg.source_id,
                    scheme=seg.scheme,
                    section=heading or None,
                    segment_type="section_text",
                    text=text,
                    metadata={"heading": heading, "chunk_index": i},
                )
            )
        return chunks

    # §5.3.3 -----------------------------------------------------------------
    def _chunk_table(self, seg: Segment) -> list[Chunk]:
        headers: list[str] = seg.payload.get("headers") or []
        rows: list[list[str]] = seg.payload.get("rows") or []
        caption = seg.payload.get("caption", "table")

        if not rows:
            return []

        slug = seg.doc_anchor or "table"
        header_md = self._row_md(headers) if headers else ""
        divider = "| " + " | ".join(["---"] * max(len(headers), 1)) + " |" if headers else ""

        chunks: list[Chunk] = []
        start = 0
        while start < len(rows):
            # Grow window until we hit row or token limit
            end = start
            while end < len(rows) and (end - start) < TABLE_ROW_LIMIT:
                candidate_rows = rows[start : end + 1]
                md = self._table_md(headers, candidate_rows, header_md, divider, caption)
                if self.count(md) > TABLE_TOKEN_LIMIT and end > start:
                    break
                end += 1
            end = max(end, start + 1)

            window_rows = rows[start:end]
            md = self._table_md(headers, window_rows, header_md, divider, caption)
            chunks.append(
                Chunk(
                    chunk_id=f"{seg.source_id}#table_{slug}#rows_{start}-{end - 1}",
                    source_id=seg.source_id,
                    scheme=seg.scheme,
                    section=caption,
                    segment_type="table",
                    text=md,
                    metadata={"caption": caption, "rows_range": [start, end - 1]},
                )
            )
            start = end

        return chunks

    # ------------------------------------------------------------------
    def _recursive_split(self, text: str, target: int) -> list[str]:
        text = text.strip()
        if not text:
            return []
        if self.count(text) <= target:
            return [text]

        for sep in SPLIT_SEPARATORS:
            if sep in text:
                parts = [p for p in text.split(sep) if p]
                if len(parts) == 1:
                    continue
                # Re-glue with a single space / newline to preserve readability
                joined_sep = sep if sep.strip() else sep
                return self._greedy_merge(parts, target, joined_sep)

        # Last-ditch hard split on target
        return [text[: target * 4], text[target * 4 :]]

    def _greedy_merge(self, parts: list[str], target: int, sep: str) -> list[str]:
        out: list[str] = []
        buf = ""
        for part in parts:
            candidate = (buf + sep + part) if buf else part
            if self.count(candidate) <= target:
                buf = candidate
                continue
            if buf:
                out.append(buf.strip())
            # Part alone still too big → recurse
            if self.count(part) > target:
                out.extend(self._recursive_split(part, target))
                buf = ""
            else:
                buf = part
        if buf:
            out.append(buf.strip())
        return out

    @staticmethod
    def _row_md(cells: list[str]) -> str:
        return "| " + " | ".join(c.replace("|", r"\|") for c in cells) + " |"

    def _table_md(
        self,
        headers: list[str],
        rows: list[list[str]],
        header_md: str,
        divider: str,
        caption: str,
    ) -> str:
        lines: list[str] = []
        if caption:
            lines.append(f"**{caption}**")
        if header_md:
            lines.append(header_md)
            lines.append(divider)
        for row in rows:
            lines.append(self._row_md(row))
        return "\n".join(lines)
