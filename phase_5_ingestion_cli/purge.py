"""Hard-purge cron for soft-deleted chunks — §5.8.

Soft-delete marks rows with ``deleted_at``; this module permanently removes
them after the retention window expires. Should be scheduled as a separate
cron (daily is fine — rows are retained at least ``cutoff_days`` from the
point they were soft-deleted).

Designed to run independently of the main ingest path so a failed purge
never blocks an ingest run.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Any

log = logging.getLogger(__name__)

_DEFAULT_CUTOFF_DAYS = 7


@dataclass
class PurgeReport:
    cutoff_days: int
    rows_purged: int

    def to_dict(self) -> dict:
        return {"cutoff_days": self.cutoff_days, "rows_purged": self.rows_purged}


def hard_purge_deleted_chunks(
    vector_index,
    *,
    cutoff_days: int = _DEFAULT_CUTOFF_DAYS,
) -> PurgeReport:
    """Delete rows soft-deleted more than ``cutoff_days`` ago.

    ``vector_index`` must expose ``hard_purge_older_than(cutoff_days) -> int``
    (implemented by both ``InMemoryVectorIndex``-compatible fakes and
    ``PgVectorIndex``).
    """
    if cutoff_days < 1:
        raise ValueError(f"cutoff_days must be >= 1, got {cutoff_days}")

    rows_purged = vector_index.hard_purge_older_than(cutoff_days)
    log.info(
        "hard purge complete: removed %d rows soft-deleted > %d days ago",
        rows_purged,
        cutoff_days,
    )
    return PurgeReport(cutoff_days=cutoff_days, rows_purged=rows_purged)
