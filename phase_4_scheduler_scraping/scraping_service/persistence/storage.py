from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol


class Storage(Protocol):
    def write_html(self, run_id: str, source_id: str, html: str) -> str: ...
    def write_structured(self, run_id: str, source_id: str, data: dict) -> str: ...
    def write_report(self, report_path: str, data: dict) -> str: ...


class LocalStorage:
    """Filesystem-backed storage. Swap for S3/MinIO in prod via the Storage protocol."""

    def __init__(self, base_dir: str):
        self.base = Path(base_dir)

    def _corpus_dir(self, run_id: str) -> Path:
        d = self.base / "corpus" / run_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_html(self, run_id: str, source_id: str, html: str) -> str:
        path = self._corpus_dir(run_id) / f"{source_id}.html"
        path.write_text(html, encoding="utf-8")
        return str(path)

    def write_structured(self, run_id: str, source_id: str, data: dict) -> str:
        path = self._corpus_dir(run_id) / f"{source_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def write_report(self, report_path: str, data: dict) -> str:
        path = self.base / report_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)
