# CLAUDE.md — Project Context

Primary reference for future sessions in `RAG-ChatBOT`. Source-of-truth docs live in `doc/doc.md` (problem statement) and `doc/architecture.md` (detailed architecture). This file is the condensed working brief.

**Implementation status:** Phases 4.0 (scheduler + scraping), 4.1 (chunk/embed/index/snapshot), 4.2 (prod wiring: pgvector + Postgres FTS + S3/MinIO adapters), **5** (ingestion CLI — wires 4.1 + 4.2, hard-purge cron), and **6** (hybrid retrieval — dense + BM25 + RRF + rerank + query rewrite) are coded and tested. Generation (§7), guardrails (§8), session store, and UI are **not yet implemented** — they remain design-only in `doc/architecture.md`.

---

## 1. What we are building

A **facts-only Mutual Fund FAQ Assistant** using RAG. Answers objective queries about mutual fund schemes (expense ratio, exit load, min SIP, lock-in, benchmark, riskometer, how-to-download-statement, etc.) from a curated corpus. No advice, no recommendations, no performance/return calculations.

**Reference product context:** Groww.

**Target users:** retail investors comparing schemes; customer-support/content teams handling repetitive queries.

---

## 2. Hard rules (non-negotiable)

- **Facts-only** — never offer opinions, recommendations, or comparisons of "which fund is better".
- **Max 3 sentences** per answer.
- **Exactly one citation link** per answer (highest-ranked source).
- **Footer required**: `Last updated from sources: <YYYY-MM-DD>`.
- **Refuse** advisory / out-of-scope queries politely with a relevant AMFI/SEBI educational link.
- **No PII**: do not collect/store/process PAN, Aadhaar, account numbers, OTPs, email, or phone. Strip on input.
- **No computed returns** — for performance questions, link to the scheme's Groww page only.
- **UI disclaimer (sticky):** `Facts-only. No investment advice.`

---

## 3. Corpus (current iteration)

**HTML only — no PDFs ingested yet.** Three Groww scheme pages (Direct-Growth):

| ID      | Scheme                                         | Category             | URL |
|---------|------------------------------------------------|----------------------|-----|
| src_001 | Nippon India Taiwan Equity Fund Direct - Growth | International Equity | https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth |
| src_002 | Bandhan Small Cap Fund Direct - Growth          | Small-Cap Equity     | https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth |
| src_003 | HDFC Mid Cap Fund Direct - Growth               | Mid-Cap Equity       | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

Registry lives in `sources.yaml` with `source_class: groww`, `type: scheme_page`, `fetched_at`, `checksum`.

**Fields extracted per page:** scheme metadata, expense ratio, exit load, min SIP / lumpsum, lock-in, riskometer, benchmark, fund manager, launch date, AUM, disclaimers.

**Caveat:** Groww is a distributor, not the issuing AMC. Treat as interim ground truth until official AMC/AMFI/SEBI sources are added (v0.4).

---

## 4. High-level architecture

```
UI (Next.js) → FastAPI (thread mgr, session, rate limit)
              ↘ Guardrails (PII, intent, injection)
              ↘ RAG pipeline (rewrite → retrieve → rerank → generate → validate)
                     ↘ Vector DB + BM25 + Fact KV store
                              ↑
                    Ingestion Pipeline (chunk → embed → index → snapshot/swap)
                              ↑  DocumentChangedEvent
                    Scraping Service (Playwright fetch, parse, checksum diff)
                              ↑  trigger 09:00 IST daily
                    Scheduler: GitHub Actions workflow
                              ↑
                    Sources: 3 Groww scheme URLs
```

---

## 5. Scheduler — GitHub Actions (implemented)

Code: `.github/workflows/ingest.yml`, `.github/workflows/retry-failed-ingest.yml`.

