from __future__ import annotations

import re
from typing import Any, Optional

from ..models import ParsedDocument, Source

FACT_LABELS = {
    "expense_ratio": ["Expense Ratio", "Expense ratio"],
    "exit_load": ["Exit Load", "Exit load"],
    "min_sip": ["Min SIP", "Minimum SIP", "Min. SIP"],
    "min_lumpsum": ["Min Lumpsum", "Minimum Lumpsum", "Min. Lumpsum"],
    "lock_in": ["Lock-in", "Lock in", "Lock-In"],
    "risk": ["Risk", "Riskometer"],
    "benchmark": ["Benchmark"],
    "fund_manager": ["Fund Manager", "Fund Managers"],
    "aum": ["AUM", "Fund Size"],
    "launch_date": ["Launch Date", "Inception Date"],
}


class GrowwSchemePageParser:
    """Parse a rendered Groww scheme page into facts + narrative sections + tables."""

    def parse(self, source: Source, html: str) -> ParsedDocument:
        try:
            from bs4 import BeautifulSoup  # type: ignore
        except ImportError as e:
            raise RuntimeError("beautifulsoup4 is required for parsing") from e

        soup = BeautifulSoup(html, "html.parser")

        facts = self._extract_facts(soup)
        if "scheme" not in facts:
            facts["scheme"] = source.scheme

        sections = self._extract_sections(soup)
        tables = self._extract_tables(soup)

        return ParsedDocument(
            source_id=source.id,
            scheme=source.scheme,
            facts=facts,
            sections=sections,
            tables=tables,
        )

    def _extract_facts(self, soup: Any) -> dict[str, Any]:
        text_blob = soup.get_text(separator="\n", strip=True)
        out: dict[str, Any] = {}

        for field_name, labels in FACT_LABELS.items():
            value = self._find_labeled_value(text_blob, labels)
            if value is not None:
                out[field_name] = value

        for node in soup.find_all(["li", "div", "tr", "p"]):
            txt = node.get_text(" ", strip=True)
            for field_name, labels in FACT_LABELS.items():
                if field_name in out:
                    continue
                for label in labels:
                    pat = rf"{re.escape(label)}\s*[:\-]?\s*(.+)"
                    m = re.match(pat, txt, re.IGNORECASE)
                    if m:
                        val = m.group(1).strip()
                        if val and len(val) < 200:
                            out[field_name] = val
                            break

        return out

    @staticmethod
    def _find_labeled_value(blob: str, labels: list[str]) -> Optional[str]:
        for label in labels:
            pat = rf"{re.escape(label)}\s*[:\-]?\s*\n?\s*([^\n]+)"
            m = re.search(pat, blob, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and len(val) < 200:
                    return val
        return None

    def _extract_sections(self, soup: Any) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        for h in soup.find_all(["h1", "h2", "h3"]):
            heading = h.get_text(" ", strip=True)
            if not heading:
                continue
            body_parts: list[str] = []
            for sib in h.next_siblings:
                name = getattr(sib, "name", None)
                if name in {"h1", "h2", "h3"}:
                    break
                if hasattr(sib, "get_text"):
                    t = sib.get_text(" ", strip=True)
                    if t:
                        body_parts.append(t)
            body = "\n\n".join(body_parts).strip()
            if body:
                sections.append(
                    {"heading": heading, "level": int(h.name[1]), "body": body}
                )
        return sections

    def _extract_tables(self, soup: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for idx, table in enumerate(soup.find_all("table")):
            headers = [
                th.get_text(" ", strip=True) for th in table.find_all("th")
            ]
            rows: list[list[str]] = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
                if cells:
                    rows.append(cells)
            if headers or rows:
                caption_el = table.find("caption")
                caption = caption_el.get_text(" ", strip=True) if caption_el else None
                out.append(
                    {
                        "index": idx,
                        "caption": caption,
                        "headers": headers,
                        "rows": rows,
                    }
                )
        return out
