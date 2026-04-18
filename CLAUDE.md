# CLAUDE.md — Project Context

Primary reference for future sessions in `RAG-ChatBOT`. Source-of-truth docs live in `doc/doc.md` (problem statement) and `doc/architecture.md` (detailed architecture). This file is the condensed working brief.

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

## 5. Scheduler — GitHub Actions (committed choice)

- **Workflow:** `.github/workflows/ingest.yml`.
- **Cron:** `30 3 * * *` UTC = **09:00 IST daily** (GitHub Actions is UTC-only).
- **Manual trigger:** `workflow_dispatch` with `force` bool input; internal `POST /admin/ingest/run` dispatches via GitHub REST.
- **Singleton:** `concurrency: { group: ingest-groww, cancel-in-progress: false }` — queues, never overlaps.
- **Timeout:** `timeout-minutes: 20`.
- **Retry:** no native retry on scheduled runs → companion `retry-failed-ingest.yml` listens on `workflow_run: failure`, re-dispatches up to 2× with 15 min delay.
- **Secrets:** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `VECTOR_DB_URL`, `S3_BUCKET`, `SLACK_WEBHOOK` — via GitHub encrypted secrets.
- **State:** runners are ephemeral → all persisted state (vector index, raw HTML) lives in S3/MinIO + external vector DB; never on the runner FS.
- **Observability:** ScrapeReport uploaded as artifact (90-day retention); metrics via OTLP; Slack alert on failure.
- **Delay caveat:** GitHub may delay scheduled runs up to 15 min under peak load → valid window is 09:00–09:20 IST.

---

## 6. Scraping Service

Runs as a step inside the `ingest` GitHub Actions job.

- **Fetch:** Playwright (headless Chromium) with `wait_until="networkidle"` + selector wait before `page.content()`; `httpx` fallback on timeout.
- **Politeness:** 1 req / 3 s token bucket, 0–60 s jitter, honor robots.txt, UA = `MutualFundFAQBot/1.0 (+contact: ops@example.com)`.
- **Per-URL retry:** 3× exponential backoff (2 s, 8 s, 30 s).
- **Circuit breaker:** abort run if > 50 % of URLs fail; keep previous snapshot live.
- **Selector-drift alert:** fires if < 70 % of required fields extracted.
- **Checksum diff:** SHA-256 on raw HTML → unchanged sources skip downstream work.
- **Validation:** required fields (scheme name, expense ratio, exit load) — missing → `degraded`, alert, keep previous snapshot.
- **Persist:** raw HTML to `corpus/<run_id>/<source_id>.html`, structured JSON to `corpus/<run_id>/<source_id>.json`.
- **Output:** `ScrapeReport` with per-URL `changed | unchanged | degraded | failed` status.
- **Emits:** `DocumentChangedEvent` to the chunk/embed pipeline **only for changed sources**.

---

## 7. Chunking & Embedding

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
- **Primary:** OpenAI `text-embedding-3-large` (3072 dim).
- **Local fallback:** `BAAI/bge-large-en-v1.5` (1024 dim) via `sentence-transformers`.
- **Config-driven** (`embedder.provider`, `.model`, `.dim`, `.batch_size`, `.normalize`).
- **Batch size 64**, retry with 1/3/9/27 s backoff on 429/5xx, hard cap 1,000 chunks/run.
- `embed_model_id = "openai/text-embedding-3-large@2024-01"` stored per row.

### Index writer — three stores
| Store      | Purpose                          | Key                         |
|------------|----------------------------------|-----------------------------|
| Vector DB  | Dense retrieval (cosine)         | `chunk_id`                  |
| BM25       | Sparse retrieval                 | `chunk_id`                  |
| Fact KV    | Exact-lookup fast path           | `(scheme_id, field_name)`   |

pgvector schema: `chunks(chunk_id PK, source_id, scheme, section, segment_type, text, embedding vector(3072), embed_model_id, chunk_hash, source_url, last_updated, corpus_version)` with HNSW cosine index + `(scheme, segment_type)` btree. Upsert on `chunk_id`. Soft-delete missing chunks; hard-purge after 7 days.

