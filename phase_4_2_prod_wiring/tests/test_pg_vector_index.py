from phase_4_2_prod_wiring.adapters import PgVectorIndex


def _row(chunk_id: str, source_id: str = "src_001", cv: str = "corpus_v1"):
    return {
        "corpus_version": cv,
        "chunk_id": chunk_id,
        "source_id": source_id,
        "scheme": "S",
        "section": None,
        "segment_type": "fact_table",
        "text": "hello",
        "embedding": [0.1, 0.2, 0.3],
        "embed_model_id": "fake/deterministic@v1",
        "chunk_hash": "hash-" + chunk_id,
        "source_url": "https://groww.in/x",
        "last_updated": "2026-04-19",
        "dim": 3,
    }


def test_upsert_and_count(connect):
    ix = PgVectorIndex(connect)
    ix.upsert([_row("a"), _row("b")])
    assert ix.count("corpus_v1") == 2


def test_upsert_is_idempotent(connect):
    ix = PgVectorIndex(connect)
    ix.upsert([_row("a")])
    ix.upsert([_row("a")])  # same chunk_id, same corpus_version
    assert ix.count("corpus_v1") == 1


def test_chunk_ids_for_source_scoped_by_corpus_version(connect):
    ix = PgVectorIndex(connect)
    ix.upsert(
        [
            _row("a", source_id="src_001", cv="corpus_v1"),
            _row("b", source_id="src_001", cv="corpus_v1"),
            _row("c", source_id="src_002", cv="corpus_v1"),
            _row("d", source_id="src_001", cv="corpus_v2"),
        ]
    )
    assert set(ix.chunk_ids_for_source("src_001", "corpus_v1")) == {"a", "b"}
    assert set(ix.chunk_ids_for_source("src_001", "corpus_v2")) == {"d"}


def test_soft_delete_skips_already_deleted(connect):
    ix = PgVectorIndex(connect)
    ix.upsert([_row("a"), _row("b")])
    assert ix.soft_delete(["a"]) == 1
    # Second soft_delete on same id is a no-op
    assert ix.soft_delete(["a"]) == 0
    assert ix.count("corpus_v1") == 1


def test_distinct_source_ids_ignores_deleted(connect):
    ix = PgVectorIndex(connect)
    ix.upsert(
        [
            _row("a", source_id="src_001"),
            _row("b", source_id="src_002"),
            _row("c", source_id="src_003"),
        ]
    )
    ix.soft_delete(["b"])
    assert ix.distinct_source_ids("corpus_v1") == ["src_001", "src_003"]


def test_empty_upsert_is_noop(connect):
    PgVectorIndex(connect).upsert([])


def test_empty_soft_delete_is_noop(connect):
    assert PgVectorIndex(connect).soft_delete([]) == 0


def test_embedding_serialized_when_list_passed(connect, fake_db):
    ix = PgVectorIndex(connect)
    ix.upsert([_row("a")])
    stored = fake_db.chunks[("corpus_v1", "a")]["embedding"]
    assert isinstance(stored, str)
    assert stored.startswith("[") and stored.endswith("]")


def test_embedding_passthrough_when_string_passed(connect, fake_db):
    ix = PgVectorIndex(connect)
    row = _row("a")
    row["embedding"] = "[0.5,0.5]"
    ix.upsert([row])
    assert fake_db.chunks[("corpus_v1", "a")]["embedding"] == "[0.5,0.5]"
