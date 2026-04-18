"""Local CLI for exercising phase 4.1 against a structured JSON file on disk.

Usage:
    python cli.py ingest --json path/to/src_002.json \
        --source-id src_002 --run-id local_dev
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ingestion_pipeline import IngestionPipeline
from ingestion_pipeline.chunker import Chunker
from ingestion_pipeline.embedder import CachedEmbedder, FakeDeterministicEmbedder
from ingestion_pipeline.embedding_cache import InMemoryEmbeddingCache
from ingestion_pipeline.hasher import ChunkHasher
from ingestion_pipeline.index_writer import (
    IndexWriter,
    InMemoryBM25,
    InMemoryFactKV,
    InMemoryVectorIndex,
)
from ingestion_pipeline.models import ParsedDocument
from ingestion_pipeline.segmenter import DocumentSegmenter
from ingestion_pipeline.snapshot import (
    InMemoryCorpusPointer,
    SmokeQuery,
    SnapshotManager,
)


def _always_pass(_version: str, _queries: list[SmokeQuery]) -> float:
    return 1.0


def _build_pipeline() -> IngestionPipeline:
    embedder = FakeDeterministicEmbedder(dim=64)
    cached = CachedEmbedder(
        embedder=embedder, cache=InMemoryEmbeddingCache(),
        retry_backoff_s=(0,), max_attempts=1,
    )
    vec, bm, kv = InMemoryVectorIndex(), InMemoryBM25(), InMemoryFactKV()
    pointer = InMemoryCorpusPointer()

    return IngestionPipeline(
        segmenter=DocumentSegmenter(),
        chunker=Chunker(),
        hasher=ChunkHasher(embed_model_id=embedder.model_id),
        embedder=cached,
        index_writer=IndexWriter(vec, bm, kv),
        snapshot_manager=SnapshotManager(
            pointer=pointer,
            smoke_queries=[SmokeQuery(query="expense ratio?")],
            smoke_runner=_always_pass,
        ),
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="phase_4_1.cli")
    sub = ap.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="Ingest a structured JSON doc.")
    ing.add_argument("--json", required=True, type=Path)
    ing.add_argument("--source-id", required=True)
    ing.add_argument("--scheme", required=True)
    ing.add_argument("--source-url", required=True)
    ing.add_argument("--last-updated", required=True)
    ing.add_argument("--run-id", default="local_dev")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.command == "ingest":
        data = json.loads(args.json.read_text(encoding="utf-8"))
        doc = ParsedDocument(
            source_id=args.source_id,
            scheme=args.scheme,
            source_url=args.source_url,
            last_updated=args.last_updated,
            facts=data.get("facts", {}),
            sections=data.get("sections", []),
            tables=data.get("tables", []),
        )
        pipeline = _build_pipeline()
        result = pipeline.handle(run_id=args.run_id, doc=doc)
        print(json.dumps({
            "corpus_version": result.corpus_version,
            "swapped": result.swapped,
            "upsert_report": result.upsert_report.to_dict(),
        }, indent=2))
        return 0 if result.swapped else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
