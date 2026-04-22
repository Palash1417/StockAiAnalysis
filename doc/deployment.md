# Deployment Plan — Mutual Fund FAQ Assistant

**Revision:** 2026-04-21  
**Status:** Ready for Phase 9 (API + UI). Ingestion pipeline (phases 4–6) is already coded and tested.

---

## 1. Service Layout

| Service | Platform | Responsibility |
|---------|----------|----------------|
| Ingestion scheduler | **GitHub Actions** | Daily scrape → chunk → embed → push to Chroma Cloud |
| Backend API | **Render** (Web Service) | FastAPI — guardrails, RAG pipeline, session store |
| Frontend | **Vercel** | Next.js — chat UI |
| Vector store | **Chroma Cloud** | Managed HNSW dense retrieval |
| Relational store | **Render PostgreSQL** | BM25 (tsvector), fact_kv, embedding_cache, session store, corpus pointer |
| LLM | **Groq** | `llama-3.3-70b-versatile` — query rewrite + generation |

```
Vercel (Next.js)
    │  HTTPS  POST /api/chat
    ▼
Render (FastAPI)  ──── Groq API  (query rewrite, generation)
    │
    ├── Chroma Cloud    (dense vector retrieval)
    ├── Render Postgres  (BM25 / fact_kv / sessions)
    └── [read] ingest_report.json  (health endpoint)

GitHub Actions (cron 03:45 UTC = 09:15 IST)
    └── phase_4_3_push_to_chroma/run.py
            └── Chroma Cloud  (upsert)
```

---

## 2. GitHub Actions — Ingestion Scheduler

### What it deploys
No runtime service is deployed. The workflow runs a Python job on `ubuntu-latest` runners and pushes vectors to Chroma Cloud.

### Trigger
| Trigger | Schedule |
|---------|----------|
| `schedule` | `45 3 * * *` UTC (= 09:15 IST) |
| `workflow_dispatch` | Manual, optional `force: true` input |

### Required GitHub Encrypted Secrets
Go to **Settings → Secrets and variables → Actions → New repository secret**.

| Secret | Where to get it |
|--------|----------------|
| `CHROMA_API_KEY` | Chroma Cloud dashboard → API Keys |
| `CHROMA_TENANT` | Chroma Cloud dashboard → Tenant UUID |
| `CHROMA_DATABASE` | Chroma Cloud collection database name (e.g. `default_database`) |
| `GROQ_API_KEY` | console.groq.com → API Keys |
| `SLACK_WEBHOOK` | Slack → App → Incoming Webhooks (optional, for failure alerts) |

### HuggingFace model cache
The workflow caches `~/.cache/huggingface` (key `hf-bge-small-en-v1.5-v1`) so the 130 MB model is downloaded only once. Bump the key suffix to force a fresh download.

### Retry workflow
`.github/workflows/retry-failed-ingest.yml` fires on `workflow_run: [ingest] → failure` and re-dispatches up to 2× with a 15-minute delay.

### Artifact
`phase_4_3_push_to_chroma/ingest_report.json` is uploaded as a GitHub artifact (90-day retention) after every run.

---

## 3. Render — Backend (FastAPI)

### Service type
**Web Service** — Docker or Python (native runtime).

### Recommended: native Python runtime
Render auto-detects `requirements.txt` and runs the start command directly — no Dockerfile needed for initial deployment.

### Repository connection
1. Connect the GitHub repo in the Render dashboard.
2. Set **Root Directory** to the project root.
3. Set **Branch** to `main`.

### Build command
```bash
pip install -r phase_9_api/requirements.txt
```

### Start command
```bash
uvicorn phase_9_api.main:app --host 0.0.0.0 --port $PORT
```

### Environment variables (Render dashboard → Environment)

| Variable | Value / Source |
|----------|---------------|
| `CHROMA_API_KEY` | Chroma Cloud API key |
| `CHROMA_TENANT` | Chroma Cloud tenant UUID |
| `CHROMA_DATABASE` | e.g. `default_database` |
| `GROQ_API_KEY` | Groq console |
| `VECTOR_DB_URL` | Render Postgres internal URL (`postgresql://...`) |
| `REDIS_URL` | Render Redis internal URL (`redis://...`) — when Redis add-on is enabled |
| `CORS_ORIGINS` | `https://<your-project>.vercel.app` (comma-separated if multiple) |
| `LOG_LEVEL` | `INFO` |
| `ENVIRONMENT` | `production` |

### Render PostgreSQL add-on
1. In the Render dashboard, create a **PostgreSQL** instance (free tier: 1 GB, 97 days retention; paid: unlimited).
2. Copy the **Internal Database URL** and set it as `VECTOR_DB_URL`.
3. Run the DDL once after first deploy:
   ```bash
   # From Render Shell or locally with the external URL
   psql $VECTOR_DB_URL -f phase_4_2_prod_wiring/sql/schema.sql
   ```

### Health check
Render pings `GET /health` every 30 s. Implement it in `phase_9_api/main.py`:
```python
@app.get("/health")
def health():
    return {"status": "ok"}
```

### Auto-deploy
Render redeploys automatically on every push to `main`. Disable this in **Settings → Auto-Deploy** if you want manual control.

