"""Phase 5 composition root — wires the phase 4.1 IngestionPipeline onto the
phase 4.2 prod backends.

Vector store backend is selected by ``config.vector_store.backend``:

  * ``chroma`` (default for prod) — Chroma Cloud (api.trychroma.com).
    Requires ``CHROMA_API_KEY`` env var. No self-hosted Postgres HNSW index
    needed; all other stores (BM25, fact_kv, embedding_cache, corpus_pointer)
    stay in Postgres.
  * ``pgvector`` — pgvector HNSW in Postgres (legacy/fallback).

This module is the single place that knows about both phase packages.
Run from the project root so both phase packages are importable:
    python -m phase_5_ingestion_cli.cli run ...
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Make project root importable (idempotent).
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---- phase 4.1 imports -------------------------------------------------------
from phase_4_1_chunk_embed_index.ingestion_pipeline import IngestionPipeline  # noqa: E402
from phase_4_1_chunk_embed_index.ingestion_pipeline.chunker import Chunker  # noqa: E402
from phase_4_1_chunk_embed_index.ingestion_pipeline.embedder import (  # noqa: E402
    CachedEmbedder,
    build_embedder,
)
from phase_4_1_chunk_embed_index.ingestion_pipeline.hasher import ChunkHasher  # noqa: E402
from phase_4_1_chunk_embed_index.ingestion_pipeline.index_writer import IndexWriter  # noqa: E402
from phase_4_1_chunk_embed_index.ingestion_pipeline.segmenter import DocumentSegmenter  # noqa: E402
from phase_4_1_chunk_embed_index.ingestion_pipeline.snapshot import SnapshotManager  # noqa: E402

# ---- phase 4.2 imports -------------------------------------------------------
from phase_4_2_prod_wiring.composition import ProdPipeline  # noqa: E402
from phase_4_2_prod_wiring.smoke import build_smoke_runner  # noqa: E402

log = logging.getLogger(__name__)


def _select_vector_index(cfg: dict):
    """Return the correct VectorIndex implementation based on config.

    ``cfg`` is the top-level config dict (env-vars already expanded).
    Falls back to ``pgvector`` when ``vector_store`` key is absent so existing
    prod.yaml files (phase 4.2) keep working without modification.
    """
    vs_cfg = cfg.get("vector_store", {})
    backend = vs_cfg.get("backend", "pgvector")

    if backend == "chroma":
        from .adapters import ChromaVectorIndex
        chroma_cfg = vs_cfg.get("chroma", {})
        api_key = chroma_cfg.get("api_key", "")
        if not api_key:
            raise ValueError(
                "vector_store.chroma.api_key is required when backend=chroma. "
                "Set CHROMA_API_KEY in the environment."
            )
        log.info(
            "vector backend: Chroma Cloud (collection=%s)",
            chroma_cfg.get("collection", "mf_rag"),
        )
        return ChromaVectorIndex(
            api_key=api_key,
            collection_name=chroma_cfg.get("collection", "mf_rag"),
            tenant=chroma_cfg.get("tenant", "default_tenant"),
            database=chroma_cfg.get("database", "default_database"),
        )

    # pgvector (default / fallback)
    log.info("vector backend: pgvector (Postgres HNSW)")
    return None   # sentinel → caller uses prod.vector_index (PgVectorIndex)


def build_ingestion_pipeline(prod: ProdPipeline) -> IngestionPipeline:
    """Wire prod backends into a ready-to-use IngestionPipeline.

    Configuration is read from ``prod.config`` (env-vars already expanded by
    ``build_prod_pipeline``).  The vector backend is selected here; everything
    else (BM25, fact_kv, embedding_cache, corpus_pointer) always comes from
    Postgres via the phase 4.2 adapters.

    Injection point for tests: pass a ``ProdPipeline`` whose adapters are
    in-memory fakes — no real Postgres, S3, or Chroma needed.
    """
    cfg = prod.config
    embedder_cfg = cfg.get("embedder", {})
    snapshot_cfg = cfg.get("snapshot", {})

    # --- vector backend selection ------------------------------------------
    chroma_index = _select_vector_index(cfg)
    vector_index = chroma_index if chroma_index is not None else prod.vector_index

    # When using Chroma, rebuild the smoke runner bound to the Chroma index
    # (the runner in prod.smoke_runner is bound to PgVectorIndex).
    if chroma_index is not None:
        smoke_runner = build_smoke_runner(
            cfg.get("smoke", {}), chroma_index, prod.fact_kv
        )
    else:
        smoke_runner = prod.smoke_runner

    # --- embedder ----------------------------------------------------------
    embedder_impl = build_embedder(embedder_cfg)
    cached_embedder = CachedEmbedder(
        embedder=embedder_impl,
        cache=prod.embedding_cache,
        batch_size=int(embedder_cfg.get("batch_size", 64)),
        retry_backoff_s=tuple(embedder_cfg.get("retry_backoff_seconds", [1, 3, 9, 27])),
        max_attempts=int(embedder_cfg.get("max_attempts", 5)),
        hard_cap=int(embedder_cfg.get("hard_cap_per_run", 1000)),
    )

    # --- index writer (three stores) --------------------------------------
    index_writer = IndexWriter(
        vector=vector_index,           # Chroma Cloud or PgVectorIndex
        bm25=prod.bm25_index,          # always Postgres FTS
        fact_kv=prod.fact_kv,          # always Postgres
    )

    # --- snapshot manager -------------------------------------------------
    keep_versions = int(snapshot_cfg.get("keep_versions", 7))

    def _gc_versions(versions: list[str]) -> None:
        # Soft-deleted rows for old versions are hard-purged by the `purge`
        # CLI subcommand (§5.8). Log for audit trail only.
        log.info("GC notified of old corpus versions to drop: %s", versions)

    snapshot_manager = SnapshotManager(
        pointer=prod.corpus_pointer,   # Postgres single-row pointer
        smoke_queries=[],              # structural runner ignores queries
        smoke_runner=smoke_runner,
        keep_versions=keep_versions,
        gc=_gc_versions,
    )

    return IngestionPipeline(
        segmenter=DocumentSegmenter(),
        chunker=Chunker(),
        hasher=ChunkHasher(embed_model_id=embedder_impl.model_id),
        embedder=cached_embedder,
        index_writer=index_writer,
        snapshot_manager=snapshot_manager,
    )
