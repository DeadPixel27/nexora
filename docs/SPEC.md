# Nexora - Project Spec

**One-liner:** Describe what you want done with your documents -> system builds and runs an AI agent pipeline automatically.

> **Progress snapshot:** Launch stack (V2/V3 + auth/metering) shipped on `develop`. Open work: [NEXT-STEPS.md](./NEXT-STEPS.md). System truth: [ARCHITECTURE.md](./ARCHITECTURE.md).


**Documentation:** All reference docs live in [`docs/`](./README.md).

---

## What It Does

1. User uploads documents (PDFs, images, scanned files)
2. User describes the task in plain English: *"Extract vendor name, invoice number, amount, and date. Flag anything over ₹50K. Give me a CSV."*
3. User picks a **template** or describes a custom task in plain English
4. System plans a pipeline (template = deterministic plan; custom = LLM planner)
5. Each agent executes its step (OCR → Extract → Rules → Format)
6. User watches progress in real-time and downloads results

---

## MVP Scope (2-3 weeks)

### Core Features

- [x] Upload 1-10 documents (PDF, PNG, JPG)
- [x] Template picker on landing page (7 presets → `POST /api/runs/template`)
- [x] Text input: describe what you want extracted/done (→ `POST /api/runs/adhoc`)
- [x] Planner agent: breaks task into steps automatically
- [x] Pipeline execution: runs each agent step sequentially (async background runs)
- [x] Real-time status updates in UI (poll `GET /api/runs/{id}` every 1.5s)
- [x] Results view: structured table + download CSV/JSON
- [x] Pipeline history: expandable run history per workflow (input docs + output)
- [x] Save workflow from a run and rerun on new uploads
- [x] Chat refinement on results page (`POST /api/runs/{id}/refine`) — creates child runs only (no run-level versions)
- [x] Template version history + branch/revert (**workflow scope only**; run-level versions removed in V2)
- [x] Email-based sign-in (restores same Supabase user + workflows)
- [x] Export results via email (`POST /api/runs/{id}/email`) — Resend
- [x] Push results to Google Sheets (`POST /api/runs/{id}/sheets`)
- [x] Workflow settings: name, description, default email/Sheets URL (`PATCH /api/workflows/{id}/settings`)
- [x] Update workflow from refined run (`PATCH /api/workflows/{id}`)
- [x] Inbound email forwarding addresses + Mailgun webhook (`POST /api/inbound/email`)

### Available Agent Types

| Agent | What it does | Status |
|-------|--------------|--------|
| **OCR Agent** | Converts images/scanned PDFs to text (Tesseract) | ✅ `processor.ocr` |
| **Text Extractor** | Pulls raw text from digital PDFs (PyMuPDF) | ✅ `processor.text_extract` |
| **Field Extractor** | LLM extracts structured fields from text based on user description | ✅ `transform.field_extractor` |
| **Normalize Agent** | Deterministic cleanup of dates, amounts, currency, phones | ✅ `transform.normalize` |
| **Rules Agent** | Flag / filter / set on extracted rows (gt, contains, exists, …) | ✅ `transform.rules` |
| **Formatter Agent** | Compiles results into CSV/JSON/table format | ✅ `output.formatter` |
| **Email Agent** | Sends extraction results via email (HTML table + CSV attachment) | ✅ `output.email` |
| **Google Sheets Agent** | Pushes rows to a spreadsheet tab | ✅ `output.google_sheets` |

> **Note:** Core pipeline agents (OCR through Formatter) are always available. Email and Sheets are used when the planner or user requests delivery; export modals on the results page call the REST routes directly.

### Planner Logic

User input + document sample -> LLM decides which agents to run and in what order.

**Example:**

```
User: "Extract name, email, and phone from these resumes"
Documents: 5 PDFs

Planner output:
Step 1: Text Extractor (digital PDFs detected)
Step 2: Field Extractor (fields: name, email, phone)
Step 3: Formatter (output: CSV)
```

**Another example:**