- **Workflow:** `.github/workflows/ingest.yml`.
- **Cron:** `45 3 * * *` UTC = **09:15 IST daily** (GitHub Actions is UTC-only; IST = UTC+5:30).
- **Pipeline:** runs `python phase_4_3_push_to_chroma/run.py` — single script that scrapes all 3 Groww URLs, chunks, embeds (BAAI/bge-small-en-v1.5 via PyTorch), and upserts vectors to Chroma Cloud. No Postgres required.
- **Manual trigger:** `workflow_dispatch` with `force` bool input (re-scrapes even if content unchanged).
- **Singleton:** `concurrency: { group: ingest-groww, cancel-in-progress: false }` — queues, never overlaps.
- **Timeout:** `timeout-minutes: 30`.
- **Retry:** companion `retry-failed-ingest.yml` listens on `workflow_run: failure` + `schedule` event, re-dispatches up to 2× with 15 min delay (`sleep 900`).
- **Secrets required (GitHub encrypted secrets):** `GROQ_API_KEY`, `CHROMA_API_KEY`, `CHROMA_TENANT` (UUID from Chroma Cloud dashboard), `CHROMA_DATABASE`, `SLACK_WEBHOOK`.
- **Model cache:** HuggingFace cache (`~/.cache/huggingface`) persisted between runs via `actions/cache` (key: `hf-bge-small-en-v1.5-v1`) — avoids 130 MB re-download on every run.
- **State:** Chroma Cloud holds all vector state; runner FS is ephemeral. `ingest_report.json` uploaded as artifact (90-day retention).
- **Observability:** ingest report artifact per run; Slack alert on failure. OTLP metrics export is design-only (not wired).
- **Delay caveat:** GitHub may delay scheduled runs up to 15 min → valid window is 09:15–09:30 IST.

---

## 6. Scraping Service (implemented)

Code: `phase_4_scheduler_scraping/scraping_service/`. Runs as a step inside the `ingest` GitHub Actions job.

- **Entrypoint:** `ScrapingService.run(run_id, source_ids=None, force=False) → ScrapeReport` in `service.py`.
- **Fetch:** `fetcher/fetcher.py` — `Fetcher` class uses Playwright (headless Chromium, `wait_until="networkidle"`, anchor selector `Expense Ratio`, 30 s nav timeout) with `httpx` fallback on timeout; `RobotsCache` (24 h per-host TTL) raises `FetchError` on disallow.
- **Politeness:** `rate_limit.py` — `TokenBucketRateLimiter` 1 req / 3 s + uniform 0–60 s jitter, UA = `MutualFundFAQBot/1.0 (+contact: ops@example.com)`.
- **Parser:** `parser/groww_parser.py` — `GrowwSchemePageParser` extracts 10 fact labels (expense_ratio, exit_load, min_sip, min_lumpsum, lock_in, risk, benchmark, fund_manager, aum, launch_date) plus narrative sections (h1–h3) and HTML tables (caption, headers, rows).
- **Per-URL retry:** 3× exponential backoff (2 s, 8 s, 30 s) — `_fetch_with_retry`.
- **Circuit breaker:** `CircuitBreakerOpen` raised if > 50 % of URLs fail; keep previous snapshot live.
- **Selector-drift alert:** logs error if avg `extraction_ratio` < 0.7 across tracked fields.
- **Checksum diff:** SHA-256 on raw HTML → unchanged sources skip downstream work (unless `force=True`).
- **Validation:** `validator/validator.py` — required fields (scheme, expense_ratio, exit_load) missing → `degraded`, HTML persisted but JSON not persisted, no event emitted.
- **Persist:** `persistence/storage.py` — `LocalStorage` writes raw HTML to `corpus/<run_id>/<source_id>.html`, structured JSON to `corpus/<run_id>/<source_id>.json`, report to `artifacts/scrape_report.json`. Prod swap-in: S3/MinIO adapter (not yet coded).
- **Output:** `ScrapeReport` (run_id, started_at, finished_at, results, summary) with per-URL `changed | unchanged | degraded | failed` status.
- **Emits:** `DocumentChangedEvent` (run_id, source_id, source_url, scheme, structured_json_path, html_path, checksum, emitted_at) to the chunk/embed pipeline **only for changed sources**.
- **CLI exit codes:** 0 clean, 1 any source failed, 2 `CircuitBreakerOpen`.

---

## 7. Chunking & Embedding (implemented)

Code: `phase_4_1_chunk_embed_index/ingestion_pipeline/`. Orchestrator: `IngestionPipeline.handle(doc, run_id) → IngestionResult` in `pipeline.py`. Entrypoint: `python cli.py ingest --json … --source-id … --scheme … --source-url … --last-updated … --run-id …`.

