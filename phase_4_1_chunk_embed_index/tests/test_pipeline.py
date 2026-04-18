"""End-to-end pipeline: DocumentChangedEvent-like input → live index."""
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


def _build(smoke_pass_rate: float = 1.0):
    embedder = FakeDeterministicEmbedder(dim=16)
    cache = InMemoryEmbeddingCache()
    cached = CachedEmbedder(
        embedder=embedder, cache=cache,
        retry_backoff_s=(0,), max_attempts=1,
    )
    vec, bm, kv = InMemoryVectorIndex(), InMemoryBM25(), InMemoryFactKV()
    pointer = InMemoryCorpusPointer()

    pipeline = IngestionPipeline(
        segmenter=DocumentSegmenter(),
        chunker=Chunker(target_tokens=60, overlap_tokens=5, min_tokens=5),
        hasher=ChunkHasher(embed_model_id=embedder.model_id),
        embedder=cached,
        index_writer=IndexWriter(vec, bm, kv),
        snapshot_manager=SnapshotManager(
            pointer=pointer,
            smoke_queries=[SmokeQuery(query="expense ratio")],
            smoke_runner=lambda v, q: smoke_pass_rate,
        ),
    )
    return pipeline, vec, bm, kv, pointer, cached


def _doc():
    return ParsedDocument(
        source_id="src_002",
        scheme="Bandhan Small Cap Fund Direct - Growth",
        source_url="https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
        last_updated="2026-04-19",
        facts={
            "expense_ratio": "0.67%",
            "exit_load": "1% if redeemed within 1 year",
            "benchmark": "NIFTY Smallcap 250 TRI",
        },
        sections=[
            {"heading": "Investment Objective", "level": 2,
             "body": "The scheme seeks long-term capital appreciation through "
                     "small-cap equity. " * 4},
        ],
    )


def test_end_to_end_happy_path_swaps_pointer():
    pipeline, vec, bm, kv, pointer, cached = _build(smoke_pass_rate=1.0)

    result = pipeline.handle(run_id="20260419", doc=_doc())
    assert result.swapped is True
    assert result.corpus_version == "corpus_v_20260419"

    # Fact chunks present in all three stores
    assert vec.count(result.corpus_version) >= 3
    assert any("expense_ratio" in cid for cid in
               [r["chunk_id"] for r in vec.rows(result.corpus_version)])
    assert kv.get("src_002", "expense_ratio")["value"] == "0.67%"
    assert pointer.get_live() == result.corpus_version

    # Second ingest with same doc → cache hits everywhere, no new API calls
    cached.api_embeds = 0
    cached.cache_hits = 0
    pipeline.handle(run_id="20260420", doc=_doc())
    assert cached.api_embeds == 0
    assert cached.cache_hits > 0


def test_failed_smoke_keeps_previous_live():
    pipeline, vec, bm, kv, pointer, _ = _build(smoke_pass_rate=0.8)

    # First run: force smoke pass by patching the runner
    pipeline.snapshot_manager.smoke_runner = lambda v, q: 1.0
    result1 = pipeline.handle(run_id="r1", doc=_doc())
    assert pointer.get_live() == result1.corpus_version

    # Second run: smoke fails → pointer stays on r1
    pipeline.snapshot_manager.smoke_runner = lambda v, q: 0.5
    doc2 = _doc()
    doc2.facts["expense_ratio"] = "0.99%"  # ensure new content
    result2 = pipeline.handle(run_id="r2", doc=doc2)
    assert result2.swapped is False
    assert result2.error and "pass_rate" in result2.error
    assert pointer.get_live() == result1.corpus_version
