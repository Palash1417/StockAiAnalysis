# Deployment Plan — Mutual Fund FAQ Assistant

**Revision:** 2026-04-23
**Status:** Ready for Phase 9 (API + UI). Ingestion pipeline (phases 4–6) is already coded and tested.

---

## 1. Service Layout

| Service | Platform | Cost | Responsibility |
|---------|----------|------|----------------|
| Ingestion scheduler | **GitHub Actions** | Free | Daily scrape → chunk → embed → push to Chroma Cloud |
| Backend API | **Railway** (Web Service) | Free ($5/mo credits, no card) | FastAPI — guardrails, RAG pipeline, session store |
| Frontend | **Vercel** | Free | Next.js — chat UI |
| Vector store | **Chroma Cloud** | Free tier | Managed HNSW dense retrieval |
| LLM | **Groq** | Free tier | `llama-3.3-70b-versatile` — query rewrite + generation |

```
Vercel (Next.js)
    │  HTTPS  POST /api/chat
    ▼
Railway (FastAPI)  ──── Groq API  (query rewrite, generation)
    │
    └── Chroma Cloud    (dense vector retrieval)

GitHub Actions (cron 03:45 UTC = 09:15 IST)
    └── phase_4_3_push_to_chroma/run.py
            └── Chroma Cloud  (upsert)
```

> **Note on Render:** Render now requires a credit card even for their free tier. Railway is the recommended free alternative — it provides $5/month in free credits (enough for ~500 hours/month on the smallest instance) and requires only a GitHub login.

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
The workflow caches `~/.cache/huggingface` (key `hf-bge-small-en-v1.5-v1`) so the 130 MB model is downloaded only once.

### Retry workflow
`.github/workflows/retry-failed-ingest.yml` fires on `workflow_run: [ingest] → failure` and re-dispatches up to 2× with a 15-minute delay.

---

## 3. Railway — Backend (FastAPI)

### Why Railway
- **No credit card required** — sign in with GitHub and deploy immediately.
- **$5/month free credits** — enough for a demo/portfolio app running 24/7.
- **Nixpacks** auto-detects Python and installs `requirements.txt`.
- Config as code via `railway.toml` (already committed to the repo).

### One-time setup (terminal)
```bash
# Install Railway CLI
npm install -g @railway/cli

# Authenticate (opens browser — sign in with GitHub)
railway login

# Link this repo as a new Railway project
cd /path/to/StockAIAnalysis
railway init        # choose "Empty project", name it mf-faq-api

# Deploy
railway up
```

### Set environment variables
After the first deploy, set secrets via CLI (run each line separately):
```bash
railway variables set CHROMA_API_KEY=<your-key>
railway variables set CHROMA_TENANT=<your-tenant-uuid>
railway variables set CHROMA_DATABASE=default_database
railway variables set GROQ_API_KEY=<your-key>
railway variables set ENVIRONMENT=production
railway variables set LOG_LEVEL=INFO
# Set CORS_ORIGINS after Vercel deploy (Step 4):
railway variables set CORS_ORIGINS=https://<your-project>.vercel.app
```

### Verify health
```bash
railway open   # opens the deployed URL in your browser
# Append /health — should return {"status":"ok"}
```

Railway config lives in `railway.toml` (committed). Build command: `pip install -r requirements.txt`. Start command: `uvicorn phase_9_api.main:app --host 0.0.0.0 --port $PORT`.

### Auto-deploy
Railway redeploys automatically on every push to `main`.

---

## 4. Vercel — Frontend (Next.js)

### Deploy via CLI (terminal)
```bash
cd phase_9_ui
vercel --prod
```

When prompted:
- Link to existing project? → **No** (first time)
- Project name → `mf-faq-ui`
- Root directory → `.` (already in `phase_9_ui/`)
- Override settings? → **No**

### Set environment variable
```bash
vercel env add NEXT_PUBLIC_API_URL production
# Paste your Railway URL: https://mf-faq-api.up.railway.app
vercel --prod   # redeploy to pick up the env var
```

