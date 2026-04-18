"""Snapshot + atomic swap — §5.9.

Every run builds a new corpus_version. The pointer only flips after the
smoke test passes. On failure, the new version is left dangling and the
retriever continues on the previous live version.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Protocol

log = logging.getLogger(__name__)


class SmokeTestFailed(Exception):
    """Raised when canned smoke queries fail against the new version."""


@dataclass
class SmokeQuery:
    query: str
    expected_scheme: str | None = None
    expected_field: str | None = None  # only meaningful for fact lookups


class CorpusPointer(Protocol):
    def get_live(self) -> str | None: ...
    def set_live(self, corpus_version: str) -> None: ...
    def history(self) -> list[str]: ...


class InMemoryCorpusPointer:
    def __init__(self) -> None:
        self._live: str | None = None
        self._history: list[str] = []

    def get_live(self) -> str | None:
        return self._live

    def set_live(self, corpus_version: str) -> None:
        self._live = corpus_version
        if corpus_version not in self._history:
            self._history.append(corpus_version)

    def history(self) -> list[str]:
        return list(self._history)


SmokeRunner = Callable[[str, list[SmokeQuery]], float]  # returns pass_rate 0..1


class SnapshotManager:
    """Runs smoke queries against the candidate corpus_version and swaps the
    live pointer only when the pass rate is 1.0.
    """

    def __init__(
        self,
        pointer: CorpusPointer,
        smoke_queries: list[SmokeQuery],
        smoke_runner: SmokeRunner,
        keep_versions: int = 7,
        gc: Callable[[list[str]], None] | None = None,
    ):
        self.pointer = pointer
        self.smoke_queries = smoke_queries
        self.smoke_runner = smoke_runner
        self.keep = keep_versions
        self.gc = gc

    def try_swap(self, candidate_version: str) -> str:
        """Runs smoke test; flips pointer on 100 % pass. Returns the live version."""
        pass_rate = self.smoke_runner(candidate_version, self.smoke_queries)
        if pass_rate < 1.0:
            previous = self.pointer.get_live()
            log.error(
                "smoke test failed for %s (pass_rate=%.2f). Keeping %s live.",
                candidate_version, pass_rate, previous,
            )
            raise SmokeTestFailed(
                f"candidate {candidate_version} pass_rate={pass_rate:.2f} < 1.0"
            )

        self.pointer.set_live(candidate_version)
        self._gc_old_versions()
        return candidate_version

    def _gc_old_versions(self) -> None:
        history = self.pointer.history()
        if len(history) <= self.keep:
            return
        to_drop = history[: -self.keep]
        if self.gc is not None:
            self.gc(to_drop)
        log.info("gc corpus versions: %s", to_drop)
