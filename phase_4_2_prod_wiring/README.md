# Phase 4.2 — Prod Wiring

Swaps phase 4.1's in-memory reference stores for production backends without
changing the pipeline protocols. The shadow-rebuild flow, cache-aware
embedder, and `IndexWriter` from phase 4.1 all continue to work — they just
see real Postgres and S3 underneath.

Implements the production side of architecture.md:
- §5.5 Embedding cache → Postgres `embedding_cache` (BYTEA).
- §5.8 Index writer → pgvector (dense) + Postgres FTS (sparse) + `fact_kv`.
- §5.9 Snapshot & atomic swap → single-row `corpus_pointer` table.
- §4.4 Storage → S3/MinIO replacing the filesystem `LocalStorage`.

## Layout

```
phase_4_2_prod_wiring/
├── adapters/
│   ├── pg_vector_index.py      # VectorIndex via pgvector (HNSW cosine)
│   ├── pg_bm25_index.py        # BM25Index via Postgres FTS (tsvector + GIN)
│   ├── pg_fact_kv.py           # FactKVStore
│   ├── pg_embedding_cache.py   # EmbeddingCache (BYTEA float32 blobs)
│   ├── pg_corpus_pointer.py    # CorpusPointer single-row atomic swap
│   └── s3_storage.py           # Storage (boto3) — works with MinIO too
├── smoke/
│   └── runner.py               # structural smoke runner for SnapshotManager
├── sql/
│   └── schema.sql              # Postgres DDL (pgvector ext + all 5 tables)
├── config/
│   └── prod.yaml               # sample config with ${ENV_VAR:default} expansion
├── composition.py              # build_prod_pipeline(config_path) → ProdPipeline
├── tests/                      # 39 unit tests (fake psycopg + moto)
└── requirements.txt
```

## Adapter contracts

Every adapter conforms to a protocol defined in phase 4.1 so the same
`IndexWriter` / `CachedEmbedder` / `SnapshotManager` code paths exercised
by phase 4.1's in-memory tests also drive the prod backends.

| Protocol (phase 4.1)  | Prod impl (phase 4.2) | Storage |
|-----------------------|-----------------------|---------|
| `VectorIndex`         | `PgVectorIndex`       | `chunks` table + pgvector HNSW |
| `BM25Index`           | `PgBM25Index`         | `bm25_docs` table + tsvector GIN |
| `FactKVStore`         | `PgFactKV`            | `fact_kv` table |
| `EmbeddingCache`      | `PgEmbeddingCache`    | `embedding_cache` table (BYTEA) |
| `CorpusPointer`       | `PgCorpusPointer`     | `corpus_pointer` (1 row) + `corpus_history` |
| `Storage`             | `S3Storage`           | S3 / MinIO object store |

## Smoke test (structural)

Retrieval + generation are still ahead (Phase 5), so `StructuralSmokeRunner`
is the best gate available today. It checks three things before the
`SnapshotManager` flips the `corpus_pointer`:

1. `min_chunks` — candidate corpus_version has ≥ N live chunks.
2. `required_sources` — every expected `source_id` is present.
3. `required_facts` — every `(scheme_id, field_name)` has a `fact_kv` row.

Any miss keeps the previous `live` version serving — matching §5.9's
fail-closed semantics.

## Setup

```bash
# 1. Install deps (assumes psycopg build prereqs are available on your box)
pip install -r requirements.txt

# 2. Provision schema (one-time)
psql "$VECTOR_DB_URL" -f sql/schema.sql

# 3. Export the env vars the prod config references
export VECTOR_DB_URL="postgresql://user:pw@host:5432/mf_rag"
export S3_BUCKET="mf-rag-corpus"
export S3_ENDPOINT_URL=""           # leave empty for real AWS S3
export AWS_REGION="ap-south-1"
```

Then in your pipeline orchestrator:

```python
from phase_4_2_prod_wiring.composition import build_prod_pipeline

pipeline = build_prod_pipeline("phase_4_2_prod_wiring/config/prod.yaml")
# pipeline.vector_index, .bm25_index, .fact_kv, .embedding_cache,
# .corpus_pointer, .storage, .smoke_runner are drop-in replacements
# for phase 4.1's in-memory stubs.
```

## Tests

```bash
pytest phase_4_2_prod_wiring/tests/ -v
```

No real Postgres or S3 required:
- A `FakeDB` in `tests/conftest.py` pattern-matches every SQL statement the
  adapters issue and stores rows in dicts.
- `moto` mocks S3 so `S3Storage` can be exercised in-process.

## Not yet wired

- Real retrieval pipeline (Phase 5) — this phase only stands up the backends
  the retriever will read from.
- Ingestion CLI entry point that calls `build_prod_pipeline(...)` and feeds
  phase 4.1's `IngestionPipeline`. Today you'd wire it yourself until the
  scheduler CLI is updated in Phase 5.
- Hard-purge job on a schedule. `PgVectorIndex.hard_purge_older_than(7)`
  exists but is not yet called from anywhere.