### Segmenter → 3 segment types
- `fact_table` — key-value pairs (expense ratio, exit load, min SIP, …). Atomic.
- `section_text` — narrative prose. Semantic chunking.
- `table` — row-based (holdings, year-wise returns). Row-aware.

### Chunking rules
- **fact_table**: one chunk per fact, wrapped in sentence template (`"{scheme} has an expense ratio of 0.67%."`). `chunk_id = {source_id}#fact#{field_name}`.
- **section_text**: 500-token target, 80-token overlap, `tiktoken cl100k_base`. Recursive splitter on `"\n## "`, `"\n### "`, `"\n\n"`, `"\n"`, `". "`, `" "`. Heading propagated as prefix. Min size 100 tokens (merge else). `chunk_id = {source_id}#{section_slug}#c{index}`.
- **table**: ≤ 6 rows or ≤ 400 tokens per chunk, header re-included in every chunk, serialized as Markdown. `chunk_id = {source_id}#table_{slug}#rows_{start}-{end}`.

### Normalization (pre-hash, pre-embed)
NFKC → whitespace collapse → `₹` standardization → `%` standardization → lowercase for hashing only. Deliberately light — no stemming/stopword removal.

### Cache-aware embedding
```
chunk_hash = sha256(f"{embed_model_id}:{normalized_text}")
```
`embed_model_id` is part of the hash → model upgrade automatically invalidates cache. Postgres table `embedding_cache(chunk_hash PK, embedding BYTEA, dim INT, created_at)`. Steady-state cache hit target > 90 %.

### Embedder
- **Factory:** `embedder/build_embedder.py` — `build_embedder(config)` dispatches on `provider` ∈ {`fake`, `openai`, `bge_local`}.
- **Primary:** `BAAI/bge-small-en-v1.5` (384 dim) via `sentence-transformers` — runs locally, no API key needed.
- **Optional alternative:** OpenAI `text-embedding-3-large` (3072 dim) — set `provider: openai` in config.
- **Test/dev default:** `FakeDeterministicEmbedder` (64 dim, model_id `fake/deterministic@v1`) — SHA-based deterministic vectors, L2-normalized, no network.
- **Config:** `config/embedder.yaml` — `provider`, `model`, `dim`, `batch_size=64`, `normalize=true`, `hard_cap_per_run=1000`, `retry_backoff_seconds=[1,3,9,27]`, `max_attempts=5`.
- **`CachedEmbedder` wrapper:** queries cache → batches misses (64) → `_embed_with_retry` with exponential backoff → updates cache → exposes `cache_hits`, `api_embeds` counters. Raises `RuntimeError` if attempts exhausted.
- `embed_model_id = "bge_local/BAAI/bge-small-en-v1.5@v1"` stored per row.

### Index writer — three stores
| Store      | Purpose                          | Key                         | Impl (current)                |
|------------|----------------------------------|-----------------------------|-------------------------------|
| Vector DB  | Dense retrieval (cosine)         | `chunk_id`                  | `InMemoryVectorIndex` (Protocol: `VectorIndex`) |
| BM25       | Sparse retrieval                 | `chunk_id`                  | `InMemoryBM25` (regex tokenizer `[a-z0-9]+`) |
| Fact KV    | Exact-lookup fast path           | `(scheme_id, field_name)`   | `InMemoryFactKV`              |

`IndexWriter.upsert(embedded, corpus_version, source_id, source_url, last_updated) → UpsertReport`:
1. Validates no duplicate `chunk_id` within the call (raises otherwise).
2. Writes vector rows with full metadata (chunk_id, source_id, scheme, section, segment_type, text, embedding, embed_model_id, chunk_hash, source_url, last_updated, corpus_version, dim).
3. Upserts BM25 with (text, metadata).
4. For `fact_table` segments, writes FactKV with `field_name`, `raw_value`, `source_url`, `last_updated`.
5. Soft-deletes orphans (chunks in this `(corpus_version, source_id)` not present in current batch); deletes from BM25.
6. Returns `UpsertReport(corpus_version, chunks_upserted, chunks_soft_deleted, fact_kv_writes, bm25_writes)`.

