"""Embedder — §5.6 + §5.7.

Primary: BAAI/bge-small-en-v1.5 (384 dim) via sentence-transformers.
Fallback: OpenAI text-embedding-3-large (3072 dim) — set provider=openai in config.
Deterministic fake: for tests, avoids any external call.

Batching, retry/backoff, and hard cap live in `CachedEmbedder`, which wraps
the concrete embedder and the cache.
"""
from __future__ import annotations

import hashlib
import logging
import struct
import time
from typing import Protocol

from ..embedding_cache import EmbeddingCache
from ..models import Chunk, EmbeddedChunk

log = logging.getLogger(__name__)


class EmbeddingBudgetExceeded(Exception):
    """Raised when chunks_embedded exceeds the per-run cap (§5.7)."""


class EmbedderProtocol(Protocol):
    model_id: str
    dim: int

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


class FakeDeterministicEmbedder:
    """Produces repeatable pseudo-embeddings from SHA-256 of the text.

    Used by tests so we never hit OpenAI. The vectors are L2-normalized so
    cosine scores behave the same way real ones do.
    """

    def __init__(self, dim: int = 64, model_id: str = "fake/deterministic@v1"):
        self.dim = dim
        self.model_id = model_id

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # Expand hash into dim floats via SHA-256 chaining.
        raw = bytearray()
        block = h
        while len(raw) < self.dim * 4:
            block = hashlib.sha256(block).digest()
            raw.extend(block)
        floats = [
            struct.unpack_from("f", raw, i * 4)[0] / 1e38  # tame the magnitude
            for i in range(self.dim)
        ]
        # L2 normalize
        norm = (sum(x * x for x in floats) ** 0.5) or 1.0
        return [x / norm for x in floats]


class CachedEmbedder:
    """Applies the cache (§5.5) and batches cache-misses through the embedder."""

    def __init__(
        self,
        embedder: EmbedderProtocol,
        cache: EmbeddingCache,
        batch_size: int = 64,
        retry_backoff_s: tuple[float, ...] = (1, 3, 9, 27),
        max_attempts: int = 5,
        hard_cap: int = 1000,
        sleep=time.sleep,
    ):
        self.embedder = embedder
        self.cache = cache
        self.batch_size = batch_size
        self.retry_backoff = retry_backoff_s
        self.max_attempts = max_attempts
        self.hard_cap = hard_cap
        self.sleep = sleep

        # Counters exposed for metrics (§5.11)
        self.cache_hits = 0
        self.api_embeds = 0

    def embed(self, chunks: list[Chunk]) -> list[EmbeddedChunk]:
        if len(chunks) > self.hard_cap:
            raise EmbeddingBudgetExceeded(
                f"{len(chunks)} chunks exceed the {self.hard_cap}-chunk/run cap"
            )

        for c in chunks:
            if c.chunk_hash is None:
                raise ValueError(
                    f"chunk {c.chunk_id} has no chunk_hash — run ChunkHasher first"
                )

        hashes = [c.chunk_hash for c in chunks]
        cached = self.cache.get_many(h for h in hashes if h is not None)

        # Split chunks into cached vs needs-embedding
        misses: list[Chunk] = []
        for c in chunks:
            if c.chunk_hash in cached:
                self.cache_hits += 1
            else:
                misses.append(c)

        # Batch embed misses
        new_rows: dict[str, tuple[list[float], int]] = {}
        for batch_start in range(0, len(misses), self.batch_size):
            batch = misses[batch_start : batch_start + self.batch_size]
            texts = [c.normalized_text or c.text for c in batch]
            vectors = self._embed_with_retry(texts)
            for c, v in zip(batch, vectors):
                assert c.chunk_hash is not None
                new_rows[c.chunk_hash] = (v, self.embedder.dim)
                self.api_embeds += 1

        if new_rows:
            self.cache.put_many(new_rows)

        # Assemble final result in original order
        combined = {**cached, **new_rows}
        out: list[EmbeddedChunk] = []
        for c in chunks:
            if c.chunk_hash is None:
                continue
            vec, dim = combined[c.chunk_hash]
            out.append(
                EmbeddedChunk(
                    chunk=c,
                    embedding=vec,
                    embed_model_id=self.embedder.model_id,
                    dim=dim,
                )
            )
        return out

    def _embed_with_retry(self, texts: list[str]) -> list[list[float]]:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                return self.embedder.embed_batch(texts)
            except Exception as e:
                last_exc = e
                if attempt >= self.max_attempts:
                    break
                delay = self.retry_backoff[
                    min(attempt - 1, len(self.retry_backoff) - 1)
                ]
                log.warning(
                    "embed batch failed (%d/%d): %s — sleeping %ss",
                    attempt, self.max_attempts, e, delay,
                )
                self.sleep(delay)
        raise RuntimeError(f"embedding retries exhausted: {last_exc}") from last_exc


def build_embedder(config: dict) -> EmbedderProtocol:
    """Factory keyed by config.embedder.provider (§5.6)."""
    provider = config.get("provider", "fake")
    if provider == "fake":
        return FakeDeterministicEmbedder(
            dim=config.get("dim", 64),
            model_id=config.get("model", "fake/deterministic@v1"),
        )
    if provider == "openai":
        return _OpenAIEmbedder(
            model=config["model"],
            dim=config["dim"],
        )
    if provider == "bge_local":
        return _BGELocalEmbedder(
            model=config.get("model", "BAAI/bge-small-en-v1.5"),
            dim=config.get("dim", 384),
        )
    raise ValueError(f"unknown embedder provider: {provider}")


class _OpenAIEmbedder:
    """Thin wrapper; imports openai lazily so phase-4.1 can be exercised
    without installing the client. Not covered by unit tests."""

    def __init__(self, model: str, dim: int):
        self.model_id = f"openai/{model}@2024-01"
        self.dim = dim
        self._model = model

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        import openai  # type: ignore
        client = openai.OpenAI()
        resp = client.embeddings.create(model=self._model, input=texts)
        return [r.embedding for r in resp.data]


class _BGELocalEmbedder:
    def __init__(self, model: str, dim: int):
        self.model_id = f"bge_local/{model}@v1"
        self.dim = dim
        self._model_name = model
        self._model = None  # lazy

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            # backend="torch" avoids ONNX Runtime memory-mapping which fails on
            # Windows systems with small paging files (os error 1455).
            self._model = SentenceTransformer(self._model_name, backend="torch")
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]
