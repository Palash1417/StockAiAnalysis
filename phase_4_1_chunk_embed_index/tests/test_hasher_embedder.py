import pytest

from ingestion_pipeline.embedder import (
    CachedEmbedder,
    EmbeddingBudgetExceeded,
    FakeDeterministicEmbedder,
)
from ingestion_pipeline.embedding_cache import InMemoryEmbeddingCache
from ingestion_pipeline.hasher import ChunkHasher
from ingestion_pipeline.models import Chunk


def _chunk(cid: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=cid, source_id="src_001", scheme="x",
        section=None, segment_type="section_text", text=text,
    )


# ---------------------------------------------------------------------------
# Hasher — §5.5
# ---------------------------------------------------------------------------
def test_hash_differs_when_embed_model_id_differs():
    c = _chunk("c1", "Expense ratio is 0.67%.")
    h1 = ChunkHasher(embed_model_id="openai/m@v1").apply([c])[0].chunk_hash
    c2 = _chunk("c1", "Expense ratio is 0.67%.")
    h2 = ChunkHasher(embed_model_id="openai/m@v2").apply([c2])[0].chunk_hash
    assert h1 != h2


def test_hash_stable_for_identical_text_and_model():
    hasher = ChunkHasher(embed_model_id="m")
    h1 = hasher.apply([_chunk("c1", "same text")])[0].chunk_hash
    h2 = hasher.apply([_chunk("c2", "same text")])[0].chunk_hash
    # Different chunk_ids but same content → identical hash
    assert h1 == h2


def test_hash_ignores_case_and_whitespace():
    hasher = ChunkHasher(embed_model_id="m")
    h1 = hasher.apply([_chunk("a", "Hello   World")])[0].chunk_hash
    h2 = hasher.apply([_chunk("b", "hello world")])[0].chunk_hash
    assert h1 == h2


# ---------------------------------------------------------------------------
# Embedder — §5.6 + §5.7
# ---------------------------------------------------------------------------
def test_cache_hit_on_second_run():
    cache = InMemoryEmbeddingCache()
    emb = FakeDeterministicEmbedder(dim=16)
    cached = CachedEmbedder(
        embedder=emb, cache=cache,
        retry_backoff_s=(0,), max_attempts=1,
    )

    chunks = [_chunk(f"c{i}", f"text {i}") for i in range(3)]
    ChunkHasher(emb.model_id).apply(chunks)

    cached.embed(chunks)
    assert cached.api_embeds == 3
    assert cached.cache_hits == 0

    cached.api_embeds = 0
    cached.cache_hits = 0
    cached.embed(chunks)
    assert cached.api_embeds == 0
    assert cached.cache_hits == 3


def test_cache_invalidated_on_model_change():
    cache = InMemoryEmbeddingCache()
    emb_v1 = FakeDeterministicEmbedder(dim=16, model_id="fake@v1")
    emb_v2 = FakeDeterministicEmbedder(dim=16, model_id="fake@v2")

    chunks = [_chunk("c1", "expense ratio is 0.67%")]
    ChunkHasher(emb_v1.model_id).apply(chunks)
    CachedEmbedder(emb_v1, cache, retry_backoff_s=(0,), max_attempts=1).embed(chunks)

    # Re-hash for new model, cache must miss
    chunks_v2 = [_chunk("c1", "expense ratio is 0.67%")]
    ChunkHasher(emb_v2.model_id).apply(chunks_v2)
    assert chunks_v2[0].chunk_hash not in cache._store  # type: ignore[attr-defined]


def test_hard_cap_enforced():
    cache = InMemoryEmbeddingCache()
    emb = FakeDeterministicEmbedder(dim=8)
    cached = CachedEmbedder(
        embedder=emb, cache=cache, hard_cap=5,
        retry_backoff_s=(0,), max_attempts=1,
    )
    chunks = [_chunk(f"c{i}", f"t{i}") for i in range(6)]
    ChunkHasher(emb.model_id).apply(chunks)
    with pytest.raises(EmbeddingBudgetExceeded):
        cached.embed(chunks)


def test_retry_then_success(monkeypatch):
    cache = InMemoryEmbeddingCache()

    calls = {"n": 0}

    class Flaky:
        model_id = "fake@flaky"
        dim = 4

        def embed_batch(self, texts):
            calls["n"] += 1
            if calls["n"] < 3:
                raise RuntimeError("429")
            return [[0.1, 0.2, 0.3, 0.4]] * len(texts)

    cached = CachedEmbedder(
        embedder=Flaky(), cache=cache,
        retry_backoff_s=(0, 0, 0, 0),
        max_attempts=5,
        sleep=lambda s: None,
    )
    chunks = [_chunk("c1", "ok")]
    ChunkHasher("fake@flaky").apply(chunks)
    out = cached.embed(chunks)
    assert len(out) == 1
    assert calls["n"] == 3


def test_retry_exhausted_raises():
    class AlwaysFails:
        model_id = "fake@dead"
        dim = 4

        def embed_batch(self, texts):
            raise RuntimeError("permanent")

    cached = CachedEmbedder(
        embedder=AlwaysFails(), cache=InMemoryEmbeddingCache(),
        retry_backoff_s=(0,), max_attempts=2, sleep=lambda s: None,
    )
    chunks = [_chunk("c1", "x")]
    ChunkHasher("fake@dead").apply(chunks)
    with pytest.raises(RuntimeError, match="retries exhausted"):
        cached.embed(chunks)