**Prod target (wired in phase 4.2):** pgvector schema `chunks(... embedding vector(384) ...)` with HNSW cosine index. Dim matches `bge-small-en-v1.5`; change to 3072 for OpenAI. Hard-purge soft-deleted rows after 7 days.

### Snapshot & atomic swap (shadow-rebuild)

Code: `snapshot/` — `SnapshotManager`, `SmokeQuery`, `CorpusPointer` Protocol, `InMemoryCorpusPointer`.

1. Writes tagged with new `corpus_version = corpus_v_<run_id>`.
2. `SnapshotManager.try_swap(version)` calls `smoke_runner(version, smoke_queries) → pass_rate`. `pass_rate < 1.0` raises `SmokeTestFailed`.
3. On success: `pointer.set_live(version)` (single-row flip).
4. On failure: new version left dangling, retriever keeps serving previous, Slack alert.
5. `_gc_old_versions()` keeps last `keep_versions=7`; calls optional `gc(to_drop)` hook. Same mechanism handles embedding-model upgrades.
6. Current smoke runner used by `cli.py` is a no-op stub (always passes) — real groundedness/citation checks land with §6–§8.

---

## 8. Retrieval & Generation (design-only — not yet implemented)

### Retrieval
- **Hybrid**: dense (cosine, top-K=20) + BM25 (top-K=20) → RRF (k=60) → top-K=15 → cross-encoder rerank (`bge-reranker-base` or Cohere Rerank v3) → top-N=5.
- **Score threshold 0.35** — below = force "not found" path.
- **Scheme/category metadata filter** applied from query understanding.
- **Query rewrite** (1 LLM call) expands abbreviations (ELSS, SIP, NAV, TER) using last 4 thread turns.
- **Source-class priority** (current): fact-table chunk > narrative chunk, tie-break on most recent `last_updated`. Future: AMC factsheet > SID > KIM > AMFI > SEBI > Groww.

### Generation
- **LLM:** Groq `llama-3.3-70b-versatile` (primary). Temperature 0.0–0.2.
- **Prompt contract:** answer only from provided context; max 3 sentences; exactly one citation; append `Last updated from sources: <date>`; return `INSUFFICIENT_CONTEXT` sentinel when chunks don't cover the question.
- **Output JSON schema:**
  ```json
  {
    "answer": "…",
    "citation_url": "https://groww.in/...",
    "last_updated": "2026-04-19",
    "confidence": 0.87,
    "used_chunk_ids": ["src_002#fact#expense_ratio"]
  }
  ```

---

## 9. Guardrails (design-only — not yet implemented)

**Input (pre-retrieval):**
1. PII scrubber (regex + NER) — PAN/Aadhaar/account/OTP/email/phone → polite refusal.
2. Intent classifier: `FACTUAL` (proceed), `ADVISORY` (refuse + AMFI/SEBI link), `PERFORMANCE_CALC` (redirect to Groww page), `OUT_OF_SCOPE` (refuse — includes schemes not in the 3-URL corpus).
3. Prompt-injection filter.

**Output (post-generation):**
1. Citation validator — URL must exist in source registry.
2. Length enforcer — ≤ 3 sentences (truncate or regenerate).
3. Advice detector — block on "should", "recommend", "better", etc.
4. Groundedness check — LLM-judge or NLI verifies each claim maps to `used_chunk_ids`; regenerate on failure.
5. Disclaimer attached once per thread in UI.

---

## 10. Multi-thread chat (design-only — not yet implemented)

- `thread_id` (UUID) per conversation. Session store: Redis (prod) / SQLite (dev), TTL 24h.
- Thread message schema stores `messages[]` with role/content/ts, plus `metadata.last_scheme`.
- Only **last 4 turns** injected into query rewrite (not into retrieval directly) to resolve coreference ("and its expense ratio?").
- Per-thread in-flight lock; async FastAPI; horizontally scalable.

---

## 11. Tech stack

