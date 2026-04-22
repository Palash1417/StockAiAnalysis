"""Structural smoke runner for SnapshotManager (§5.9).

Retrieval + generation land in Phase 5; until then a query-based smoke test
would be impossible to evaluate meaningfully. This runner does the best
thing available today — it confirms the candidate corpus_version is
physically well-formed:

  1. `min_chunks`          — at least N live rows in `chunks`.
  2. `required_sources`    — every registered source_id appears at least once.
  3. `required_facts`      — every (scheme_id, field_name) has a row in
                             `fact_kv`. This is what actually backs the
                             fact lookup fast path.

Every check is worth 1 point. `pass_rate = passed / total`. SnapshotManager
requires 1.0 to flip the pointer, so any missing check leaves the previous
corpus_version live.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class StructuralSmokeConfig:
    min_chunks: int
    required_sources: list[str]
    required_facts: list[tuple[str, str]]


class StructuralSmokeRunner:
    """Signature matches SnapshotManager's `SmokeRunner` alias:
        Callable[[corpus_version, list[SmokeQuery]], float]
    The `queries` arg is accepted for interface parity with a future
    retrieval-based runner — the structural runner ignores it.
    """

    def __init__(
        self,
        vector_index,
        fact_kv,
        config: StructuralSmokeConfig,
    ):
        self.vector_index = vector_index
        self.fact_kv = fact_kv
        self.config = config

    def __call__(self, corpus_version: str, queries=None) -> float:
        checks: list[tuple[str, bool]] = []

        chunk_count = self.vector_index.count(corpus_version)
        checks.append(
            (f"min_chunks>={self.config.min_chunks}",
             chunk_count >= self.config.min_chunks)
        )

        present_sources = set(
            self.vector_index.distinct_source_ids(corpus_version)
        )
        for sid in self.config.required_sources:
            checks.append((f"source:{sid}", sid in present_sources))

        for scheme_id, field_name in self.config.required_facts:
            row = self.fact_kv.get(scheme_id, field_name)
            checks.append(
                (f"fact:{scheme_id}.{field_name}", row is not None)
            )

        passed = sum(1 for _, ok in checks if ok)
        total = len(checks)
        pass_rate = passed / total if total else 1.0

        for label, ok in checks:
            log.info(
                "smoke %s %s", "PASS" if ok else "FAIL", label,
            )
        log.info(
            "smoke summary: %d/%d passed (rate=%.2f) for %s",
            passed, total, pass_rate, corpus_version,
        )
        return pass_rate


def build_smoke_runner(smoke_cfg: dict, vector_index, fact_kv) -> Callable:
    cfg = StructuralSmokeConfig(
        min_chunks=int(smoke_cfg.get("min_chunks", 1)),
        required_sources=list(smoke_cfg.get("required_sources", [])),
        required_facts=[tuple(p) for p in smoke_cfg.get("required_facts", [])],
    )
    return StructuralSmokeRunner(vector_index, fact_kv, cfg)
