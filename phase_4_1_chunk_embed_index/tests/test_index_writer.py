import pytest

from ingestion_pipeline.embedder import CachedEmbedder, FakeDeterministicEmbedder
from ingestion_pipeline.embedding_cache import InMemoryEmbeddingCache
from ingestion_pipeline.hasher import ChunkHasher
from ingestion_pipeline.index_writer import (
    IndexWriter,
    InMemoryBM25,
    InMemoryFactKV,
    InMemoryVectorIndex,
)
from ingestion_pipeline.index_writer.index_writer import DuplicateChunkIdError
from ingestion_pipeline.models import Chunk


def _embed(chunks):
    emb = FakeDeterministicEmbedder(dim=8)
    ChunkHasher(emb.model_id).apply(chunks)
    cached = CachedEmbedder(
        embedder=emb, cache=InMemoryEmbeddingCache(),
        retry_backoff_s=(0,), max_attempts=1,
    )
    return cached.embed(chunks)


def _fact_chunk(cid: str, field_name: str, value: str):
    return Chunk(
        chunk_id=cid, source_id="src_002", scheme="Bandhan Small Cap",
        section="facts", segment_type="fact_table",
        text=f"Bandhan Small Cap has an expense ratio of {value}.",
        metadata={"field_name": field_name, "raw_value": value},
    )


def test_upsert_writes_to_all_three_stores():
    vec, bm, kv = InMemoryVectorIndex(), InMemoryBM25(), InMemoryFactKV()
    writer = IndexWriter(vec, bm, kv)

    chunks = [_fact_chunk("src_002#fact#expense_ratio", "expense_ratio", "0.67%")]
    embedded = _embed(chunks)

    report = writer.upsert(
        embedded,
        corpus_version="v1",
        source_id="src_002",
        source_url="https://groww.in/...",
        last_updated="2026-04-19",
    )

    assert report.chunks_upserted == 1
    assert report.bm25_writes == 1
    assert report.fact_kv_writes == 1
    assert vec.count("v1") == 1
    assert "src_002#fact#expense_ratio" in bm
    got = kv.get("src_002", "expense_ratio")
    assert got and got["value"] == "0.67%"


def test_duplicate_chunk_id_raises():
    writer = IndexWriter(InMemoryVectorIndex(), InMemoryBM25(), InMemoryFactKV())
    chunks = [
        _fact_chunk("same_id", "expense_ratio", "0.67%"),
        _fact_chunk("same_id", "expense_ratio", "0.68%"),
    ]
    embedded = _embed(chunks)

    with pytest.raises(DuplicateChunkIdError):
        writer.upsert(
            embedded, corpus_version="v1", source_id="src_002",
            source_url="u", last_updated="2026-04-19",
        )


def test_orphans_are_soft_deleted_on_next_run():
    vec, bm, kv = InMemoryVectorIndex(), InMemoryBM25(), InMemoryFactKV()
    writer = IndexWriter(vec, bm, kv)

    # Run 1: two chunks
    r1 = _embed(
        [
            _fact_chunk("src_002#fact#expense_ratio", "expense_ratio", "0.67%"),
            _fact_chunk("src_002#fact#exit_load", "exit_load", "1%"),
        ]
    )
    writer.upsert(
        r1, corpus_version="v1", source_id="src_002",
        source_url="u", last_updated="2026-04-19",
    )
    assert vec.count("v1") == 2

    # Run 2: exit_load disappears from the page
    r2 = _embed(
        [_fact_chunk("src_002#fact#expense_ratio", "expense_ratio", "0.67%")]
    )
    report = writer.upsert(
        r2, corpus_version="v1", source_id="src_002",
        source_url="u", last_updated="2026-04-20",
    )

    assert report.chunks_soft_deleted == 1
    assert vec.count("v1") == 1
    assert "src_002#fact#exit_load" not in bm


def test_fact_kv_write_skipped_for_non_fact_chunks():
    vec, bm, kv = InMemoryVectorIndex(), InMemoryBM25(), InMemoryFactKV()
    writer = IndexWriter(vec, bm, kv)

    narrative = Chunk(
        chunk_id="src_002#investment_objective#c0",
        source_id="src_002", scheme="x", section="Investment Objective",
        segment_type="section_text", text="narrative text here",
    )
    embedded = _embed([narrative])
    report = writer.upsert(
        embedded, corpus_version="v1", source_id="src_002",
        source_url="u", last_updated="d",
    )
    assert report.fact_kv_writes == 0
    assert len(kv) == 0