| Layer            | Choice |
|------------------|--------|
| API              | FastAPI (Python 3.11) |
| Orchestration    | LangGraph or thin custom |
| Vector DB        | **Chroma Cloud** (`api.trychroma.com`) — managed HNSW, cosine similarity. Adapter: `ChromaVectorIndex` (`phase_5_ingestion_cli/adapters/`). pgvector available as fallback via `vector_store.backend: pgvector` in config. |
| Sparse index     | Postgres FTS (`tsvector` / GIN) via `PgBM25Index` |
| Fact KV          | Postgres table `fact_kv` — exact-lookup fast path |
| Embedding cache  | Postgres table `embedding_cache` (float32 BYTEA) |
| Corpus pointer   | Postgres single-row `corpus_pointer` — atomic swap |
| Embeddings       | `BAAI/bge-small-en-v1.5` 384-dim via `sentence-transformers` (primary) / OpenAI `text-embedding-3-large` (optional) |
| Reranker         | `bge-reranker-base` or Cohere Rerank v3 |
| LLM              | **Groq** `llama-3.3-70b-versatile` (primary) |
| Session store    | Redis |
| Web fetch        | Playwright (headless Chromium) + `httpx` fallback |
| Scheduler        | **GitHub Actions** (`.github/workflows/ingest.yml`, `30 3 * * *` UTC) |
| Scraping worker  | Step inside the `ingest` GitHub Actions job |
| Document store   | S3/MinIO (raw HTML snapshots); Postgres for relational stores |
| Frontend         | Next.js / React + Tailwind |
| Observability    | OpenTelemetry → Grafana / Langfuse |
| Deploy           | Docker + Fly.io / Render / AWS ECS |

---

## 12. UI spec (minimal) — design-only, not yet implemented

- Welcome banner: "Ask me factual questions about mutual fund schemes."
- **3 example chips** (tied to seed corpus):
  1. "What is the expense ratio of HDFC Mid Cap Fund Direct - Growth?"
  2. "What is the exit load for Bandhan Small Cap Fund Direct - Growth?"
  3. "What is the benchmark for Nippon India Taiwan Equity Fund Direct - Growth?"
- Sticky disclaimer: `Facts-only. No investment advice.`
- Thread sidebar + "New chat" button.
- Message bubble shows citation link + `Last updated: YYYY-MM-DD`.

---

## 13. Evaluation

- **Shipped:** 99 pytest cases — 35 across phases 4.0/4.1 + 17 phase 5 + 47 phase 6 (RRF fusion, in-memory dense/BM25, HybridRetriever pipeline, scheme filter, threshold gate, query rewrite abbrevs + LLM mock, PassthroughReranker). Run: `pytest phase_4_scheduler_scraping/tests/ phase_4_1_chunk_embed_index/tests/ phase_5_ingestion_cli/tests/ phase_6_retrieval/tests/ -v`.
- **Planned:** golden set of 50–100 Q/A pairs (expense ratio, exit load, SIP min, ELSS lock-in, riskometer, benchmark, statement download, refusal cases); metrics Recall@5, MRR, exact-fact accuracy, citation precision, groundedness %, refusal precision/recall, p50/p95 latency, tokens/query.
- **CI gate (planned):** regression suite on every ingestion refresh; blocks release if accuracy drops > 3 %.

---

## 14. Security & privacy

- No PII logged; prompts/responses hashed for analytics.
- TLS everywhere; secrets via environment / GitHub secrets / vault.
- Rate limit per IP and per thread.
- Audit log: `(thread_id, ts, query_hash, citation_url, decision)`.
- Retention: thread history 24 h, logs 30 d, raw corpus versioned indefinitely.

---

## 15. Known limitations

- Only 3 Groww scheme pages; no PDFs (factsheet/KIM/SID) yet — questions requiring them route to the Groww page or are refused.
- Groww is a distributor, not the AMC — interim ground truth.
- Lag up to ingestion interval (24 h + GitHub delay).
- Client-rendered pages require Playwright; selector drift risk monitored via alert.
- No personalized or portfolio-specific answers by design.

---

## 16. Roadmap

