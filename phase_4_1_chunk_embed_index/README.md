# Phase 4.1 — Chunk, Embed, Index, Snapshot

Implements architecture **§4.1 stages 3–8** and the full detail of **§5**: the
pipeline that consumes a `DocumentChangedEvent` from phase 4.0 and produces a
validated, versioned, queryable index.

## Position in the system

```
Phase 4.0                                Phase 4.1 (this folder)
──────────                               ─────────────────────────
scheduler → scraper → parser → validator
                                │
                                ▼  DocumentChangedEvent
                                        segmenter → chunker → normalizer
                                          → hasher → cache → embedder
                                          → index writer → snapshot/swap
                                          → live corpus_pointer
```

## Layout

```
phase_4_1_chunk_embed_index/
├── cli.py                          # `python cli.py ingest --json ...`
├── config/embedder.yaml            # provider, model, batch, caps
├── ingestion_pipeline/
│   ├── models.py                   # ParsedDocument, Chunk, EmbeddedChunk, UpsertReport
│   ├── pipeline.py                 # IngestionPipeline — orchestrator
│   ├── normalizer/                 # NFKC + ₹ + % standardization (§5.4)
│   ├── segmenter/                  # fact_table | section_text | table (§5.2)
│   ├── chunker/                    # per-segment rules (§5.3)
│   ├── hasher/                     # sha256(embed_model_id:normalized) (§5.5)
│   ├── embedding_cache/            # Protocol + in-memory impl
│   ├── embedder/                   # Fake + OpenAI + bge_local, batch/retry/cap (§5.6, §5.7)
│   ├── index_writer/               # vector + BM25 + fact KV, soft-delete (§5.8)
│   └── snapshot/                   # corpus_version + smoke-gated atomic swap (§5.9)
├── tests/                          # 29 pytest cases
└── requirements.txt
```

## Pipeline (per `DocumentChangedEvent`)

1. **Segmenter** splits the parser's structured JSON into typed segments.
2. **Chunker** applies the rule for each segment:
   - `fact_table` → one chunk per fact, sentence-templated, atomic.
   - `section_text` → 500 tokens, 80 overlap, heading-prefixed, min 100.
   - `table` → ≤ 6 rows *or* ≤ 400 tokens, header re-included per chunk.
3. **Normalizer** runs NFKC + whitespace + ₹/% standardization.
4. **Hasher** computes `sha256(embed_model_id:normalized_text)` per chunk.
5. **Embedding cache** bypasses chunks whose hash we've embedded before
   (90 %+ hit rate target in steady state).
6. **Embedder** batches cache-misses (64 at a time), 5× retry on 429/5xx with
   backoff `1s/3s/9s/27s`, hard cap 1 000 chunks/run.
7. **IndexWriter** upserts to three stores tagged with
   `corpus_version = corpus_v_<run_id>`. Orphan chunks from prior runs of
   this source are soft-deleted. Duplicate `chunk_id` collisions raise.
8. **SnapshotManager** runs canned smoke queries against the new version.
   Pointer flips **only** when the pass rate is 1.0. On failure, the new
   version is left dangling; retriever keeps serving the previous live
   version. Last 7 versions kept; older GC'd.

## Tech choices

- **Embedder provider is config-driven** (`openai` | `bge_local` | `fake`).
  The fake deterministic embedder lets tests + local dev avoid external
  calls entirely.
- **All stores use Protocol interfaces.** In-memory implementations back the
  unit tests; prod replaces them with pgvector / OpenSearch / Postgres KV
  without touching the pipeline.
- **No leaky abstractions at boundaries.** `IngestionPipeline.handle` takes
  a `ParsedDocument` and a `run_id`, returns `IngestionResult`. The caller
  (CLI, FastAPI admin endpoint, GitHub Actions step) decides how to load
  the doc and what to do with the result.

## Running locally

```bash
cd phase_4_1_chunk_embed_index
pip install -r requirements.txt
pytest tests/ -v
```

Ingesting a structured JSON file produced by phase 4.0:

```bash
python cli.py ingest \
  --json ../phase_4_scheduler_scraping/corpus/ingest_local/src_002.json \
  --source-id src_002 \
  --scheme "Bandhan Small Cap Fund Direct - Growth" \
  --source-url https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth \
  --last-updated 2026-04-19 \
  --run-id local_dev
```

## Guarantees

- **Shadow-rebuild**: every run writes into a fresh `corpus_version`; live
  pointer only flips after smoke tests pass. Worst case is stale freshness,
  never stale correctness.
- **Model-swap safety**: `embed_model_id` is part of every chunk hash, so a
  model upgrade invalidates the cache automatically. Dim mismatches between
  cache entries and the current model are hidden at retrieval time (phase 5
  responsibility).
- **Orphan cleanup**: chunks removed upstream are soft-deleted on the next
  run of their source, then hard-purged after 7 days.
- **Budget cap**: hard limit of 1 000 chunks/run prevents a parser regression
  from blowing through embedding spend.
- **Duplicate-id guard**: upsert aborts a run rather than silently
  overwriting across sources.

## What is NOT in this phase

- Retrieval + reranking (§6) — next phase.
- Generation + guardrails (§7, §8) — next phase.
- The real pgvector / OpenSearch wiring — protocol stubs live here; the
  concrete clients land when the vector DB is stood up in prod.