### Preview deployments
Vercel creates a unique URL for every PR. Useful for testing UI changes before merging.

---

## 5. Environment Variables Master Reference

| Variable | GitHub Actions | Railway | Vercel | Notes |
|----------|:--------------:|:-------:|:------:|-------|
| `CHROMA_API_KEY` | ✓ (secret) | ✓ | — | Chroma Cloud auth |
| `CHROMA_TENANT` | ✓ (secret) | ✓ | — | Chroma tenant UUID |
| `CHROMA_DATABASE` | ✓ (secret) | ✓ | — | e.g. `default_database` |
| `GROQ_API_KEY` | ✓ (secret) | ✓ | — | LLM inference |
| `CORS_ORIGINS` | — | ✓ | — | Vercel deployment URL |
| `SLACK_WEBHOOK` | ✓ (secret) | — | — | Failure alerts (optional) |
| `NEXT_PUBLIC_API_URL` | — | — | ✓ | Railway backend URL |
| `LOG_LEVEL` | — | ✓ | — | `INFO` in prod |
| `ENVIRONMENT` | — | ✓ | — | `production` |

---

## 6. Deployment Order

```
Step 1 — Deploy Railway backend
  • npm install -g @railway/cli
  • railway login  (GitHub OAuth)
  • railway init   (in project root)
  • railway up
  • railway variables set CHROMA_API_KEY=... CHROMA_TENANT=... etc.
  • Verify: <railway-url>/health → {"status":"ok"}

Step 2 — Deploy Vercel frontend
  • cd phase_9_ui && vercel --prod
  • vercel env add NEXT_PUBLIC_API_URL production  (paste Railway URL)
  • vercel --prod  (redeploy)
  • Note the Vercel URL

Step 3 — Wire CORS on Railway
  • railway variables set CORS_ORIGINS=https://<your-project>.vercel.app

Step 4 — Run first ingestion
  • GitHub → Actions → ingest → Run workflow → force: true
  • Confirm ingest_report.json artifact shows status: ok
  • Confirm Chroma collection count > 0

Step 5 — Verify end-to-end
  • Open the Vercel URL
  • Ask: "What is the expense ratio of HDFC Mid Cap Fund Direct - Growth?"
  • Confirm answer + citation + Last updated footer appear
```

---

## 7. CORS Configuration

`phase_9_api/app.py` merges two sources of CORS origins:
1. Static list in `phase_9_api/config/api.yaml` (localhost origins for dev)
2. `CORS_ORIGINS` env var set on Railway (Vercel production URL)

Set Railway variable after Vercel deploy:
```bash
railway variables set CORS_ORIGINS=https://<your-project>.vercel.app
```

For local development, `http://localhost:3000` is already in `api.yaml`.

---

## 8. Local Development vs Production Parity

| Concern | Local | Production |
|---------|-------|-----------|
| Ingestion trigger | `python run_local.py` | GitHub Actions cron |
| Vector store | Chroma Cloud (same) | Chroma Cloud |
| Session store | SQLite (default) | SQLite on Railway (or Redis add-on) |
| Backend | `uvicorn phase_9_api.main:app --reload` | Railway Web Service |
| Frontend | `npm run dev` (port 3000) | Vercel |
| Secrets | `.env` file | Railway / Vercel env vars |

---

## 9. Rollback Procedure

| Layer | How to rollback |
|-------|----------------|
| Ingestion | Chroma keeps 7 corpus versions (`keep_versions=7`). Flip `corpus_pointer` to previous version via a one-off script. |
| Backend | Railway → **Deployments** tab → select a previous deploy → **Rollback**. |
| Frontend | Vercel → **Deployments** tab → select a previous deployment → **Promote to Production**. Instant. |

---

## 10. Secrets Rotation

1. Generate the new key on the provider dashboard.
2. Set the new value: `railway variables set KEY=new_value`
3. Railway redeploys automatically.
4. Revoke the old key.

Never commit secrets to the repository. The `.gitignore` already excludes `.env`.