- **Phase 4.0 (done):** GitHub Actions scheduler + scraping service (Playwright/httpx, Groww parser, validator, rate limiter, checksum diff, circuit breaker, drift alert, `ScrapeReport`, `DocumentChangedEvent`).
- **Phase 4.1 (done):** Segmenter → chunker → normalizer → hasher → cache → embedder → index writer → snapshot manager. In-memory stores + fake deterministic embedder; protocol interfaces for prod swap-in.
- **Phase 4.2 (done):** Prod backends behind the 4.1 protocols — `PgVectorIndex` (pgvector HNSW), `PgBM25Index` (Postgres FTS tsvector), `PgFactKV`, `PgEmbeddingCache` (BYTEA), `PgCorpusPointer`, `S3Storage` (boto3/MinIO), `StructuralSmokeRunner`, composition root in [phase_4_2_prod_wiring/composition.py](phase_4_2_prod_wiring/composition.py), 39 unit tests with fake psycopg + moto.
- **Phase 5 (done):** Ingestion CLI (`phase_5_ingestion_cli/`) — `cli.py` (`run` + `purge`), `composition.py` (wires 4.1 pipeline onto 4.2 prod backends), `purge.py` (hard-purge cron for soft-deleted rows), `config/phase5.yaml`, 17 unit tests.
- **Phase 6 (done):** Hybrid retrieval — `HybridRetriever` (dense cosine + BM25/FTS + RRF k=60 + `PassthroughReranker`/`CrossEncoderReranker`), `QueryRewriter` (Groq `llama-3.3-70b-versatile` + rule-based fallback), `PgDenseRetriever`/`PgSparseRetriever` adapters, `InMemoryDenseRetriever`/`InMemoryBM25Retriever` for tests. 47 unit tests. Code: `phase_6_retrieval/`.
- **Phase 7 (done):** Generation (`phase_7_generation/`) — `Generator` (Groq `llama-3.3-70b-versatile`, JSON mode), `prompt.py` (system prompt + context formatter), `models.py` (`GenerationRequest`, `GenerationResponse`), `build_generator` factory. 48 unit tests (happy path, INSUFFICIENT_CONTEXT sentinel, LLM fallback, citation validation, confidence clamping). Code: `phase_7_generation/`.
- **Phase 8:** Guardrails (PII, intent, injection; citation/length/advice/groundedness).
- **Phase 9:** FastAPI + thread manager + Redis session store; Next.js UI.
- **Phase 10:** Observability (OTLP + Langfuse), eval harness, CI gate, expand corpus to AMC/AMFI/SEBI.

---

## 17. Request lifecycle

1. User sends query on thread `T`.
2. API: validate + PII scrub + intent classify.
3. If `ADVISORY` / `OUT_OF_SCOPE` → refusal template → return.
4. Query rewrite using last 4 turns.
5. Hybrid retrieve (dense + BM25) → RRF → rerank → top-5.
6. If top score < 0.35 → "I couldn't find this in official sources" + AMFI link.
7. Build prompt with chunks + metadata → LLM → structured JSON.
8. Output guards: citation validity, length, advice detector, groundedness.
9. Persist assistant message on thread `T`; emit telemetry.
10. Return answer + citation + `Last updated` footer to UI.

---

## 18. File map

**Docs**
- `doc/doc.md` — original problem statement (source of truth for requirements).
- `doc/architecture.md` — full architecture with implementation detail (source of truth for design).
- `doc/edgecase.md` — edge-case catalogue.
- `CLAUDE.md` — this file (condensed working brief for future sessions).

**Phase 4.0 — Scheduler + Scraping (implemented)**
- `.github/workflows/ingest.yml` — daily ingest workflow (cron `30 3 * * *`).
- `.github/workflows/retry-failed-ingest.yml` — retry-on-failure companion.
- `phase_4_scheduler_scraping/README.md` — phase overview.
- `phase_4_scheduler_scraping/config/sources.yaml` — source registry (3 Groww URLs).
- `phase_4_scheduler_scraping/config/scraper.yaml` — fetcher, retry, circuit breaker, drift thresholds.
- `phase_4_scheduler_scraping/scheduler/cli.py` — `python -m scheduler.cli run`.
- `phase_4_scheduler_scraping/scheduler/admin_trigger.py` — `dispatch_ingest()` via GitHub REST.
- `phase_4_scheduler_scraping/scraping_service/service.py` — `ScrapingService` orchestrator.
- `phase_4_scheduler_scraping/scraping_service/fetcher/fetcher.py` — Playwright + httpx + robots cache.
- `phase_4_scheduler_scraping/scraping_service/parser/groww_parser.py` — `GrowwSchemePageParser`.
- `phase_4_scheduler_scraping/scraping_service/validator/validator.py` — required-field + drift ratio.
- `phase_4_scheduler_scraping/scraping_service/persistence/storage.py` — `LocalStorage`.
- `phase_4_scheduler_scraping/scraping_service/rate_limit.py` — `TokenBucketRateLimiter`.
- `phase_4_scheduler_scraping/scraping_service/models.py` — `Source`, `ParsedDocument`, `ScrapeReport`, `DocumentChangedEvent`, ….
- `phase_4_scheduler_scraping/tests/` — 6 test files.

