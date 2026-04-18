"""Chunk hasher — §5.5.

chunk_hash = sha256(f"{embed_model_id}:{normalized_text}")

embed_model_id is part of the hash so a model swap invalidates the cache
automatically, no manual flush needed.
"""
from __future__ import annotations

import hashlib

from ..models import Chunk
from ..normalizer import normalize_for_display, normalize_for_hash


class ChunkHasher:
    def __init__(self, embed_model_id: str):
        self.embed_model_id = embed_model_id

    def apply(self, chunks: list[Chunk]) -> list[Chunk]:
        for c in chunks:
            c.normalized_text = normalize_for_display(c.text)
            hash_input = f"{self.embed_model_id}:{normalize_for_hash(c.text)}"
            c.chunk_hash = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        return chunks
