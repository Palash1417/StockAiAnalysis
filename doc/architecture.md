# RAG Architecture: Mutual Fund FAQ Assistant

> **Implementation status (2026-04-19).** Phase 4.0 (scheduler + scraping), Phase 4.1 (chunk/embed/index/snapshot), Phase 4.2 (prod wiring — pgvector + Postgres FTS + fact_kv + embedding_cache + corpus_pointer + S3/MinIO), and Phase 5 (ingestion CLI — composes 4.1 + 4.2, hard-purge cron) are coded and unit-tested. Sections tagged **[IMPLEMENTED]** map to existing Python code under `phase_4_scheduler_scraping/`, `phase_4_1_chunk_embed_index/`, `phase_4_2_prod_wiring/`, and `phase_5_ingestion_cli/`. Sections tagged **[DESIGN-ONLY]** are not yet built (retrieval, generation, guardrails, API, session store, UI, evaluation). See §17 for the implementation map.

## 1. Executive Summary

This document describes a detailed Retrieval-Augmented Generation (RAG) architecture for a **facts-only Mutual Fund FAQ Assistant**. The system retrieves answers exclusively from curated, official public sources (AMC, AMFI, SEBI) and produces concise, cited, compliance-safe responses. It refuses advisory queries and supports multiple concurrent chat threads.

**Key Principles**
- Facts-only: no advice, opinions, recommendations, or computed returns.
- Source-grounded: every answer carries exactly one citation + "last updated" date.
- Constrained generation: max 3 sentences per answer.
- Multi-thread: independent conversational sessions with isolated context.
- Privacy-first: no PII collection or persistence.

---

## 2. High-Level Architecture

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                         USER INTERFACE (Web)                        │
 │   Welcome message  •  3 sample Qs  •  Disclaimer banner  •  Threads │
 └──────────────────────────────┬──────────────────────────────────────┘
                                │ HTTPS / WebSocket
 ┌──────────────────────────────▼──────────────────────────────────────┐
 │                      API / ORCHESTRATION LAYER                      │
 │  FastAPI  •  Thread Manager  •  Session Store  •  Rate Limiter      │
 └──────────────────────────────┬──────────────────────────────────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
 ┌─────────────────┐  ┌───────────────────┐  ┌────────────────────┐
 │  GUARDRAILS     │  │   RAG PIPELINE    │  │  OBSERVABILITY     │
 │  • Intent clf.  │  │  • Query rewrite  │  │  • Logs / Traces   │
 │  • PII scrubber │  │  • Retriever      │  │  • Metrics         │
 │  • Refusal gen. │  │  • Reranker       │  │  • Eval harness    │
 └─────────────────┘  │  • Generator      │  └────────────────────┘
                      │  • Citation check │
                      └────────┬──────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
   ┌──────────────┐   ┌────────────────┐   ┌─────────────────┐
   │ Vector Store │   │ Document Store │   │  LLM Provider   │
   │  (Chroma/    │   │  (Postgres /   │   │ (Claude / GPT / │
   │   Qdrant)    │   │   Object Store)│   │   local model)  │
   └──────▲───────┘   └────────▲───────┘   └─────────────────┘
          │                    │
          └────────┬───────────┘
                   │
         ┌─────────▼──────────┐
         │  INGESTION PIPELINE │
         │  Chunk → Embed →    │
         │  Index → Snapshot   │
         └─────────▲──────────┘
                   │ DocumentChangedEvent
         ┌─────────┴──────────┐
         │  SCRAPING SERVICE  │
         │  Playwright fetch  │
         │  Parse • Checksum  │
         │  Validate • Diff   │
         └─────────▲──────────┘
                   │ trigger (09:00 IST daily)
         ┌─────────┴──────────┐
         │     SCHEDULER      │
         │  cron: 0 9 * * *   │
         │  TZ: Asia/Kolkata  │
         └─────────▲──────────┘
                   │
         ┌─────────┴──────────┐
         │    SOURCES (Groww) │
         │  3 scheme URLs     │
         └────────────────────┘
```

---

## 3. Corpus & Data Sources

### 3.1 Selection (Groww scheme pages — HTML only; no PDFs provided)

The corpus is built **exclusively from Groww scheme pages** (HTML). No PDFs (factsheet/KIM/SID) are ingested in this iteration — all facts are extracted from the rendered Groww pages.

**Seed URLs (provided):**

| ID      | Scheme                                  | Category         | URL |
|---------|-----------------------------------------|------------------|-----|
| src_001 | Nippon India Taiwan Equity Fund Direct  | International Equity | https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth |
| src_002 | Bandhan Small Cap Fund Direct           | Small-Cap Equity | https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth |
| src_003 | HDFC Mid Cap Fund Direct                | Mid-Cap Equity   | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

> Note: The problem statement lists Groww as the reference **product context**. Since only Groww URLs are available, they serve as the de-facto source here; in production these should be augmented or replaced with official AMC / AMFI / SEBI pages for strict compliance.

**Content types extracted per Groww page:**
- Scheme metadata (name, AMC, category, plan/option)
- Expense ratio
- Exit load
- Minimum SIP / lumpsum amount
- Lock-in period (where applicable, e.g., ELSS)
- Riskometer classification
- Benchmark index
- Fund manager, launch date, AUM
- Any visible disclaimers / last-updated timestamps

### 3.2 Source Registry
Stored as `sources.yaml`:
```yaml
- id: src_001
  url: https://groww.in/mutual-funds/nippon-india-taiwan-equity-fund-direct-growth
  type: scheme_page
  scheme: "Nippon India Taiwan Equity Fund Direct - Growth"
  category: international_equity
  source_class: groww
  fetched_at: 2026-04-19
  checksum: sha256:...

