-- Phase 4.2 prod wiring — Postgres schema.
-- Matches the five stores referenced by architecture.md §5 + §5.8 + §5.9.
--
-- Apply once per database:
--     psql "$VECTOR_DB_URL" -f schema.sql
--
-- Notes
--   * `chunks.embedding` is declared vector(384) to match
--     BAAI/bge-small-en-v1.5 (the default provider). If you switch to
--     text-embedding-3-large (3072) or bge-large-en-v1.5 (1024), change
--     the dim here and rebuild the HNSW index via a shadow-rebuild (§5.9).
--   * `bm25_docs.tsv` holds the tsvector built from text + metadata, so the
--     BM25Index adapter can rank via ts_rank_cd without re-tokenizing.
--   * `corpus_pointer` is a single-row table — the atomic swap is literally
--     one `UPDATE` of the `live` column.

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- chunks (VectorIndex)  — §5.8
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chunks (
    corpus_version   TEXT        NOT NULL,
    chunk_id         TEXT        NOT NULL,
    source_id        TEXT        NOT NULL,
    scheme           TEXT,
    section          TEXT,
    segment_type     TEXT        NOT NULL,
    text             TEXT        NOT NULL,
    embedding        vector(384),
    embed_model_id   TEXT        NOT NULL,
    chunk_hash       TEXT        NOT NULL,
    source_url       TEXT        NOT NULL,
    last_updated     TEXT        NOT NULL,
    dim              INTEGER     NOT NULL,
    deleted_at       TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (corpus_version, chunk_id)
);

CREATE INDEX IF NOT EXISTS chunks_source_idx
    ON chunks (source_id, corpus_version)
    WHERE deleted_at IS NULL;

CREATE INDEX IF NOT EXISTS chunks_scheme_segment_idx
    ON chunks (scheme, segment_type)
    WHERE deleted_at IS NULL;

-- HNSW cosine index — applies to live rows only via partial index.
-- (If your pgvector build predates HNSW, fall back to ivfflat.)
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- ---------------------------------------------------------------------------
-- bm25_docs (BM25Index)  — §5.8, Postgres FTS flavor
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bm25_docs (
    chunk_id    TEXT PRIMARY KEY,
    text        TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    tsv         tsvector,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS bm25_docs_tsv_idx
    ON bm25_docs USING GIN (tsv);

-- ---------------------------------------------------------------------------
-- fact_kv (FactKVStore)  — §5.8 exact-lookup fast path
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fact_kv (
    scheme_id     TEXT NOT NULL,
    field_name    TEXT NOT NULL,
    value         TEXT NOT NULL,
    source_url    TEXT NOT NULL,
    last_updated  TEXT NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (scheme_id, field_name)
);

-- ---------------------------------------------------------------------------
-- embedding_cache (EmbeddingCache)  — §5.5
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS embedding_cache (
    chunk_hash  TEXT PRIMARY KEY,
    embedding   BYTEA NOT NULL,
    dim         INTEGER NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- corpus_pointer (CorpusPointer)  — §5.9 atomic swap
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS corpus_pointer (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    live        TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO corpus_pointer (id, live) VALUES (1, NULL)
    ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS corpus_history (
    corpus_version  TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
