from phase_4_2_prod_wiring.adapters import PgBM25Index


def test_upsert_and_contains(connect):
    ix = PgBM25Index(connect)
    ix.upsert("c1", "expense ratio is 0.67%", {"scheme": "x"})
    assert "c1" in ix
    assert ix.count() == 1


def test_upsert_replaces_on_same_chunk_id(connect, fake_db):
    ix = PgBM25Index(connect)
    ix.upsert("c1", "first text", {"scheme": "a"})
    ix.upsert("c1", "second text", {"scheme": "b"})
    assert fake_db.bm25["c1"]["text"] == "second text"
    assert fake_db.bm25["c1"]["metadata"] == {"scheme": "b"}
    assert ix.count() == 1


def test_delete_removes_doc(connect):
    ix = PgBM25Index(connect)
    ix.upsert("c1", "text", {})
    ix.delete("c1")
    assert "c1" not in ix
    assert ix.count() == 0


def test_delete_missing_is_noop(connect):
    PgBM25Index(connect).delete("nonexistent")