- id: src_002
  url: https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth
  type: scheme_page
  scheme: "Bandhan Small Cap Fund Direct - Growth"
  category: small_cap
  source_class: groww
  fetched_at: 2026-04-19
  checksum: sha256:...

- id: src_003
  url: https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth
  type: scheme_page
  scheme: "HDFC Mid Cap Fund Direct - Growth"
  category: mid_cap
  source_class: groww
  fetched_at: 2026-04-19
  checksum: sha256:...
```

---

## 4. Ingestion Pipeline  **[IMPLEMENTED — phases 4.0 + 4.1]**

### 4.1 Stages

1. **Fetch** — the **Scraping Service** is triggered by the **Scheduler** (see §4.3 and §4.4) and pulls the 3 Groww scheme URLs. Because Groww pages are client-rendered, use **Playwright (headless Chromium)** to render JS before capturing HTML; fall back to `httpx` for static fragments. Respect `robots.txt` and add a polite `User-Agent` + rate limit.
2. **Parse (HTML only — no PDFs in this iteration)**
   - `BeautifulSoup` / `selectolax` to extract the rendered DOM.
   - Target known Groww selectors / labeled sections: *Expense Ratio*, *Exit Load*, *Min SIP*, *Min Lumpsum*, *Lock-in*, *Risk*, *Benchmark*, *Fund Manager*, *AUM*, *Launch Date*.
   - Extract key-value pairs into a structured "facts table" per scheme **in addition to** free-text chunks, so exact-fact queries can bypass the LLM and read the value directly.
3. **Normalize** — Unicode NFKC, whitespace collapse, unit standardization (₹, %, bps), date parsing to ISO-8601.
4. **Chunk**
   - Semantic chunking (heading / section-aware) with `chunk_size=500 tokens`, `overlap=80`.
   - Preserve fact tables as single atomic chunks — never split a key-value row.
5. **Enrich Metadata** per chunk:
   ```json
   {
     "chunk_id": "src_002#sec_expense_ratio#c1",
     "source_id": "src_002",
     "source_url": "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
     "source_class": "groww",
     "scheme": "Bandhan Small Cap Fund Direct - Growth",
     "section": "Expense Ratio",
     "last_updated": "2026-04-19",
     "doc_type": "scheme_page"
   }
   ```
6. **Embed** — `BAAI/bge-small-en-v1.5` (default) via `sentence-transformers`; batch + cache by checksum.
7. **Index** — upsert into vector store with metadata + BM25 sidecar index for hybrid search.
8. **Snapshot** — version the corpus (`corpus_v2026_04_19`) so answers are reproducible.

### 4.2 Freshness Strategy
- Re-fetch daily at 09:00 IST; compute checksum; re-embed only changed chunks.
- `last_updated` propagates into citations.
- Stale corpus warning if any source is > 48 hours old (alert on 2 consecutive missed runs).

### 4.3 Scheduler — GitHub Actions  **[IMPLEMENTED]**

**Code:** `.github/workflows/ingest.yml`, `.github/workflows/retry-failed-ingest.yml`, admin dispatch in `phase_4_scheduler_scraping/scheduler/admin_trigger.py` (`dispatch_ingest()`).

**Responsibility:** trigger the Scraping Service daily and guarantee the corpus stays fresh. Chosen implementation: **GitHub Actions scheduled workflow** (zero-infra, free tier, version-controlled with the code).

**Cron caveat:** GitHub Actions cron runs in **UTC only** and has no timezone flag. To get **09:00 IST (Asia/Kolkata = UTC+5:30)**, set cron to **`30 3 * * *`** (03:30 UTC = 09:00 IST). Also note GitHub delays scheduled runs by up to 15 min under peak load — the scheduler treats 09:00–09:20 IST as the valid window.

**Workflow file:** `.github/workflows/ingest.yml`
```yaml
name: Ingest Groww Corpus

on:
  schedule:
    - cron: "30 3 * * *"      # 09:00 IST daily (03:30 UTC)
  workflow_dispatch:            # manual trigger from the Actions UI
    inputs:
      force:
        description: "Re-embed even if checksum unchanged"
        type: boolean
        default: false

concurrency:
  group: ingest-groww
  cancel-in-progress: false     # singleton — queue instead of overlap

