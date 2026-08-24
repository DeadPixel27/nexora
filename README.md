# Nexora

Describe what you want done with your documents → AI builds and runs a multi-agent pipeline automatically.

Upload PDFs or images, describe the task in plain English, and get structured JSON/CSV output. Save successful runs as reusable workflows and rerun on new files without re-planning.

## What it does

1. **Upload** documents (PDF, PNG, JPG)
2. **Describe** the task (e.g. *"Extract vendor, amount, date. Flag over ₹50K. CSV."*)
3. **Planner** (Groq LLM) builds a step-by-step pipeline
4. **Runner** executes agents in sequence
5. **Save** the plan as a workflow and **rerun** on new uploads

## Agent types

| Stage | Agent | `agent_type` |
|-------|--------|----------------|
| Process | Text Extractor | `processor.text_extract` |
| Process | OCR (RapidOCR / Tesseract) | `processor.ocr` |
| Transform | Field Extractor (LLM) | `transform.field_extractor` |
| Transform | Normalize (dates/amounts) | `transform.normalize` |
| Transform | Rules (flags/filters) | `transform.rules` |
| Output | Formatter (CSV/JSON) | `output.formatter` |

## Tech stack

- **Backend:** Python 3.11+, FastAPI, Groq (Llama 3.3), OpenAI (GPT-4o)
- **Jobs:** Redis + Arq worker (`schedule_run` → `execute_run`)
- **PDF/OCR:** PyMuPDF, RapidOCR / Tesseract, Docling
- **Persistence:** Supabase (Postgres + Storage)
- **Frontend:** Next.js 14 + TypeScript + Tailwind + shadcn/ui
- **Deploy:** Vercel (frontend) + Railway (API + worker) + Upstash Redis

**Live API:** `https://nexora-api-production-065e.up.railway.app` (`GET /api/health`). Frontend is on Vercel (Google sign-in → upload → extract → email/Sheets). **Inbound email** (Mailgun) is implemented in code but **not turned on** — receiving mail needs a domain you control; a Railway hostname cannot be an inbox.

## Quick start

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add GROQ_API_KEY
uvicorn app.main:app --reload
```

API docs: http://localhost:8000/docs

### Run tests

```bash
cd backend
source .venv/bin/activate
pytest tests/ -v
```

### Manual API walkthrough

Use Swagger at http://localhost:8000/docs once the backend is running.

### Supabase (persistence)

See [docs/SUPABASE_SETUP.md](docs/SUPABASE_SETUP.md).

### Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open http://localhost:3000 (backend must be running on :8000).

## Main API flow

```
POST /api/users
POST /api/upload
POST /api/runs/adhoc              # plan + run
POST /api/workflows/from-run/{id}  # save workflow
POST /api/workflows/{id}/runs     # rerun without planner
GET  /api/workflows/{id}/runs     # run history
```

## Project structure

```
backend/     # FastAPI app, supabase/, tests/
frontend/    # Next.js app
docs/        # All reference documentation (start at docs/README.md)
README.md    # This file
```

## Documentation

**Everything is under [`docs/`](docs/README.md).**

| Start here | |
|------------|--|
| [docs/README.md](docs/README.md) | Index |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Prod / secrets |
| [docs/NEXT-STEPS.md](docs/NEXT-STEPS.md) | Current ship order |
| [docs/ENGINEERING-PRINCIPLES.md](docs/ENGINEERING-PRINCIPLES.md) | Code rules |

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Groq API key for planner + refine |
| `OPENAI_API_KEY` | Yes (prod extract) | GPT-4o extraction |
| `JWT_SECRET_KEY` | Yes (prod) | Session JWT |
| `SUPABASE_URL` | No locally | Postgres persistence |
| `SUPABASE_SECRET_KEY` | No locally | Supabase service role key |
| `REDIS_URL` | Prod queue | Omit locally → in-process runs |
| `INBOUND_WEBHOOK_SECRET` | Optional | Mailgun HMAC; empty **rejects** inbound |

## Contributing / Git workflow

We use a simple **Git Flow**-style setup:

| Branch | Purpose |
|--------|---------|
| `main` | Stable, deployable code (releases) |
| `develop` | Integration branch — day-to-day work merges here |
| `feature/*` | One branch per task (e.g. `feature/supabase-setup`) |

### Day-to-day

```bash
git checkout develop
git pull origin develop
git checkout -b feature/my-task

# ... make changes, commit ...

git push -u origin feature/my-task
# Open a PR: feature/my-task → develop
```

### Release to production

When `develop` is tested and ready:

```bash
# Open a PR: develop → main
# Or locally:
git checkout main
git merge develop
git push origin main
```

**Rule of thumb:** never commit directly to `main` — always go through `develop` or a feature branch.

## License

MIT (or your choice — update before publishing)
