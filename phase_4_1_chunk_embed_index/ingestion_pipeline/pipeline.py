"""IngestionPipeline — wires §5.2–§5.9 into a single callable.

Input:  a DocumentChangedEvent payload (produced by phase 4.0) plus the
        ParsedDocument reconstructed from the structured JSON.
Output: IngestionResult with the corpus_version, upsert report, and
        whether the pointer was swapped.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from .chunker import Chunker
from .embedder import CachedEmbedder
from .hasher import ChunkHasher
from .index_writer import IndexWriter
from .models import ParsedDocument, UpsertReport
from .segmenter import DocumentSegmenter
from .snapshot import SmokeTestFailed, SnapshotManager

log = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    corpus_version: str
    upsert_report: UpsertReport
    swapped: bool
    error: str | None = None


class IngestionPipeline:
    def __init__(
        self,
        segmenter: DocumentSegmenter,
        chunker: Chunker,
        hasher: ChunkHasher,
        embedder: CachedEmbedder,
        index_writer: IndexWriter,
        snapshot_manager: SnapshotManager,
        version_builder: Callable[[str], str] = lambda run_id: f"corpus_v_{run_id}",
    ):
        self.segmenter = segmenter
        self.chunker = chunker
        self.hasher = hasher
        self.embedder = embedder
        self.index_writer = index_writer
        self.snapshot_manager = snapshot_manager
        self.build_version = version_builder

    def handle(
        self,
        *,
        run_id: str,
        doc: ParsedDocument,
    ) -> IngestionResult:
        corpus_version = self.build_version(run_id)

        segments = self.segmenter.segment(doc)
        chunks = self.chunker.chunk(segments)
        self.hasher.apply(chunks)
        embedded = self.embedder.embed(chunks)

        upsert_report = self.index_writer.upsert(
            embedded,
            corpus_version=corpus_version,
            source_id=doc.source_id,
            source_url=doc.source_url,
            last_updated=doc.last_updated,
        )

        try:
            self.snapshot_manager.try_swap(corpus_version)
            swapped = True
            error: str | None = None
        except SmokeTestFailed as e:
            swapped = False
            error = str(e)
            log.error("pointer not swapped: %s", e)

        return IngestionResult(
            corpus_version=corpus_version,
            upsert_report=upsert_report,
            swapped=swapped,
            error=error,
        )