jobs:
  ingest:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: write            # for committing index artifacts
      id-token: write            # for OIDC auth to cloud storage
    env:
      TZ: Asia/Kolkata
      RUN_ID: ingest_${{ github.run_id }}
      GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
      VECTOR_DB_URL: ${{ secrets.VECTOR_DB_URL }}
      S3_BUCKET: ${{ secrets.S3_BUCKET }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - run: playwright install --with-deps chromium
      - name: Run scraper + ingest
        run: python -m ingest.cli run --force=${{ inputs.force || 'false' }}
      - name: Upload ScrapeReport
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: scrape-report-${{ github.run_id }}
          path: artifacts/scrape_report.json
      - name: Notify on failure
        if: failure()
        uses: slackapi/slack-github-action@v1
        with:
          payload: '{"text":"❌ Ingest failed: ${{ github.run_id }}"}'
          webhook: ${{ secrets.SLACK_WEBHOOK }}
```

**Operational behavior (GitHub Actions specifics)**
- **Singleton:** `concurrency.group: ingest-groww` ensures only one ingest job runs at a time; a new scheduled run queued while yesterday's is still executing will **wait**, not overlap.
- **Timeout:** `timeout-minutes: 20` at the job level; individual steps have their own timeouts.
- **Retry policy:** GitHub Actions doesn't retry scheduled jobs automatically. A second workflow (`retry-failed-ingest.yml`) listens to `workflow_run: completed + conclusion == failure` and re-dispatches up to 2 times with a 15 min delay.
- **Idempotency:** the scraper keys work on `RUN_ID`; re-runs of the same workflow run are no-ops unless `force=true` is passed via `workflow_dispatch`.
- **Manual trigger:** `workflow_dispatch` input `force` lets an admin force re-embedding from the Actions UI. An internal `POST /admin/ingest/run` endpoint dispatches this workflow via the GitHub REST API (`actions/workflows/ingest.yml/dispatches`).
- **Secrets:** all API keys and DB URLs via GitHub Actions encrypted secrets — never committed.
- **Observability:**
  - `ScrapeReport` uploaded as a workflow artifact (retained 90 days).
  - Metrics (`sources_changed_count`, `chunks_reembedded`, `duration_ms`) pushed to the metrics pipeline via a `statsd`/OTLP export step.
  - Slack notification on failure via webhook.
- **Audit:** every run's commit SHA, `RUN_ID`, and `ScrapeReport` are retained by GitHub (run history) + mirrored to an `ingestion_runs` table in Postgres for long-term query.
- **Cost:** 1 run/day × ~3 min ≈ 90 min/month — well within the free tier for private repos (2,000 min/month) and unlimited for public repos.

**Why GitHub Actions (trade-offs)**
- ✅ Zero infrastructure, version-controlled with the code, free tier sufficient.
- ✅ Native `workflow_dispatch` for manual runs and `concurrency` for singleton semantics.
- ⚠️ UTC-only cron + up to 15 min scheduling delay — acceptable for a daily FAQ refresh.
- ⚠️ No native retry on scheduled triggers — handled via the companion retry workflow.
- ⚠️ Ephemeral runners — all state (vector index, raw HTML) must live in external stores (S3/MinIO + vector DB), not the runner FS.

### 4.4 Scraping Service  **[IMPLEMENTED]**

**Code:** `phase_4_scheduler_scraping/scraping_service/` — `service.ScrapingService`, `fetcher.Fetcher` + `RobotsCache`, `parser.GrowwSchemePageParser`, `validator.Validator`, `persistence.LocalStorage`, `rate_limit.TokenBucketRateLimiter`, `models.{Source,ParsedDocument,ScrapeResult,ScrapeReport,DocumentChangedEvent}`. CLI: `phase_4_scheduler_scraping/scheduler/cli.py` (`python -m scheduler.cli run`).

**Responsibility:** given the source registry (§3.2), fetch each URL, produce normalized documents, and hand them to the chunking + embedding stages. Runs as an isolated, stateless worker so it can be invoked by the scheduler, a queue, or a CLI.

**Interface**
```python
class ScrapingService:
    def run(self, source_ids: list[str] | None = None, force: bool = False) -> ScrapeReport:
        """Fetch + parse each source. Returns per-URL status and diff vs. last snapshot."""
```

**Execution flow (per URL)**
1. **Load source** from `sources.yaml`.
2. **Render** with Playwright (headless Chromium):
   - `chromium.launch(headless=True)`, `context.new_page()`.
   - `page.goto(url, wait_until="networkidle", timeout=30000)`.
   - Wait for known scheme-page anchor (e.g., `text=Expense Ratio` or a stable data-testid) before capturing HTML.
   - `page.content()` → raw HTML.
3. **Fallback:** if Playwright times out, retry once with `httpx` (best-effort; may miss JS-hydrated fields).
4. **Checksum** raw HTML (SHA-256). If identical to last snapshot → mark `unchanged`, skip downstream work.
5. **Parse** with BeautifulSoup → structured dict (facts table) + narrative sections.
6. **Validate** required fields (scheme name, expense ratio, exit load). If any required field is missing → mark `degraded`, keep previous snapshot, alert.
7. **Persist** raw HTML to object store at `corpus/<run_id>/<source_id>.html` and structured JSON at `corpus/<run_id>/<source_id>.json`.
8. **Emit** a `DocumentChangedEvent` to the chunk/embed/index pipeline only for changed sources.

**Politeness & resilience**
- **Rate limit:** 1 request every 3 s across all sources (token bucket); randomized 0–60 s jitter per URL.
- **User-Agent:** `MutualFundFAQBot/1.0 (+contact: ops@example.com)`; never spoof a browser UA.
- **robots.txt:** fetch + cache per-day; abort if disallowed.
- **Per-URL retries:** 3 attempts with exponential backoff (2 s, 8 s, 30 s) on transient errors (5xx, network, Playwright timeout).
- **Circuit breaker:** if > 50 % of URLs fail in a run, abort the whole run and keep the previous snapshot live.
- **Selector drift detection:** each parser declares required fields; a run that extracts < 70 % of required fields across all URLs triggers an alert (`groww_selector_drift`) so the parser can be updated before the corpus decays.

**Output: `ScrapeReport`**
```json
{
  "run_id": "ingest_20260419",
  "started_at": "2026-04-19T09:00:12+05:30",
  "finished_at": "2026-04-19T09:02:47+05:30",
  "results": [
    {"source_id": "src_001", "status": "unchanged", "checksum": "sha256:..."},
    {"source_id": "src_002", "status": "changed",   "checksum": "sha256:...", "fields_extracted": 12},
    {"source_id": "src_003", "status": "degraded",  "error": "missing field: exit_load"}
  ],
  "summary": {"changed": 1, "unchanged": 1, "degraded": 1, "failed": 0}
}
```

**Deployment shape**
- Runs in its own container (`scraper-worker`) so the Playwright/Chromium footprint does not bloat the API image.
- On GitHub Actions the scraper runs as a step inside the `ingest` job (§4.3) — the "container" is the ephemeral `ubuntu-latest` runner.
- Horizontally scalable but typically runs as a **single replica** (3 URLs do not need concurrency); the `concurrency` block in the workflow enforces this.
- Resource hint: 1 vCPU, 1 GB RAM, +~300 MB for Chromium.

---

## 5. Chunking & Embedding Architecture  **[IMPLEMENTED]**

**Code:** `phase_4_1_chunk_embed_index/ingestion_pipeline/` — `pipeline.IngestionPipeline`, `segmenter.DocumentSegmenter`, `chunker.Chunker`, `normalizer.{normalize_for_display,normalize_for_hash}`, `hasher.ChunkHasher`, `embedding_cache.{EmbeddingCache,InMemoryEmbeddingCache}`, `embedder.{CachedEmbedder,FakeDeterministicEmbedder,build_embedder}`, `index_writer.IndexWriter`, `snapshot.{SnapshotManager,CorpusPointer}`. CLI: `phase_4_1_chunk_embed_index/cli.py` (`python cli.py ingest …`). Config: `phase_4_1_chunk_embed_index/config/embedder.yaml`.

**What's live:** in-memory implementations of `VectorIndex`, `BM25Index`, `FactKVStore`, `CorpusPointer`, `EmbeddingCache`; `FakeDeterministicEmbedder` (64-dim, SHA-derived, L2-normalized) is the default for tests + local dev. `build_embedder(config)` dispatches on `provider` ∈ {`fake`, `bge_local`, `openai`}. Default provider is `bge_local` (`BAAI/bge-small-en-v1.5`, 384 dims).

This section is the detailed design for how a **changed** document (emitted by the Scraping Service as `DocumentChangedEvent`) becomes searchable vectors + a BM25 index. The stage is invoked inside the same GitHub Actions job (§4.3) after scraping completes.

### 5.1 Pipeline Overview

```
 DocumentChangedEvent(source_id, run_id, structured_json, html)
        │
        ▼
 ┌───────────────────────┐
 │ 1. Document Segmenter │  split into typed segments: fact_table | section_text | table
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 2. Chunker (per-type) │  rules differ by segment type
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 3. Metadata Enricher  │  attach scheme/section/source_url/last_updated
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 4. Chunk Hasher       │  SHA-256(normalized_text) → chunk_hash
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 5. Cache Lookup       │  skip if (chunk_hash, embed_model) already in cache
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 6. Embedder           │  batch → embedding API → 1024-d vector
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 7. Index Writer       │  upsert to Chroma/Qdrant + BM25 + fact_table KV store
 └──────────┬────────────┘
            ▼
 ┌───────────────────────┐
 │ 8. Snapshot & Swap    │  atomic version bump: corpus_v2026_04_19 → live
 └───────────────────────┘
```

### 5.2 Document Segmenter

Input: the structured JSON emitted by the scraper (`facts` dict + `sections` list) plus the raw HTML for anchor info.

Produces three **segment types**, each with its own downstream chunking rule:

| Segment type     | Example content                                    | Why separate |
|------------------|----------------------------------------------------|--------------|
| `fact_table`     | `{expense_ratio: "0.67%", exit_load: "1% if < 1y"}` | Exact-lookup path — must stay atomic, never split. |
| `section_text`   | "About the fund", "Investment objective" prose     | Free-text — benefits from semantic chunking. |
| `table`          | Portfolio holdings table, year-wise returns table  | Row-aware — split by rows, keep header with each chunk. |

Each segment carries `{source_id, scheme, section, doc_anchor, segment_type}`.

### 5.3 Chunking Rules (per segment type)

#### 5.3.1 `fact_table` → one chunk per **fact**
- Each key-value pair becomes its own tiny chunk (e.g., "Expense Ratio: 0.67%").
- Wrapped in a sentence template so embedding captures intent:
  `"{scheme} has an expense ratio of 0.67%."`
- Keeps retrieval precise: a query about "expense ratio of HDFC Mid Cap" hits exactly one chunk.
- `chunk_id` format: `{source_id}#fact#{field_name}` (e.g., `src_003#fact#expense_ratio`).

#### 5.3.2 `section_text` → semantic, heading-aware chunking
- **Target size:** 500 tokens.
- **Overlap:** 80 tokens (sliding window at chunk boundaries).
- **Tokenizer:** `tiktoken` (`cl100k_base`) for consistent counts regardless of model.
- **Algorithm:** recursive splitter using separators in order: `"\n## "`, `"\n### "`, `"\n\n"`, `"\n"`, `". "`, `" "`. Each split tries the next separator only if a chunk exceeds target.
- **Heading propagation:** every chunk is prefixed with the nearest parent heading so embeddings retain context, e.g., `"Section: Investment Objective\n\n{chunk_body}"`.
- **Minimum size guard:** chunks < 100 tokens get merged with the previous chunk (avoids noisy mini-chunks).
- `chunk_id` format: `{source_id}#{section_slug}#c{index}`.

#### 5.3.3 `table` → row-aware chunking
- Extract `<thead>` as a reusable header.
- Group rows into chunks of ≤ 6 rows (or ≤ 400 tokens, whichever comes first).
- **Every chunk re-includes the header row** so it is self-contained for embedding.
- Serialized as Markdown table for readability by the LLM.
- `chunk_id` format: `{source_id}#table_{table_slug}#rows_{start}-{end}`.

### 5.4 Normalization (pre-hash, pre-embed)

Applied uniformly to every chunk before hashing and embedding:
1. Unicode NFKC.
2. Collapse whitespace (`\s+` → single space), trim ends.
3. Standardize currency: `Rs.`, `INR`, `₹` → `₹`.
4. Standardize percentage: `0.67 %` → `0.67%`.
5. Lowercase scheme-name variants (for hashing only — display text keeps original case).

Normalization is **intentionally light** — we don't stem or remove stopwords, since the embedding model handles those better than we would.

### 5.5 Chunk Hashing & Re-Embed Avoidance

For each normalized chunk:
```
chunk_hash = sha256(f"{embed_model_id}:{normalized_text}")
```

The **embed_model_id is part of the hash** — swapping models automatically invalidates the cache without a manual flush.

Cache: Postgres table `embedding_cache(chunk_hash PK, embedding BYTEA, dim INT, created_at)`. On a daily run:
- Typical case: 3 URLs × ~25 chunks = 75 chunks; 0–5 are actually new → 5 embedding API calls, not 75.
- Estimated cost impact: > 90 % cache hit in steady state.

### 5.6 Embedding Model

**Primary:** `BAAI/bge-small-en-v1.5` (384 dims) via `sentence-transformers` — runs locally with no external API, no cost, suitable for CI and GitHub Actions runners.

**Alternative:** `OpenAI text-embedding-3-large` (3072 dims) — higher quality, but requires `OPENAI_API_KEY` and incurs per-token cost. Note: Groq does not provide an embeddings endpoint; the local `bge_local` provider is the recommended default.

**Selection lives in config** so switching is a one-line change:
```yaml
embedder:
  provider: bge_local        # bge_local | openai | fake
  model: BAAI/bge-small-en-v1.5
  dim: 384
  batch_size: 64
  normalize: true            # L2-normalize vectors for cosine ≡ dot product
```

**Model versioning:** `embed_model_id = "bge_local/BAAI/bge-small-en-v1.5@v1"`. Every vector row stores this id; a model change triggers a **shadow-rebuild** (§5.9), not an in-place swap.

### 5.7 Batching & Rate Limits

- Embedder consumes a queue of chunks and sends them in batches of **64**.
- Retry: exponential backoff on 429/5xx (1 s, 3 s, 9 s, 27 s) up to 5 attempts.
- Concurrency: single async worker — 3 URLs per day does not need parallelism; keeps rate-limit math trivial.
- Hard cap: 1,000 chunks/run (alert if exceeded — implies parser runaway).

### 5.8 Index Writer

Writes go to **three stores**, atomically per chunk:

| Store              | Purpose                                   | Key                         | Backend (prod)              |
|--------------------|-------------------------------------------|-----------------------------|-----------------------------|
| **Vector DB**      | Dense retrieval (cosine)                  | `chunk_id` → (vector, metadata) | **Chroma Cloud** (`ChromaVectorIndex`) |
| **BM25 index**     | Sparse retrieval (keyword)                | `chunk_id` → tokenized text  | Postgres FTS (`PgBM25Index`) |
| **Fact KV store**  | Exact-lookup fast path for `fact_table` chunks | `(scheme_id, field_name)` → value + source_url + last_updated | Postgres (`PgFactKV`) |

**Chroma Cloud storage model** (`ChromaVectorIndex`):
- One collection (`mf_rag`) for the whole deployment; `corpus_version` is stored as a metadata field on each document so shadow-rebuilds and the atomic pointer swap work without creating/deleting collections.
- Soft-delete: `update()` patches `deleted: "true"` + `deleted_at_ts` (Unix epoch int) in metadata without re-uploading embeddings.
- Hard-purge: filters `deleted=true AND deleted_at_ts <= cutoff` using Chroma's `$lte` operator, then calls `delete(ids=[...])`.
- `corpus_pointer` (atomic swap) and `embedding_cache` remain in Postgres — Chroma has no equivalent relational capability.

```python
# Chroma Cloud connection (phase_5_ingestion_cli/adapters/chroma_vector_index.py)
client = chromadb.HttpClient(
    host="api.trychroma.com",
    ssl=True,
    headers={"x-chroma-token": CHROMA_API_KEY},
    tenant=CHROMA_TENANT,
    database=CHROMA_DATABASE,
)
collection = client.get_or_create_collection(
    name="mf_rag",
    metadata={"hnsw:space": "cosine"},
)
```

pgvector remains available as a local/CI fallback (`vector_store.backend: pgvector` in `phase5.yaml`). The `chunks` table in `schema.sql` is only used when pgvector backend is selected.

**Upsert semantics:** primary key is `chunk_id`; same id with a new `chunk_hash` overwrites.

**Deletion:** chunks whose `chunk_id` did not appear in the current run but belong to a `changed` source are marked `deleted_at = now()` (soft delete) and excluded from retrieval; hard-purged after 7 days.

### 5.9 Snapshot & Atomic Swap

Every run writes into a **new corpus version** (`corpus_v<run_id>`) and only flips a pointer when the whole pipeline succeeds:

1. All writes go to rows tagged `corpus_version = corpus_v2026_04_19`.
2. A smoke test runs 10 canned queries against the new version; must pass groundedness + citation-validity checks.
3. On success: `UPDATE corpus_pointer SET live = 'corpus_v2026_04_19'` — a single-row flip the retriever reads on every request.
4. On failure: the new version is left dangling, retriever continues serving the previous `live` version, Slack alert fires.
5. Keep last 7 versions for rollback; GC older versions.

This is the **shadow-rebuild** mechanism that also handles embedding-model upgrades: build the new index in parallel, validate, swap.

### 5.10 Interface

```python
@dataclass
class Chunk:
    chunk_id: str
    source_id: str
    scheme: str
    section: str | None
    segment_type: Literal["fact_table", "section_text", "table"]
    text: str
    metadata: dict

class Chunker:
    def chunk(self, doc: ParsedDocument) -> list[Chunk]: ...

class Embedder:
    def embed(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]: ...

class IndexWriter:
    def upsert(self, embedded: list[tuple[Chunk, list[float]]], corpus_version: str) -> UpsertReport: ...
```

### 5.11 Metrics (per run)

- `chunks_produced_total{segment_type=...}`
- `chunks_embedded_total` vs `chunks_cache_hit_total` (cache hit rate should be > 90 %)
- `embedding_latency_ms` (p50, p95)
- `embedding_errors_total{code=...}`
- `corpus_version_bytes` (size growth over time)
- `smoke_test_pass_rate` (must be 100 % to swap)

### 5.12 Failure Modes & Guards

| Failure                                  | Guard                                             |
|------------------------------------------|---------------------------------------------------|
| Embedder API down                        | 5× retry → fall back to `bge_local` → if still failing, abort swap (live version unchanged) |
| Parser regression produces empty section | Min-size guard drops empty chunks; count anomaly alert if `chunks_produced_total` drops > 30 % vs 7-day avg |
| Duplicate `chunk_id` across sources      | Upsert key collision caught at write; run aborts with error |
| Dim mismatch after model swap            | `dim` column asserted per-row at retrieval time; mismatched rows hidden, alert raised |
| Vector DB partial write                  | Transactional upsert per source; on error, roll back and keep previous `corpus_version` live |

---

## 6. Retrieval  **[DESIGN-ONLY — not yet implemented]**

### 6.1 Hybrid Retrieval
- **Dense**: vector similarity (cosine) — top-K = 20.
- **Sparse**: BM25 over chunk text — top-K = 20.
- **Fusion**: Reciprocal Rank Fusion (RRF), k=60 → top-K = 15.

### 6.2 Query Understanding
- **Scheme/category detection** via lightweight classifier or keyword match → metadata filter (`scheme = X` or `category = Y`).
- **Query rewrite** (LLM, 1 call) to expand abbreviations (ELSS, SIP, NAV, TER) and canonicalize.
- **Multi-query** variant: generate 2 paraphrases, union results, dedupe.

### 6.3 Reranking
- Cross-encoder (`bge-reranker-base` or Cohere Rerank) → top-N = 5.
- Filter below score threshold (e.g., 0.35) to force refusal/"not found" path.

### 6.4 Source-Class Priority
Current corpus is single-class (`groww` scheme pages). Tie-breaker when multiple chunks match: **fact-table chunk > narrative chunk**, then most recent `last_updated`. When official AMC/AMFI/SEBI pages are added later, preference order becomes **AMC factsheet > SID > KIM > AMFI > SEBI > Groww scheme page**.

---

## 7. Generation  **[DESIGN-ONLY — not yet implemented]**

### 7.1 Prompt Contract
System prompt enforces:
- Answer **only** from provided context.
- Max **3 sentences**.
- Include **exactly one** citation link (the highest-ranked source).
- Append footer: `Last updated from sources: <ISO date>`.
- If context is insufficient → return `INSUFFICIENT_CONTEXT` sentinel.
- Never provide advice, recommendations, performance comparisons, or return calculations.

### 7.2 Model Choice
- Primary: **Groq — `llama-3.3-70b-versatile`** (fast inference, cost-efficient, strong instruction-following).
- Optional upgrade: `llama-3.1-405b-reasoning` or similar large model for complex schemes/tables.
- Temperature: 0.0–0.2 for factual consistency.

### 7.3 Generator Output Schema
```json
{
  "answer": "…max 3 sentences…",
  "citation_url": "https://groww.in/mutual-funds/bandhan-small-cap-fund-direct-growth",
  "last_updated": "2026-04-19",
  "confidence": 0.87,
  "used_chunk_ids": ["src_002#sec_expense_ratio#c1"]
}
```

---

## 8. Guardrails  **[DESIGN-ONLY — not yet implemented]**

### 8.1 Pre-Retrieval (Input Guard)
1. **PII scrubber** — regex + NER to block PAN / Aadhaar / account / OTP / email / phone; reject with polite refusal.
2. **Intent classifier** (small LLM or rules) labels query as:
   - `FACTUAL` → proceed.
   - `ADVISORY` → refuse with template + AMFI/SEBI educational link.
   - `PERFORMANCE_CALC` → redirect to the scheme's Groww page only (no computed returns).
   - `OUT_OF_SCOPE` → polite refusal (e.g., schemes not in the 3-URL corpus).
3. **Prompt-injection filter** — strip instructions embedded in user text; reject known jailbreak patterns.

### 8.2 Post-Generation (Output Guard)
1. **Citation validator** — URL must exist in source registry; reject/regenerate if not.
2. **Length enforcer** — ≤ 3 sentences; truncate or regenerate.
3. **Advice detector** — classifier flags advisory verbs ("should", "recommend", "better"); block if triggered.
4. **Groundedness check** — LLM-as-judge or NLI model verifies each claim appears in `used_chunk_ids`; regenerate on failure.
5. **Disclaimer** attached once per thread in the UI.

### 8.3 Refusal Templates
```
"I can only share factual information from official mutual fund sources,
so I can't offer recommendations. For general guidance on choosing schemes,
see AMFI's investor education: https://www.amfiindia.com/investor-corner"
```

---

## 9. Multi-Thread Chat Support  **[DESIGN-ONLY — not yet implemented]**

### 9.1 Thread Model
- `thread_id` (UUID) generated per new conversation.
- Session store: Redis (prod) / SQLite (dev) with TTL = 24h.
- Schema:
  ```json
  {
    "thread_id": "uuid",
    "created_at": "...",
    "messages": [
      {"role": "user", "content": "...", "ts": "..."},
      {"role": "assistant", "content": "...", "citations": [...], "ts": "..."}
    ],
    "metadata": {"last_scheme": "Bandhan Small Cap Fund Direct - Growth"}
  }
  ```

### 9.2 Context Handling
- Only last **4 turns** injected into query rewrite (not into retrieval directly) to resolve coreference (e.g., "and its expense ratio?").
- Per-thread in-flight request lock to prevent race conditions.
- Concurrency: async FastAPI + connection pool; horizontally scalable behind a load balancer.

---

## 10. User Interface  **[DESIGN-ONLY — not yet implemented]**

- Minimal single-page app (React/Next.js or plain HTML + HTMX).
- Components:
  - **Welcome banner**: "Ask me factual questions about mutual fund schemes."
  - **3 example chips** (tied to the seed corpus):
    1. "What is the expense ratio of HDFC Mid Cap Fund Direct - Growth?"
    2. "What is the exit load for Bandhan Small Cap Fund Direct - Growth?"
    3. "What is the benchmark for Nippon India Taiwan Equity Fund Direct - Growth?"
  - **Disclaimer (sticky)**: `Facts-only. No investment advice.`
  - **Thread sidebar**: list of threads, "New chat" button.
  - **Message bubbles** with citation link + `Last updated: YYYY-MM-DD` footer.

---

## 11. Technology Stack

| Layer           | Choice                                             |
|-----------------|----------------------------------------------------|
| API             | FastAPI (Python 3.11)                              |
| Orchestration   | LangGraph or a thin custom orchestrator            |
| Vector DB       | **Chroma Cloud** (`api.trychroma.com`) — managed HNSW, cosine similarity, no self-hosted infra. Adapter: `ChromaVectorIndex` in `phase_5_ingestion_cli/adapters/`. pgvector remains available as a fallback (`vector_store.backend: pgvector` in config). |
| Sparse index    | Postgres FTS (`tsvector` / GIN index) — `PgBM25Index` in phase 4.2 |
| Fact KV         | Postgres table `fact_kv` — exact-lookup fast path  |
| Embedding cache | Postgres table `embedding_cache` (float32 BYTEA)   |
| Corpus pointer  | Postgres single-row `corpus_pointer` — atomic swap |
| Embeddings      | `BAAI/bge-small-en-v1.5` 384-dim via `sentence-transformers` (primary) / OpenAI `text-embedding-3-large` (optional) |
| Reranker        | `bge-reranker-base` or Cohere Rerank v3            |
| LLM             | **Groq** `llama-3.3-70b-versatile` (primary) — OpenAI-compatible API; `GROQ_API_KEY` required |
| Session store   | Redis                                              |
| Web fetch       | Playwright (headless Chromium) for JS-rendered Groww pages; `httpx` fallback |
| Scheduler       | **GitHub Actions** — `.github/workflows/ingest.yml`, cron `30 3 * * *` UTC (= 09:00 IST) |
| Scraping worker | Step inside the `ingest` GitHub Actions job (Playwright + BeautifulSoup) |
| Document store  | S3/MinIO for raw HTML snapshots; Postgres for relational stores |
| Frontend        | Next.js / React + Tailwind                         |
| Observability   | OpenTelemetry → Grafana / Langfuse for LLM traces  |
| Deploy          | Docker + Fly.io / Render / AWS ECS                 |

---

## 12. Evaluation

### 12.1 Golden Set
- 50–100 curated Q/A pairs covering: expense ratio, exit load, SIP min, ELSS lock-in, riskometer, benchmark, statement download, refusal cases.

### 12.2 Metrics
- **Retrieval**: Recall@5, MRR.
- **Answer quality**: Exact-fact accuracy, citation precision (URL matches ground truth).
- **Groundedness**: % claims supported by retrieved chunks (LLM-judge).
- **Refusal accuracy**: Precision/recall on advisory queries.
- **Latency**: p50 / p95 end-to-end.
- **Cost**: tokens per query.

### 12.3 CI Gate
Regression test suite runs on every ingestion refresh; blocks release if accuracy drops > 3%.

---

## 13. Security & Privacy

- No PII logged; prompts/responses hashed for analytics.
- TLS everywhere; secrets via environment / vault.
- Rate limiting per IP and per thread.
- Audit log: (thread_id, timestamp, query_hash, citation_url, decision).
- Data retention: thread history 24h, logs 30d, raw corpus versioned indefinitely.

---

## 14. Known Limitations

- Corpus is limited to the three provided Groww scheme pages (Nippon India Taiwan Equity, Bandhan Small Cap, HDFC Mid Cap — all Direct-Growth).
- **No PDFs ingested** in this iteration: factsheet / KIM / SID content is not in-scope. Any question requiring those documents is answered with a pointer to the Groww page or refused.
- Groww is a distributor, not the issuing AMC; facts are subject to the AMC's own disclosures. Treat Groww as the interim ground truth until official AMC/AMFI/SEBI sources are added.
- Figures may lag underlying fund data by up to the ingestion interval.
- Client-rendered pages require Playwright; fetch failures (selector changes on Groww) need monitoring.
- No personalized or portfolio-specific answers by design.

---

## 15. Roadmap

- **Phase 4.0** ✅ *done* — GitHub Actions scheduler + scraping service (Playwright/httpx, Groww parser, validator, rate limiter, checksum diff, circuit breaker, drift alert, `ScrapeReport`, `DocumentChangedEvent`). Code: `phase_4_scheduler_scraping/`.
- **Phase 4.1** ✅ *done* — Segmenter → chunker → normalizer → hasher → cache → embedder → index writer → snapshot manager. In-memory stores + `FakeDeterministicEmbedder`; Protocol interfaces for prod swap-in. Code: `phase_4_1_chunk_embed_index/`.
- **Phase 4.2** ✅ *done* — Prod backends behind the 4.1 Protocols: `PgVectorIndex` (pgvector HNSW), `PgBM25Index` (Postgres FTS tsvector/GIN), `PgFactKV`, `PgEmbeddingCache` (BYTEA float32 blobs), `PgCorpusPointer`, `S3Storage` (boto3 — MinIO-compatible via `endpoint_url`), `StructuralSmokeRunner`, `build_prod_pipeline()` composition root, and SQL DDL. OpenAI/BGE embedder classes were already present in 4.1 (lazy-imported). 39 unit tests with a fake psycopg + moto. Code: `phase_4_2_prod_wiring/`.
- **Phase 5** ✅ *done* — Ingestion CLI (`phase_5_ingestion_cli/`) that composes phase 4.1 pipeline with phase 4.2 backends. `cli.py` (`run` + `purge` subcommands), `composition.py` (wiring root), `purge.py` (hard-purge cron), `config/phase5.yaml`, 17 unit tests (fake psycopg + no real DB/S3 needed).
- **Phase 6** — Hybrid retrieval (§6): dense + BM25 + RRF + cross-encoder rerank; query rewrite using last 4 turns.
- **Phase 7** — Generation (§7): Claude Sonnet 4.6, structured JSON output contract.
- **Phase 8** — Guardrails (§8): PII scrubber, intent classifier, prompt-injection filter; citation/length/advice/groundedness output guards.
- **Phase 9** — API + UI: FastAPI thread manager, Redis session store, Next.js frontend with sticky disclaimer and example chips.
- **Phase 10** — Observability (OTLP + Langfuse), evaluation harness + golden set, CI gate, corpus expansion to official AMC/AMFI/SEBI sources + PDFs (factsheet/KIM/SID).

---

## 16. Request Lifecycle (End-to-End)  **[DESIGN-ONLY — lifecycle depends on phases 6–9]**

1. User sends query on thread `T`.
2. API validates + PII scrub + intent classify.
3. If `ADVISORY`/`OUT_OF_SCOPE` → refusal template → return.
4. Query rewrite using last 4 turns from thread `T`.
5. Hybrid retrieve (dense + BM25) → RRF → rerank → top-5.
6. If top score < threshold → "I couldn't find this in official sources" + AMFI link.
7. Build prompt with chunks + metadata → LLM generates structured JSON.
8. Output guards: citation validity, length, advice detector, groundedness.
9. Persist assistant message on thread `T`; emit telemetry.
10. Return answer + citation + `Last updated` footer to UI.

---

## 17. Implementation Map (code → section)

| Section | Status | Code location |
|---------|--------|---------------|
| §3.2 source registry | ✅ | `phase_4_scheduler_scraping/config/sources.yaml` |
| §4.3 scheduler | ✅ | `.github/workflows/ingest.yml`, `.github/workflows/retry-failed-ingest.yml`, `phase_4_scheduler_scraping/scheduler/` |
| §4.4 scraping service | ✅ | `phase_4_scheduler_scraping/scraping_service/` |
| §5.2 segmenter | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/segmenter/` |
| §5.3 chunker | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/chunker/` |
| §5.4 normalizer | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/normalizer/` |
| §5.5 hasher | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/hasher/` |
| §5.5 embedding cache (in-memory) | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/embedding_cache/` |
| §5.5 embedding cache (Postgres) | ✅ | `phase_4_2_prod_wiring/adapters/pg_embedding_cache.py` |
| §5.6 embedder (fake) | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/embedder/` |
| §5.6 embedder (bge-small-en-v1.5 primary) | ✅ lazy-imported sentence-transformers | `phase_4_1_chunk_embed_index/ingestion_pipeline/embedder/embedder.py` |
| §5.7 batching + retry + cap | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/embedder/embedder.py` |
| §5.8 index writer (three stores) | ✅ in-memory | `phase_4_1_chunk_embed_index/ingestion_pipeline/index_writer/` |
| §5.8 pgvector VectorIndex | ✅ | `phase_4_2_prod_wiring/adapters/pg_vector_index.py` |
| §5.8 BM25 (Postgres FTS) | ✅ | `phase_4_2_prod_wiring/adapters/pg_bm25_index.py` |
| §5.8 FactKV (Postgres) | ✅ | `phase_4_2_prod_wiring/adapters/pg_fact_kv.py` |
| §5.9 snapshot + atomic swap (in-memory pointer) | ✅ | `phase_4_1_chunk_embed_index/ingestion_pipeline/snapshot/` |
| §5.9 corpus pointer (Postgres) | ✅ | `phase_4_2_prod_wiring/adapters/pg_corpus_pointer.py` |
| §5.9 smoke runner (structural) | ✅ | `phase_4_2_prod_wiring/smoke/runner.py` |
| §4.4 storage (S3/MinIO) | ✅ | `phase_4_2_prod_wiring/adapters/s3_storage.py` |
| SQL DDL | ✅ | `phase_4_2_prod_wiring/sql/schema.sql` |
| Prod composition root | ✅ | `phase_4_2_prod_wiring/composition.py` |
| §5 ingestion CLI (phase 5) | ✅ | `phase_5_ingestion_cli/` |
| §5.8 VectorIndex — Chroma Cloud | ✅ | `phase_5_ingestion_cli/adapters/chroma_vector_index.py` |
| §6 retrieval | ❌ | — |
| §7 generation | ❌ | — |
| §8 guardrails | ❌ | — |
| §9 multi-thread chat | ❌ | — |
| §10 UI | ❌ | — |
| §12 evaluation | 🟡 unit tests only | `phase_4_*/tests/` (35 cases); golden set not built |
| §13 security & privacy | 🟡 partial | No PII is handled yet because there is no request path |