**Phase 4.1 — Chunk/Embed/Index/Snapshot (implemented)**
- `phase_4_1_chunk_embed_index/README.md` — phase overview.
- `phase_4_1_chunk_embed_index/cli.py` — `python cli.py ingest --json … --source-id … …`.
- `phase_4_1_chunk_embed_index/config/embedder.yaml` — provider/model/batch/cap.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/pipeline.py` — `IngestionPipeline.handle()`.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/models.py` — `Chunk`, `EmbeddedChunk`, `UpsertReport`, `IngestionResult`.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/segmenter/` — `DocumentSegmenter` (3 segment types).
- `phase_4_1_chunk_embed_index/ingestion_pipeline/chunker/` — per-segment rules.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/normalizer/` — `normalize_for_display`, `normalize_for_hash`.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/hasher/` — `ChunkHasher`.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/embedding_cache/` — Protocol + `InMemoryEmbeddingCache`.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/embedder/` — `CachedEmbedder`, `FakeDeterministicEmbedder`, `build_embedder()` factory.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/index_writer/` — `IndexWriter` + in-memory `VectorIndex`/`BM25Index`/`FactKVStore`.
- `phase_4_1_chunk_embed_index/ingestion_pipeline/snapshot/` — `SnapshotManager`, `CorpusPointer`.
- `phase_4_1_chunk_embed_index/tests/` — 6 test files (~29 cases).

**Phase 4.2 — Prod Wiring (implemented)**
- [phase_4_2_prod_wiring/README.md](phase_4_2_prod_wiring/README.md) — phase overview.
- [phase_4_2_prod_wiring/requirements.txt](phase_4_2_prod_wiring/requirements.txt) — psycopg[binary], pgvector, boto3, openai, sentence-transformers, moto.
- [phase_4_2_prod_wiring/sql/schema.sql](phase_4_2_prod_wiring/sql/schema.sql) — DDL for `chunks` (HNSW), `bm25_docs` (tsvector GIN), `fact_kv`, `embedding_cache`, `corpus_pointer` + `corpus_history`.
- [phase_4_2_prod_wiring/config/prod.yaml](phase_4_2_prod_wiring/config/prod.yaml) — `${ENV_VAR:default}` templated sample.
- [phase_4_2_prod_wiring/adapters/pg_vector_index.py](phase_4_2_prod_wiring/adapters/pg_vector_index.py) — `PgVectorIndex`.
- [phase_4_2_prod_wiring/adapters/pg_bm25_index.py](phase_4_2_prod_wiring/adapters/pg_bm25_index.py) — `PgBM25Index`.
- [phase_4_2_prod_wiring/adapters/pg_fact_kv.py](phase_4_2_prod_wiring/adapters/pg_fact_kv.py) — `PgFactKV`.
- [phase_4_2_prod_wiring/adapters/pg_embedding_cache.py](phase_4_2_prod_wiring/adapters/pg_embedding_cache.py) — `PgEmbeddingCache` (struct-packed float32 BYTEA).
- [phase_4_2_prod_wiring/adapters/pg_corpus_pointer.py](phase_4_2_prod_wiring/adapters/pg_corpus_pointer.py) — `PgCorpusPointer`.
- [phase_4_2_prod_wiring/adapters/s3_storage.py](phase_4_2_prod_wiring/adapters/s3_storage.py) — `S3Storage` (boto3 w/ `endpoint_url` for MinIO).
- [phase_4_2_prod_wiring/smoke/runner.py](phase_4_2_prod_wiring/smoke/runner.py) — `StructuralSmokeRunner` (chunk count + required sources + required facts).
- [phase_4_2_prod_wiring/composition.py](phase_4_2_prod_wiring/composition.py) — `build_prod_pipeline(config_path)` returning `ProdPipeline`.
- [phase_4_2_prod_wiring/tests/](phase_4_2_prod_wiring/tests/) — 8 test files, 39 cases; fake psycopg + moto so no real DB/S3 needed.