### Instance sizing (starting point)
| Tier | vCPU | RAM | Use case |
|------|------|-----|----------|
| Free | 0.1 | 512 MB | Dev / demo (spins down after 15 min idle) |
| Starter ($7/mo) | 0.5 | 512 MB | Light production |
| Standard ($25/mo) | 1 | 2 GB | Recommended — bge-reranker-base needs ~1 GB |

---

## 4. Vercel — Frontend (Next.js)

### Repository connection
1. Import the GitHub repo in the Vercel dashboard.
2. Set **Root Directory** to `phase_9_ui/` (the Next.js app).
3. Framework preset: **Next.js** (auto-detected).

### Build & output
Vercel runs `next build` automatically. No changes needed to `package.json`.

### Environment variables (Vercel dashboard → Settings → Environment Variables)

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://<your-render-service>.onrender.com` |

Set this for **Production**, **Preview**, and **Development** environments. The `NEXT_PUBLIC_` prefix makes it available in the browser bundle.

### Custom domain (optional)
Vercel dashboard → **Domains → Add** → follow DNS CNAME instructions.

### Preview deployments
Vercel creates a unique URL for every PR. Useful for testing UI changes before merging.

---

## 5. Environment Variables Master Reference

The table below covers all variables across all environments.

| Variable | GitHub Actions | Render | Vercel | Notes |
|----------|:--------------:|:------:|:------:|-------|
| `CHROMA_API_KEY` | ✓ (secret) | ✓ | — | Chroma Cloud auth |
| `CHROMA_TENANT` | ✓ (secret) | ✓ | — | Chroma tenant UUID |
| `CHROMA_DATABASE` | ✓ (secret) | ✓ | — | e.g. `default_database` |
| `GROQ_API_KEY` | ✓ (secret) | ✓ | — | LLM inference |
| `VECTOR_DB_URL` | — | ✓ | — | Render Postgres internal URL |
| `REDIS_URL` | — | ✓ | — | Render Redis internal URL |
| `CORS_ORIGINS` | — | ✓ | — | Vercel deployment URL |
| `SLACK_WEBHOOK` | ✓ (secret) | — | — | Failure alerts (optional) |
| `NEXT_PUBLIC_API_URL` | — | — | ✓ | Render backend URL |
| `LOG_LEVEL` | — | ✓ | — | `INFO` in prod |
| `ENVIRONMENT` | — | ✓ | — | `production` |

---

## 6. Deployment Order

Follow this sequence for the first deployment.

```
Step 1 — Provision Chroma Cloud collection
  • Create tenant + database at app.trychroma.com
  • Note: API key, tenant UUID, database name

Step 2 — Provision Render Postgres
  • Create PostgreSQL instance in Render dashboard
  • Run schema.sql against the new database
  • Note: Internal Database URL

Step 3 — Deploy Render backend
  • Connect repo, set env vars, deploy
  • Verify GET /health returns {"status":"ok"}

Step 4 — Deploy Vercel frontend
  • Connect repo, set NEXT_PUBLIC_API_URL to Render URL
  • Verify UI loads and /api/chat returns a response

Step 5 — Run first ingestion
  • Trigger the GitHub Actions workflow manually:
      Actions → ingest → Run workflow → force: true
  • Confirm ingest_report.json artifact shows status: ok
  • Confirm Chroma collection count > 0

Step 6 — Verify end-to-end
  • Open the Vercel URL
  • Ask: "What is the expense ratio of HDFC Mid Cap Fund Direct - Growth?"
  • Confirm answer + citation + Last updated footer appear
```

---

## 7. CORS Configuration

The Render backend must allow requests from the Vercel origin. In `phase_9_api/main.py`:

```python
from fastapi.middleware.cors import CORSMiddleware
import os

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "").split(","),
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type", "Authorization"],
)
```

Set `CORS_ORIGINS` to `https://<your-project>.vercel.app` in Render.  
For local development add `http://localhost:3000` to the list.

---

## 8. Local Development vs Production Parity

| Concern | Local | Production |
|---------|-------|-----------|
| Ingestion trigger | `python run_local.py` | GitHub Actions cron |
| Vector store | Chroma Cloud (same) | Chroma Cloud |
| Relational store | Local Postgres / SQLite | Render Postgres |
| Session store | SQLite or in-memory | Render Redis |
| Backend | `uvicorn phase_9_api.main:app --reload` | Render Web Service |
| Frontend | `npm run dev` (port 3000) | Vercel |
| Secrets | `.env` file | Platform secrets / env vars |

---

## 9. Rollback Procedure

| Layer | How to rollback |
|-------|----------------|
| Ingestion | Chroma keeps 7 corpus versions (`keep_versions=7`). Flip `corpus_pointer` to previous version via a one-off script. |
| Backend | Render → **Deploys** tab → select a previous deploy → **Rollback**. Takes ~30 s. |
| Frontend | Vercel → **Deployments** tab → select a previous deployment → **Promote to Production**. Instant. |
| Database schema | Run inverse migration SQL manually; no automated down-migrations yet. |

---

## 10. Secrets Rotation

1. Generate the new key on the provider dashboard.
2. Add the new value to Render / GitHub Secrets **before** deleting the old one.
3. Trigger a manual re-deploy (Render) or re-run (GitHub Actions) to pick up the new value.
4. Revoke the old key.

Never commit secrets to the repository. The `.gitignore` already excludes `.env`.