### Snapshot & atomic swap (shadow-rebuild)
1. Writes tagged with new `corpus_version = corpus_v<run_id>`.
2. Smoke test: 10 canned queries must pass groundedness + citation validity.
3. On success: `UPDATE corpus_pointer SET live = <new>` (single row flip).
4. On failure: new version left dangling, retriever keeps serving previous, Slack alert.
5. Keep last 7 versions; GC older. Same mechanism handles embedding-model upgrades.

---

## 8. Retrieval & Generation

### Retrieval
- **Hybrid**: dense (cosine, top-K=20) + BM25 (top-K=20) → RRF (k=60) → top-K=15 → cross-encoder rerank (`bge-reranker-base` or Cohere Rerank v3) → top-N=5.
- **Score threshold 0.35** — below = force "not found" path.
- **Scheme/category metadata filter** applied from query understanding.
- **Query rewrite** (1 LLM call) expands abbreviations (ELSS, SIP, NAV, TER) using last 4 thread turns.
- **Source-class priority** (current): fact-table chunk > narrative chunk, tie-break on most recent `last_updated`. Future: AMC factsheet > SID > KIM > AMFI > SEBI > Groww.

### Generation
- **LLM:** Claude Sonnet 4.6 (primary), Claude Opus 4.7 for complex tables. Temperature 0.0–0.2.
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

## 9. Guardrails

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

## 10. Multi-thread chat

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
| Vector DB        | Chroma (dev) / Qdrant or pgvector (prod) |
| Sparse index     | `rank_bm25` or OpenSearch |
| Embeddings       | OpenAI `text-embedding-3-large` (primary) / `bge-large-en-v1.5` (local fallback) |
| Reranker         | `bge-reranker-base` or Cohere Rerank v3 |
| LLM              | Claude Sonnet 4.6 (primary), Opus 4.7 (complex) |
| Session store    | Redis |
| Web fetch        | Playwright (headless Chromium) + `httpx` fallback |
| Scheduler        | **GitHub Actions** (`.github/workflows/ingest.yml`, `30 3 * * *` UTC) |
| Scraping worker  | Step inside the `ingest` GitHub Actions job |
| Document store   | Postgres + S3/MinIO (raw HTML snapshots) |
| Frontend         | Next.js / React + Tailwind |
| Observability    | OpenTelemetry → Grafana / Langfuse |
| Deploy           | Docker + Fly.io / Render / AWS ECS |

---

## 12. UI spec (minimal)

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

- **Golden set:** 50–100 Q/A pairs (expense ratio, exit load, SIP min, ELSS lock-in, riskometer, benchmark, statement download, refusal cases).
- **Metrics:** Recall@5, MRR, exact-fact accuracy, citation precision, groundedness %, refusal precision/recall, p50/p95 latency, tokens/query.
- **CI gate:** regression suite on every ingestion refresh; blocks release if accuracy drops > 3 %.

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

1. **v0.1** — 3 Groww URLs, HTML-only ingestion, Chroma + Claude, single-thread UI.
2. **v0.2** — Hybrid retrieval + reranker, multi-thread, eval harness on 3-scheme golden set.
3. **v0.3** — GitHub Actions ingestion live, Langfuse traces, refusal classifier.
4. **v0.4** — Expand corpus with official AMC/AMFI/SEBI pages (and PDFs when available); table-aware extraction; groundedness judge in CI.

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

- `doc/doc.md` — original problem statement (source of truth for requirements).
- `doc/architecture.md` — full architecture with implementation detail (source of truth for design).
- `CLAUDE.md` — this file (condensed working brief for future sessions).
- `sources.yaml` — source registry (planned).
- `.github/workflows/ingest.yml` — daily ingest workflow (planned).
- `.github/workflows/retry-failed-ingest.yml` — retry companion (planned).

When design questions arise, prefer `doc/architecture.md` for detail; use this file for quick recall.
@doc.md - basic understanding of project
@architecture.md - architecture of the project 