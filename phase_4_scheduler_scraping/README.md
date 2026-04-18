# Phase 4 — Scheduler + Scraping Service

Implements architecture §4.3 (Scheduler via GitHub Actions) and §4.4 (Scraping
Service). Runs once a day at **09:00 IST** (`30 3 * * *` UTC), fetches the three
Groww scheme pages with Playwright, parses them into a facts table + narrative
sections, checksums the raw HTML, and emits a `DocumentChangedEvent` only for
sources whose content has actually changed.

## Layout

```
phase_4_scheduler_scraping/
├── config/
│   ├── sources.yaml           # source registry (§3.2)
│   └── scraper.yaml           # fetcher, retry, circuit breaker, drift thresholds
├── scheduler/
│   ├── cli.py                 # `python -m scheduler.cli run` — invoked by Actions
│   └── admin_trigger.py       # POST /admin/ingest/run → GitHub REST dispatches
├── scraping_service/
│   ├── fetcher/               # Playwright primary + httpx fallback + robots cache
│   ├── parser/                # BeautifulSoup extractor for Groww scheme pages
│   ├── validator/             # required-field + drift ratio checks
│   ├── persistence/           # LocalStorage (raw HTML + structured JSON + report)
│   ├── rate_limit.py          # token-bucket (1 req / 3 s + 0–60 s jitter)
│   ├── models.py              # Source, ParsedDocument, ScrapeReport, …
│   └── service.py             # orchestrator: retry, circuit breaker, checksum diff
├── tests/                     # pytest: rate limiter, validator, orchestrator
├── artifacts/                 # ScrapeReport output (uploaded as workflow artifact)
└── requirements.txt
```

The two GitHub Actions workflows live at the repo root:

- `.github/workflows/ingest.yml` — the scheduled ingest job (§4.3).
- `.github/workflows/retry-failed-ingest.yml` — retries on scheduled-run failure,
  up to 2× with a 15 min delay.

## How it runs

1. **Scheduler fires** (`30 3 * * *` UTC or `workflow_dispatch` with `force`).
2. `concurrency.group: ingest-groww` ensures only one run executes at a time.
3. The job installs deps + Chromium, then runs `python -m scheduler.cli run`.
4. The CLI loads `config/sources.yaml` + `config/scraper.yaml` and invokes
   `ScrapingService.run(run_id=RUN_ID, force=…)`.
5. Per source: rate-limit wait → fetch (Playwright, then httpx) → SHA-256 diff.
   Unchanged → skip. Changed → parse → validate → persist HTML + JSON →
   emit `DocumentChangedEvent` (consumed by the chunk/embed stage, §5).
6. `ScrapeReport` is written to `artifacts/scrape_report.json` and uploaded as a
   90-day workflow artifact.
7. On failure: Slack webhook fires; the retry workflow schedules up to 2 retries.

## Local development

```bash
cd phase_4_scheduler_scraping
pip install -r requirements.txt
playwright install chromium         # only needed for real fetches
python -m scheduler.cli run --run-id ingest_local --force true
```

Offline run: tests fully exercise the orchestrator with fake fetcher/parser, so
`pytest` passes without network or Playwright.

```bash
pytest tests/ -v
```

## Secrets (GitHub Actions)

- `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` — for downstream embedding/generation.
- `VECTOR_DB_URL`, `S3_BUCKET` — external state (runner FS is ephemeral).
- `SLACK_WEBHOOK` — failure notifications.

## Guarantees

- **Singleton**: workflow-level concurrency → no overlapping runs.
- **Polite**: 1 req / 3 s + 0–60 s jitter, honors robots.txt, declared User-Agent.
- **Resilient**: 3× exponential backoff per URL (2 s, 8 s, 30 s); circuit breaker
  aborts the run if >50 % of URLs fail, keeping the previous snapshot live.
- **Idempotent**: checksum diff skips unchanged sources; re-running the same
  `run_id` is a no-op unless `force=true`.
- **Drift-aware**: if <70 % of tracked fields are extracted on average, logs
  `groww_selector_drift` so the parser can be updated before corpus decay.
- **Atomic handoff**: `DocumentChangedEvent` is only emitted after persistence
  and validation succeed.