```
User: "Pull invoice amounts, flag anything over 50K, give me Excel"
Documents: 10 scanned images

Planner output:
Step 1: OCR Agent (scanned images detected)
Step 2: Field Extractor (fields: invoice_number, vendor, amount, date)
Step 3: Normalize (amounts/dates canonical)
Step 4: Rules Agent (flag: amount > 50000)
Step 5: Formatter (output: CSV with flag column)
```

---

## Tech Stack

| Layer | Tool | Why | Status |
|-------|------|-----|--------|
| **Frontend** | Next.js 14 + TypeScript + Tailwind CSS | Learn remote-job stack by building | ✅ Done |
| **UI Components** | shadcn/ui | Modern, clean, fast to implement | ✅ Done |
| **Backend** | Python 3.9 + FastAPI | Async API, clean service layer | ✅ Done |
| **AI (Planner)** | Groq (Llama 3.3) | Free tier; replaced original OpenAI plan | ✅ Done |
| **AI (Agents)** | Groq (Llama 3.3) – free tier | Fast, free, good for extraction tasks | ✅ Done |
| **OCR** | Tesseract (pytesseract) | Free, local, no API cost | ✅ Done (needs `brew install tesseract`) |
| **PDF parsing** | PyMuPDF (fitz) | Free, fast, extracts text from digital PDFs | ✅ Done |
| **Database** | Supabase (Postgres) | Users, workflows, runs | ✅ Done (auto fallback to in-memory) |
| **File storage** | Supabase Storage | Uploaded documents | ✅ Done (auto fallback to local disk) |
| **Auth** | Email lookup (no password) | MVP session; future: Supabase Auth | ✅ Done |
| **Deploy (frontend)** | Vercel | Free for personal projects | ❌ Not started |
| **Deploy (backend)** | Railway | $5 free credit/month | ❌ Not started |
| **Pre-deploy hardening** | CORS, rate limits, MIME, Dockerfile, etc. | Done | ✅ Done |
| **Templates** | Code-defined presets + Supabase mirror | `backend/app/templates/` | ✅ Done |
| **User template versions** | Supabase Storage `user-templates` + Postgres index | Workflow versions; refine does not create versions | ✅ Done |
| **Email delivery** | Resend API | `output.email` agent + `POST /api/runs/{id}/email` | ✅ Done |
| **Google Sheets** | Service account JSON | `output.google_sheets` agent + `POST /api/runs/{id}/sheets` | ✅ Done |
| **Inbound email** | Mailgun webhook | Forward to `*@ingest.nexora.app` → auto-run workflow | ✅ Done |
| **Code** | GitHub (public repo) | Recruiters will see this | ✅ [DeadPixel27/nexora](https://github.com/DeadPixel27/nexora) |

---

## Architecture

Full diagrams (system context, three-layer templates, pipeline flow, persistence registry): **[ARCHITECTURE.md](./ARCHITECTURE.md)**

```
┌─────────────────────────────────────────────────────────┐
│         Next.js Frontend V2 (localhost:3000)             │
│  /  compact hero + inline run    /results/[id]  3-col    │
│  /workflows + settings + runs    /account                  │
│  Export bar: email, sheets, save workflow/version        │
└──────────────────────────┬──────────────────────────────┘
                           │ REST API
┌──────────────────────────▼──────────────────────────────┐
│                   FastAPI Backend                          │
│  routes → Depends() → services → registry → backends     │
│  Planner │ Runner │ RefineService │ Email/Sheets/Inbound │
│  Agent Registry + pipeline_refiner (chat refine)         │
└──────────────────────────┬──────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────┐
│   Supabase Postgres + Storage                            │
│   Tables: users, workflows, runs, inbound_addresses, …   │
│   Buckets: Documents (uploads), user-templates (versions)│
└───────────────────────────────────────────────────────────┘
```

See also: [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## Pages (Frontend V2)

### 1. Landing Page (`/`)

- [x] Compact hero + template chips (Source Serif 4)
- [x] Inline upload + task + **Run** (single action row)
- [x] Template picker → `POST /api/runs/template` or adhoc plan

### 2. Results Page (`/results/[runId]`)

- [x] Three-column layout: documents | results tabs | refine chat
- [x] Live step progress, table view, CSV/JSON download
- [x] Export bar: email modal, Sheets modal, save workflow, save version (workflow scope)
- [x] Chat refine panel — branches to child run (no run-level version UI)

### 3. Workflows (`/workflows`, `/workflows/[id]`, `/workflows/[id]/settings`, `/workflows/[id]/runs/[runId]`)

- [x] Card grid list, detail with sidebar + rerun
- [x] Settings page: name, description, default email/Sheets URL
- [x] Workflow-scoped run results page
- [x] Template version history + revert (workflow only)

### 4. Account (`/account`)

- [x] Sign in / create account by email
- [x] Sign out (clears localStorage session)
- [x] Same email restores workflows from Supabase

---

## API Endpoints (Backend)

### Core

| Method | Endpoint | What it does | Status |
|--------|----------|--------------|--------|
| GET | `/api/health` | Health + active backends | ✅ |
| POST | `/api/upload` | Upload documents, returns upload_id | ✅ |
| GET | `/api/uploads/{id}` | List documents in upload batch | ✅ |
| GET | `/api/uploads/{id}/documents/{doc_id}` | Download input document | ✅ |
| POST | `/api/pipeline/create` | Plan pipeline from task + upload | ✅ |
| GET | `/api/templates` | List pipeline templates (summary: id, name, icon, category) | ✅ |
| GET | `/api/templates/{id}` | Get full template (fields, rules, extraction_instructions) | ✅ |
| POST | `/api/runs/adhoc` | Plan + start run (background) | ✅ |
| POST | `/api/runs/template` | Run from template id (deterministic plan) | ✅ |
| POST | `/api/runs` | Run explicit steps (background) | ✅ |
| GET | `/api/runs/{id}` | Poll run status + results | ✅ |
| POST | `/api/runs/{id}/refine` | Chat refine → child run (no version created) | ✅ |
| POST | `/api/runs/{id}/email` | Email results via Resend (HTML + CSV) | ✅ |
| POST | `/api/runs/{id}/sheets` | Push results to Google Sheet | ✅ |

> **Removed in V2:** `GET/POST /api/runs/{id}/template-versions`, `POST /api/runs/{id}/revert` — versions live on workflows only; undo refine via browser back.

### Auth & Users

| Method | Endpoint | What it does | Status |
|--------|----------|--------------|--------|
| POST | `/api/auth/session` | Sign in or register by email | ✅ |
| POST | `/api/users` | Create/restore user (delegates to auth) | ✅ |
| GET | `/api/users/{id}` | Get user | ✅ |
| GET | `/api/users/{id}/workflows` | List user's workflows | ✅ |

### Workflows

| Method | Endpoint | What it does | Status |
|--------|----------|--------------|--------|
| POST | `/api/workflows` | Save workflow template | ✅ |
| POST | `/api/workflows/from-run/{id}` | Save plan from a run | ✅ |
| GET | `/api/workflows/{id}` | Get workflow + steps | ✅ |
| GET | `/api/workflows/{id}/runs` | List all runs for a workflow | ✅ |
| POST | `/api/workflows/{id}/runs` | Rerun saved workflow | ✅ |
| PATCH | `/api/workflows/{id}` | Update workflow from refined run (new version) | ✅ |
| PATCH / PUT | `/api/workflows/{id}/settings` | Update metadata + delivery defaults | ✅ |
| GET | `/api/workflows/{id}/template-versions` | List workflow template versions | ✅ |
| GET | `/api/workflows/{id}/template-versions/{version_id}` | Preview workflow version | ✅ |
| POST | `/api/workflows/{id}/revert` | Set workflow head to earlier version | ✅ |

### Delivery & Inbound

| Method | Endpoint | What it does | Status |
|--------|----------|--------------|--------|
| POST | `/api/inbound/email` | Mailgun webhook — process forwarded attachments | ✅ |
| POST | `/api/inbound-addresses` | Create forwarding address for a workflow | ✅ |
| GET | `/api/inbound-addresses?user_id=...` | List user's forwarding addresses | ✅ |
| DELETE | `/api/inbound-addresses/{id}` | Delete forwarding address | ✅ |

### Admin (owner — deferred)

| Method | Endpoint | What it does | Status |
|--------|----------|--------------|--------|
| GET | `/api/admin/templates/feedback` | List user refinement events | ✅ |
| POST | `/api/admin/templates/{id}/synthesize` | LLM synthesis from user feedback | ✅ |
| POST | `/api/admin/templates/{id}/preview` | Preview master template changes | ✅ |
| POST | `/api/admin/templates/{id}/apply` | Persist master template changes | ⬜ later (`ADMIN_API_KEY`) |

### Debug

| Method | Endpoint | What it does | Status |
|--------|----------|--------------|--------|
| POST | `/api/extract` | Extract from raw text | ✅ |

### Frontend API client (`frontend/src/lib/api.ts`)

Typed fetch wrappers used by all pages. V2 alignment:

| Area | Client behavior |
|------|-----------------|
| **Run versions** | Removed `getRunTemplateVersions`, `getRunTemplateVersion`, `revertRunToVersion` (backend removed in V2) |
| **Workflow versions** | `getWorkflowTemplateVersions`, `revertWorkflowToVersion` — workflow scope only |
| **Workflow settings** | `WorkflowResponse` includes `default_email`, `default_sheets_url`; `updateWorkflowSettings` sends same field names as backend |
| **Export** | `emailResults({ to, subject })`, `pushToSheets({ url, sheet_name })` — aliases match backend `validation_alias` |
| **Workflow update** | `updateWorkflowFromRun` sends `from_run_id` + `version_name` |

---

## Backend Architecture Patterns

| Pattern | Location | Purpose |
|---------|----------|---------|
| **Protocol** (interface) | `persistence/protocols.py`, `services/auth/protocols.py` | Contracts for backends |
| **Registry** (wiring) | `persistence/registry.py`, `services/auth/registry.py` | Config → implementation |
| **FastAPI Depends** | `api/dependencies.py` | Inject services into routes |
| **Service classes** | `users/`, `workflows/`, `templates/`, `pipeline/` | Business logic |
| **Version service** | `UserTemplateVersionService` | Workflow template payloads in Storage |
| **Template catalog** | `app/templates/` + `persistence/templates/` | Code-defined presets; DB mirror via bootstrap |
| **Validation utils** | `validation/task_input.py` | Task sanitization (no Pydantic → services import) |
| **Domain errors** | `models/domain/document.py` | `InvalidUploadError` etc.; routes map to HTTP |

See [docs/ENGINEERING-PRINCIPLES.md](./ENGINEERING-PRINCIPLES.md) for coding rules. Adding a new storage backend (e.g. S3): one file + one line in `registry.py` + env var.

---

## Database Schema

> Implemented in `backend/supabase/schema.sql`. Seed templates via `supabase/seed_templates.sql`.

| Table | Purpose |
|-------|---------|
| `users` | `id`, `name`, `email` (indexed; used for sign-in lookup) |
| `workflows` | Saved pipeline templates per user; V2: `default_email`, `default_sheets_url` |
| `workflow_steps` | Steps belonging to a workflow |
| `workflow_runs` | Execution records (status, result JSON, planned_steps) |
| `workflow_step_runs` | Per-step status + output during a run |
| `pipeline_templates` | Editable task presets (landing page; not user workflows) |
| `user_template_versions` | Metadata index for **workflow** template versions |
| `refinement_events` | User refine messages (owner aggregation) |
| `inbound_addresses` | Unique `flow-*@ingest.nexora.app` → workflow mapping |

Document files are stored in **Supabase Storage** (`Documents` bucket), not in Postgres.

## Environment Variables

### Backend (`backend/.env`)

```env
GROQ_API_KEY=...
SUPABASE_URL=...
SUPABASE_SECRET_KEY=...
PERSISTENCE_BACKEND=auto        # auto | memory | supabase
DOCUMENT_STORAGE=auto           # auto | local | supabase
SUPABASE_DOCUMENTS_BUCKET=Documents   # must match bucket name exactly (case-sensitive)
AUTH_BACKEND=email              # email | supabase (future)
CORS_ORIGINS=http://localhost:3000    # comma-separated; set prod URL on deploy
RATE_LIMIT_RUNS_ADHOC=10/minute
RATE_LIMIT_UPLOAD=20/minute
MAX_UPLOAD_SIZE_MB=10

# V2 delivery (optional — export modals return 502 without these)
RESEND_API_KEY=
RESEND_FROM_EMAIL=onboarding@resend.dev
GOOGLE_SERVICE_ACCOUNT_JSON=

# V2 inbound email (optional)
INBOUND_EMAIL_DOMAIN=ingest.nexora.app
INBOUND_WEBHOOK_SECRET=
```

### Frontend (`frontend/.env.local`)

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB=10
```

---

## Build Plan

### Week 1: Backend + Core Pipeline ✅

- [x] FastAPI project, upload, OCR, PDF extraction
- [x] Planner + all 5 agents + unified registry
- [x] Pipeline runner with async background execution + incremental step saves
- [x] Supabase persistence (optional in-memory fallback)
- [x] Workflows, users, run history
- [x] Persistence registry (Protocol + swappable backends)
- [x] Document storage registry (local / Supabase Storage)
- [x] FastAPI Depends service injection
- [x] Email auth service (strategy pattern)
- [x] Landing page template picker + `runTemplate()` API
- [x] 38 backend tests passing
- [x] Local planning docs in `docs/` (gitignored)

### Week 2: Frontend ✅

- [x] Next.js 14 + TypeScript + Tailwind + shadcn/ui
- [x] Landing page with hero, examples, upload + run
- [x] Results page with polling, expandable steps, CSV/JSON download
- [x] Workflows list + detail + rerun + expandable run history
- [x] Account page with email sign-in
- [x] Mobile nav, toasts, empty states
- [x] Frontend directory guide (see ARCHITECTURE §11)
- [x] E2E tested locally
- [x] PR #2 merged to `develop`

### Week 3: Pre-deploy hardening ✅ (merged PR #3 → `develop` → `main`)

- [x] CORS from `CORS_ORIGINS` env var
- [x] Rate limiting (`slowapi` on adhoc + upload + template runs)
- [x] Prompt injection guard (`validation/task_input.py`)
- [x] MIME validation (`filetype` byte sniffing)
- [x] Per-file + batch file size limits
- [x] LLM retry (`tenacity` on Groq client)
- [x] Shared `to_planned_steps()` mapper
- [x] `InvalidUploadError` domain exception
- [x] Backend `Dockerfile` + `.dockerignore`
- [x] Frontend `error.tsx` error boundary
- [x] Code-defined templates (`backend/app/templates/`) + `POST /api/runs/template`
- [x] Merged to `develop` and `main` (`800cc03`)

### Week 4: Deploy + Demo ❌ (current focus)

- [ ] Deploy backend to Railway
- [ ] Deploy frontend to Vercel
- [ ] Set production env vars + `CORS_ORIGINS` (+ Resend / Sheets / inbound secrets)
- [ ] End-to-end smoke test on live URLs
- [ ] Record 60-sec demo video
- [ ] Root README with screenshots + live demo link
- [ ] Add to LinkedIn / resume
- [x] Merge `develop` → `main` for release (`800cc03`)

### V2: Frontend + Backend redesign ✅ (merged to `develop`, 2026-08-08)

- [x] Frontend V2 UI — compact home, 3-col results, export modals, workflow settings ([ARCHITECTURE.md](./ARCHITECTURE.md))
- [x] Backend V2 — email, Sheets, inbound, workflow PATCH/settings ([ARCHITECTURE.md](./ARCHITECTURE.md))
- [x] Versioning simplification — workflow-only versions; refine creates child runs only
- [x] `output.email` + `output.google_sheets` agents
- [x] Migrations `008_inbound_addresses`, `009_workflow_delivery_defaults`; `schema.sql` synced
- [x] E2E smoke script updated (`frontend/scripts/e2e-smoke.sh`) — 32 passed
- [x] 66 backend tests passing
- [x] `schema.sql` synced + Sheets A1 quoting fix (`dfef3a7`)
- [x] Frontend `api.ts` audit fixes — dead run-version clients removed; settings field names match backend

### V2 polish (optional, pre-deploy)

- [ ] Inbound webhook: email results back to sender when run completes
- [x] Wire workflow settings page to `POST /api/inbound-addresses` (real addresses vs placeholder) — **superseded for launch:** inbound gated behind Pro waitlist (`/pricing?source=inbound_email`); backend CRUD kept
- [x] Sheets/email setup walkthrough in Workflow Settings + Sheets modal (`GET /api/integrations` exposes share-as-Editor email)
- [x] Waitlist `source` telemetry: `normal` | `pages_exhausted` | `inbound_email`
- [ ] Add `RESEND_API_KEY` / `GOOGLE_SERVICE_ACCOUNT_JSON` for live export testing

---

## Master Tracker

> **Single source of truth for open work:** [NEXT-STEPS.md](./NEXT-STEPS.md).

### Gap priority (from code review)

| # | Task | Time | Impact | Status |
|---|------|------|--------|--------|
| 1 | Fix CORS (env var) | 10 min | Deploy blocker | ✅ |
| 2 | Add rate limiting | 30 min | Cost protection | ✅ |
| 3 | Add Dockerfile | 15 min | Deploy blocker | ✅ |
| 4 | Add prompt injection guard | 30 min | Security | ✅ |
| 5 | Add LLM retry | 20 min | Reliability | ✅ |
| 6 | Fix code duplication (`to_planned_steps`) | 10 min | Code quality | ✅ |
| 7 | Add error boundary | 15 min | UX | ✅ |
| 8 | Add file cleanup (24h TTL) | 1–2 hr | Privacy + cost | ⬜ |
| 9 | Add auth (Supabase Auth) | 3–4 hr | Security | ⬜ |
| 10 | Add file content validation (`filetype`) | 30 min | Security | ✅ |

**Total remaining to production-ready:** ~2–4 hours (deploy + optional auth/cleanup).

### Feature timeline (post-MVP)

| Version | Feature | Effort | Doc |
|---------|---------|--------|-----|
| V1.0.1 | Template library (picker + API) | ~3 hr | ✅ Done — `backend/app/templates/` |
| V1.1 | Email delivery (Resend) | Medium | ✅ Done — `output.email`, `POST /api/runs/{id}/email` |
| V1.2 | Google Sheets push | Medium | ✅ Done — `output.google_sheets`, `POST /api/runs/{id}/sheets` |
| V1.3 | Chat refinement + versioned user templates | High | ✅ Done — workflow versions only in V2 |
| V2.0 | Frontend V2 redesign + export/settings UX | High | ✅ Done — [ARCHITECTURE.md](./ARCHITECTURE.md) |
| V2.0 | Backend V2 delivery + inbound email | High | ✅ Done — [ARCHITECTURE.md](./ARCHITECTURE.md) |
| V2.1 | Live PDF preview + field highlights | 6–10 hr | `docs/NEXT-STEPS.md` |
| V2.1 | Auto-correct / learning from edits | Medium | `docs/NEXT-STEPS.md` |
| V3.0 | Inbound reply-to-sender after run completes | Medium | partial — webhook runs workflow; no auto-reply yet |
| V3.0 | Watch folder / inbox automation | 12–20 hr | `docs/NEXT-STEPS.md` |

### Phase A — Deploy (P0)

| Status | Task | Doc |
|--------|------|-----|
| [x] | CORS from env var | GAPS #3 (done) |
| [x] | Backend Dockerfile | GAPS #9 (done) |
| [ ] | Deploy backend (Railway) + env vars | `docs/NEXT-STEPS.md` |
| [ ] | Deploy frontend (Vercel) + `NEXT_PUBLIC_API_URL` | `docs/NEXT-STEPS.md` |
| [ ] | Live smoke test (upload → template run → download) | `docs/NEXT-STEPS.md` |
| [ ] | README screenshots + live demo URL | `docs/NEXT-STEPS.md` |
| [ ] | 60-sec demo video | `docs/NEXT-STEPS.md` |

### Phase B — Security & reliability (P1)

| Status | Task | Doc |
|--------|------|-----|
| [x] | Rate limiting on `/api/runs/adhoc`, `/api/runs/template`, `/api/upload` | ✅ |
| [x] | Prompt injection guard | GAPS #4 (done) |
| [x] | MIME validation (`filetype`) | GAPS #5 (done) |
| [x] | File size limits (per-file + batch) | GAPS #5 (done) |
| [x] | LLM retry (429 / 5xx) | GAPS #6 (done) |
| [x] | Frontend error boundary | GAPS #10 (done) |
| [x] | Dedupe `_to_planned_steps()` | GAPS #7 (done) |
| [x] | Merge pre-deploy work to `develop` and `main` | PR #3, `800cc03` |

### Phase C — Ops & quality (P2)

| Status | Task | Doc |
|--------|------|-----|
| [ ] | GitHub Actions CI (`pytest` + `npm run build`) | GAPS #12 (done) |
| [ ] | Upload file cleanup (24h TTL sweep) | GAPS #8 (done) |
| [ ] | System prompts in config/files | GAPS #15 (done) |
| [ ] | Frontend tests (Vitest) | GAPS #14 (done) |
| [ ] | Usage metering (Groq tokens per run) | GAPS #13 (done) |

### Phase D — Auth (before public launch)

| Status | Task | Doc |
|--------|------|-----|
| [ ] | Supabase Auth provider (password / magic link) | GAPS #1 (done) |
| [ ] | Frontend Supabase JS sign-in/sign-up | GAPS #1 (done) |
| [ ] | Keep `email` provider for local dev/tests | GAPS #1 (done) |

### Phase E — Template library (V1.0.1) ✅

**Code canonical:** `backend/app/templates/` (7 modules) → `registry.py` → repos + bootstrap SQL sync.

| Status | Task | Doc |
|--------|------|-----|
| [x] | `backend/app/templates/` Python modules (invoice, resume, contract, …) | `app/templates/` |
| [x] | Rich templates: `fields`, `extraction_instructions`, `rules`, `output_format` | `app/templates/` |
| [x] | `TemplateRepository` — code registry at runtime | `persistence/templates/` |
| [x] | `GET /api/templates` + `GET /api/templates/{id}` | API |
| [x] | `POST /api/runs/template` — deterministic plan from template | API |
| [x] | Inject `extraction_instructions` into field extractor config | `template_planner.py` |
| [x] | Landing page template picker + `runTemplate()` when selected | Frontend |
| [x] | `pipeline_templates` table + seed SQL (DB mirror) | `supabase/seed_templates.sql` |
| [x] | Bootstrap syncs code templates to Supabase on startup | `bootstrap.py` |
| [x] | Run `setup_templates.sql` in Supabase | User completed |
| [ ] | Category filter UI (API supports `?category=`) | optional V1.0.2 |

### Phase I — Versioned user templates (V1.3) ✅

| Status | Task | Doc |
|--------|------|-----|
| [x] | Three-layer model: master → run versions → workflow versions | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [x] | `user_template_versions` + `refinement_events` tables (migration 007) | `supabase/migrations/007_*.sql` |
| [x] | Supabase Storage bucket `user-templates` for payloads | [SUPABASE_SETUP.md](./SUPABASE_SETUP.md) |
| [x] | `POST /api/runs/{id}/refine` + version pointer dedup in Postgres | API |
| [x] | List / preview / revert APIs (**workflow scope only**) | `template_versions.py` |
| [x] | Frontend workflow settings + export modals | Frontend V2 |
| [ ] | Inbound auto-reply with results to sender | deferred |
| [ ] | Owner master template apply (`ADMIN_API_KEY`) | deferred |

### Phase F — Product features (V1.1+)

| Status | Version | Feature | Doc |
|--------|---------|---------|-----|
| [x] | V1.1 | Email delivery (Resend) — `output.email` agent | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [x] | V1.2 | Google Sheets push — `output.google_sheets` | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [x] | V1.3 | Chat refinement on results — `POST /api/runs/{id}/refine` | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [x] | V2.0 | Frontend V2 + Backend V2 delivery APIs | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [ ] | V2.1 | Live PDF preview + field highlights | [NEXT-STEPS.md](./NEXT-STEPS.md) |
| [ ] | V2.1 | Auto-correct / learning from user edits | [NEXT-STEPS.md](./NEXT-STEPS.md) |
| [ ] | V3.0 | Inbound email auto-reply to sender | partial webhook in V2 |
| [ ] | V3.0 | Watch folder / inbox automation | [NEXT-STEPS.md](./NEXT-STEPS.md) |

### Phase G — New agents (planned)

| Status | Agent type | Version | Doc |
|--------|------------|---------|-----|
| [x] | `output.email` | V1.1 | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [x] | `output.google_sheets` | V1.2 | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [ ] | `transform.summarizer` | V1.3 | [AGENTS.md](./AGENTS.md) |
| [ ] | `transform.classifier` | V2.0 | [AGENTS.md](./AGENTS.md) |
| [ ] | `processor.table_extract` | V2.0 | [AGENTS.md](./AGENTS.md) |
| [ ] | `transform.redact` | V2.0 | [AGENTS.md](./AGENTS.md) |
| [ ] | `output.webhook` | V2.0 | [AGENTS.md](./AGENTS.md) |
| [ ] | `processor.translate` | V3.0 | [AGENTS.md](./AGENTS.md) |
| [ ] | `trigger.watch_folder` | V3.0 | [AGENTS.md](./AGENTS.md) |

### Phase H — Infrastructure & polish

| Status | Task | Doc |
|--------|------|-----|
| [ ] | SSE / WebSockets for run status (replace polling) | GAPS #11 (done) |
| [ ] | S3 document backend (registry ready) | SPEC Future |
| [ ] | `global-error.tsx` (optional) | GAPS #10 (done) |
| [x] | Chat refinement: cache OCR text on run for partial re-run | [ARCHITECTURE.md](./ARCHITECTURE.md) |
| [x] | Chat refinement: `parent_run_id` lineage column | [ARCHITECTURE.md](./ARCHITECTURE.md) |

### Completed (reference)

<details>
<summary>MVP + docs + hardening (click to expand)</summary>

- [x] All 5 v1 agents + planner + async runner
- [x] Supabase Postgres + Storage (with in-memory/local fallback)
- [x] Persistence + auth registry, FastAPI Depends
- [x] Full Next.js frontend (/, results, workflows, account)
- [x] Email sign-in, workflow save/rerun, run history
- [x] Core docs: ENGINEERING-PRINCIPLES, ARCHITECTURE, SPEC, AGENTS, NEXT-STEPS, DEPLOYMENT
- [x] Template library (code-defined, 7 templates, `POST /api/runs/template`)
- [x] Versioned user templates (workflow scope; Storage + branch/revert APIs, 66 tests)
- [x] Frontend V2 + Backend V2 (email, Sheets, inbound, workflow settings)

</details>

---

### Future (quick reference)

Legacy list — see [Master Tracker](#master-tracker) for live status.

- [ ] Supabase Auth (password / magic link) — Phase D
- [ ] SSE/WebSockets instead of polling — Phase H
- [ ] S3 document backend — Phase H

---

## Cost

| Item | Monthly cost |
|------|--------------|
| Groq (planner + agents) | $0 (free tier) |
| Tesseract OCR | $0 (local) |
| Railway (backend) | $0-5 |
| Vercel (frontend) | $0 |
| Supabase (DB + storage) | $0 |
| **Total** | **~$0-5/month** |

---

## What This Proves To Employers

1. **System design** — multi-agent pipeline, registry pattern, swappable backends — ✅
2. **AI/LLM integration** — planner + extraction via Groq API — ✅
3. **Python backend** — FastAPI, async runs, Depends DI, Protocol interfaces — ✅
4. **Frontend** — Next.js, TypeScript, polling, workflows UI — ✅
5. **Full-stack deployment** — live demo — ❌ not yet (Phase A)
6. **Document processing** — OCR, PDF parsing, structured extraction — ✅
7. **Database design** — normalized schema + JSONB + Supabase Storage — ✅

This is not a tutorial project. This is production-level architecture on a public repo.

---

*Created: 2026-08-02*  
*Updated: 2026-08-08 — V2 full-stack; `api.ts` parity; schema.sql + Sheets quoting (`dfef3a7`)*