**Phase 5 — Ingestion CLI (implemented)**
- [phase_5_ingestion_cli/__init__.py](phase_5_ingestion_cli/__init__.py)
- [phase_5_ingestion_cli/composition.py](phase_5_ingestion_cli/composition.py) — `build_ingestion_pipeline(prod)` wiring root; selects Chroma or pgvector backend from config.
- [phase_5_ingestion_cli/adapters/chroma_vector_index.py](phase_5_ingestion_cli/adapters/chroma_vector_index.py) — `ChromaVectorIndex`: Chroma Cloud implementation of the `VectorIndex` protocol (upsert, soft-delete, hard-purge, count, distinct_source_ids).
- [phase_5_ingestion_cli/purge.py](phase_5_ingestion_cli/purge.py) — `hard_purge_deleted_chunks(vector_index, cutoff_days)`.
- [phase_5_ingestion_cli/cli.py](phase_5_ingestion_cli/cli.py) — `run` (report or single-source) + `purge` subcommands.
- [phase_5_ingestion_cli/config/phase5.yaml](phase_5_ingestion_cli/config/phase5.yaml) — prod config with env-var expansion.
- [phase_5_ingestion_cli/requirements.txt](phase_5_ingestion_cli/requirements.txt)
- [phase_5_ingestion_cli/tests/](phase_5_ingestion_cli/tests/) — 3 test files, 17 cases; fake psycopg (from 4.2 conftest), no real DB/S3.

**Phase 6 — Hybrid Retrieval (implemented)**
- [phase_6_retrieval/__init__.py](phase_6_retrieval/__init__.py)
- [phase_6_retrieval/models.py](phase_6_retrieval/models.py) — `RetrievalQuery`, `CandidateChunk`, `RetrievalResult`.
- [phase_6_retrieval/protocols.py](phase_6_retrieval/protocols.py) — `DenseRetriever`, `SparseRetriever`, `Reranker` structural protocols.
- [phase_6_retrieval/fusion.py](phase_6_retrieval/fusion.py) — `rrf_fuse(dense, sparse, k=60, top_k=15)` RRF implementation.
- [phase_6_retrieval/reranker.py](phase_6_retrieval/reranker.py) — `PassthroughReranker`, `CrossEncoderReranker` (lazy sentence-transformers), `build_reranker(config)`.
- [phase_6_retrieval/query_rewrite.py](phase_6_retrieval/query_rewrite.py) — `QueryRewriter` (Groq `llama-3.3-70b-versatile` + rule-based abbrev fallback), `expand_abbreviations()`, `build_query_rewriter(config)`.
- [phase_6_retrieval/retriever.py](phase_6_retrieval/retriever.py) — `HybridRetriever.retrieve()` orchestrating all stages.
- [phase_6_retrieval/adapters/pg_dense_retriever.py](phase_6_retrieval/adapters/pg_dense_retriever.py) — `PgDenseRetriever` (pgvector `<=>` cosine).
- [phase_6_retrieval/adapters/pg_sparse_retriever.py](phase_6_retrieval/adapters/pg_sparse_retriever.py) — `PgSparseRetriever` (Postgres FTS `ts_rank_cd`).
- [phase_6_retrieval/adapters/in_memory_retriever.py](phase_6_retrieval/adapters/in_memory_retriever.py) — `InMemoryDenseRetriever` (cosine scan) + `InMemoryBM25Retriever` (BM25 k1=1.5 b=0.75).
- [phase_6_retrieval/config/retrieval.yaml](phase_6_retrieval/config/retrieval.yaml) — retrieval config (top-k, threshold, reranker, query rewrite).
- [phase_6_retrieval/tests/](phase_6_retrieval/tests/) — 47 cases: fusion, retriever pipeline, query rewrite, reranker.

**Not yet implemented:** API (FastAPI), generation, guardrails, session store (Redis), frontend (Next.js), OTLP/Langfuse observability, eval harness.

When design questions arise, prefer `doc/architecture.md` for detail; use this file for quick recall.
@doc.md - basic understanding of project
@architecture.md - architecture of the project 