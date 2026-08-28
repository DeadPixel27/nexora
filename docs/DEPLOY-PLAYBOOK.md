# Nexora — End-to-End Deploy Playbook

Step-by-step checklist to go from zero to a live production deploy. Work top to bottom; each phase feeds the next. Tick off each item as you complete it.

**Time estimate:** ~2 h total, mostly waiting on dashboards.

**Current deploy (2026-08-24):** API is live at `https://nexora-api-production-065e.up.railway.app`. Use this playbook to reproduce a stack. **Phase 9 (Mailgun) is skipped** for the CV project until we own a receiving domain.

Related reference docs (do not need to read before starting):
- [DEPLOYMENT.md](./DEPLOYMENT.md) — full env var reference + topology
- [SUPABASE_SETUP.md](./SUPABASE_SETUP.md) — Supabase troubleshooting
- [SCALING-AND-JOBS.md](./SCALING-AND-JOBS.md) — worker scaling decisions

---

## Phase 0 — Prerequisites (~5 min)

Collect these before you open any dashboard:

- [ ] **Groq API key** — [console.groq.com/keys](https://console.groq.com/keys)
- [ ] **OpenAI API key** — [platform.openai.com/api-keys](https://platform.openai.com/api-keys)
- [ ] **JWT secret** — run locally and save the output:
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(32))"
  ```
- [ ] Repo is on `main` and remote is `https://github.com/DeadPixel27/nexora`
  ```bash
  git remote -v   # should show DeadPixel27/nexora
  git checkout main && git pull
  ```

---

## Phase 1 — Supabase (~20 min)

> One new project. Three SQL runs. Done.

- [ ] Go to [supabase.com](https://supabase.com) → **New project**
  - Name: `nexora`
  - Region: pick the one closest to where you will deploy Railway (e.g. `ap-south-1` for Mumbai)
  - Save the database password somewhere safe
- [ ] Wait ~2 min for provisioning
- [ ] Dashboard → **SQL Editor** → **New query** → paste and run [`backend/supabase/schema.sql`](../backend/supabase/schema.sql) → click **Run** → expect `Success`
- [ ] Same SQL Editor → paste and run [`backend/supabase/seed_templates.sql`](../backend/supabase/seed_templates.sql) → **Run** → `Success`
- [ ] Same SQL Editor → paste and run [`backend/supabase/migrations/013_storage_private.sql`](../backend/supabase/migrations/013_storage_private.sql) → **Run** → `Success`
  - This creates the `documents` and `user-templates` Storage buckets as **private** and adds a restrictive deny policy for `anon` / `authenticated` clients.
- [ ] Dashboard → **Storage** → confirm both buckets exist and show `Public: OFF`
- [ ] Dashboard → **Project Settings** → **API** → copy:
  - **Project URL** → save as `SUPABASE_URL`
  - **Secret key** (`sb_secret_…`) → save as `SUPABASE_SECRET_KEY`

> Never use the `anon` / `publishable` key on the backend. Only the `sb_secret_…` key.

### Already deployed (existing Supabase project)

If prod was created from an older `schema.sql` (before `017`), **do not** re-run the full consolidated schema. Apply only the incremental migration:

1. SQL Editor → run [`backend/supabase/migrations/017_enable_rls.sql`](../backend/supabase/migrations/017_enable_rls.sql) → `Success`
2. Dashboard → **Database** → **Tables** → RLS warnings should clear

New projects get RLS from `schema.sql` step above; `017` is only for live DBs that predate it.

---

## Phase 2 — Google Cloud / OAuth (~30 min)

> One GCP project gives you both Google Sign-In (OAuth) and Sheets export (service account).

- [ ] Go to [console.cloud.google.com](https://console.cloud.google.com) → create new project
  - Name: `nexora`
- [ ] **APIs & Services** → **Enable APIs** → search for and enable:
  - `Google Sheets API`
- [ ] **APIs & Services** → **Credentials** → **Create credentials** → **OAuth 2.0 Client ID**
  - Application type: `Web application`
  - Name: `nexora-web`
  - **Authorized JavaScript origins**: leave blank for now (you will add Vercel + Railway URLs in Phase 7)
  - Click **Create** → copy the **Client ID** → save as `GOOGLE_CLIENT_ID` (used in both Railway and Vercel)
- [ ] **Credentials** → **Create credentials** → **Service account**
  - Name: `nexora-sheets`
  - Role: no role needed (Sheets access is granted per-spreadsheet)
  - After creating, open the service account → **Keys** → **Add key** → **JSON** → download
  - Minify the JSON to one line (no newlines):
    ```bash
    python -c "import json,sys; print(json.dumps(json.load(open('path/to/key.json'))))"
    ```
  - Save the one-line result as `GOOGLE_SERVICE_ACCOUNT_JSON`
  - Note the `client_email` field — users must share spreadsheets with this address as **Editor**

---

## Phase 3 — Upstash Redis (~5 min)

> Already created. Just copy the URL.

- [ ] Open [upstash.com](https://upstash.com) → your `nexora-jobs` database
- [ ] Copy the **Redis URL** — it starts with `rediss://` (TLS required)
- [ ] Save as `REDIS_URL` — you will paste this into both Railway services

If you have not created it yet:
- New database → name `nexora-jobs` → region matching Railway → TLS ON → copy URL

---

## Phase 4 — Resend (~15 min)

> Outbound email for workflow delivery notifications.

- [ ] Go to [resend.com](https://resend.com) → sign up / create account **nexora**
- [ ] **API Keys** → **Create API key** → copy → save as `RESEND_API_KEY`
- [ ] For `RESEND_FROM_EMAIL`, use `onboarding@resend.dev` for now (Resend's shared dev domain — no DNS setup required)
  - Upgrade to a verified `nexora.app` sending domain later when you have the domain

---

## Phase 5 — Railway API service (~20 min)

- [ ] Go to [railway.app](https://railway.app) → **New project**
- [ ] **Add service** → **GitHub repo** → connect `DeadPixel27/nexora`
  - Service name: `nexora-api`
  - Root directory: `backend`
  - Dockerfile is auto-detected from [`backend/Dockerfile`](../backend/Dockerfile)
- [ ] Add all variables below in **Variables** tab (use **Raw Editor** to paste the block):

```env
APP_ENV=production
SUPABASE_URL=<from Phase 1>
SUPABASE_SECRET_KEY=<from Phase 1>
JWT_SECRET_KEY=<generated in Phase 0>
OPENAI_API_KEY=<your key>
GROQ_API_KEY=<your key>
GOOGLE_CLIENT_ID=<from Phase 2>
AUTH_ALLOW_EMAIL=false
PERSISTENCE_BACKEND=auto
DOCUMENT_STORAGE=auto
SUPABASE_DOCUMENTS_BUCKET=documents
USER_TEMPLATE_STORAGE=auto
SUPABASE_USER_TEMPLATES_BUCKET=user-templates
REDIS_URL=<from Phase 3 — rediss://...>
CORS_ORIGINS=http://localhost:3000
RESEND_API_KEY=<from Phase 4>
RESEND_FROM_EMAIL=onboarding@resend.dev
GOOGLE_SERVICE_ACCOUNT_JSON=<minified one-line JSON from Phase 2>
```

> `CORS_ORIGINS` is temporarily `localhost` — you will update it with the real Vercel URL after Phase 7.

- [ ] **Settings** → **Networking** → **Generate Domain** → copy the Railway API URL (e.g. `https://nexora-api-production.up.railway.app`)
- [ ] Deploy (triggered automatically on push or manually via **Deploy**)
- [ ] Confirm the API is healthy:
  ```bash
  curl https://<railway-api-url>/api/health
  ```
  Expected:
  ```json
  {
    "status": "ok",
    "service": "nexora-api",
    "persistence": "supabase",
    "database": "connected",
    "document_storage": "supabase"
  }
  ```
- [ ] If health shows `degraded` or `not_configured`, check Railway logs and verify Supabase env vars

---

## Phase 6 — Railway Worker service (~5 min)

> Same repo, same env vars, different start command. No public URL.

- [ ] In the same Railway project → **Add service** → **GitHub repo** → `DeadPixel27/nexora`
  - Service name: `nexora-worker`
  - Root directory: `backend`
- [ ] Copy **all env vars** from `nexora-api` into `nexora-worker` (Railway lets you copy between services)
- [ ] **Settings** → **Deploy** → **Start command**:
  ```
  arq app.jobs.worker.WorkerSettings
  ```
- [ ] Do **not** generate a public domain for this service
- [ ] Leave **Replicas = 1** (scale to 3 only for Reddit/HN traffic spikes, then back to 1)
- [ ] Deploy → check logs → expect:
  ```
  Starting arq worker version ...
  redis connection successful
  ```

---

## Phase 7 — Vercel frontend (~15 min)

- [ ] Go to [vercel.com](https://vercel.com) → **Add New Project** → import `DeadPixel27/nexora`
  - Project name: `nexora`
  - Root directory: `frontend`
  - Framework: Next.js (auto-detected)
- [ ] Add environment variables:

```env
NEXT_PUBLIC_API_URL=https://<railway-api-url-from-phase-5>
NEXT_PUBLIC_GOOGLE_CLIENT_ID=<from Phase 2>
NEXT_PUBLIC_AUTH_ALLOW_EMAIL=false
NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB=10
```

- [ ] Click **Deploy** → wait for build to finish → copy the Vercel URL (e.g. `https://nexora.vercel.app`)

### After Vercel URL is known — two follow-up steps:

- [ ] **Railway nexora-api** → Variables → update `CORS_ORIGINS` to the real Vercel URL:
  ```
  CORS_ORIGINS=https://nexora.vercel.app
  ```
  Redeploy nexora-api.

- [ ] **GCP OAuth client** → Credentials → `nexora-web` → add to **Authorized JavaScript origins**:
  ```
  https://nexora.vercel.app
  ```
  Save. (No redeploy needed — GCP propagates in ~5 min.)

---

## Phase 8 — Smoke test (~10 min)

Run these in order. Stop and fix before continuing if anything fails.

- [ ] Health check:
  ```bash
  curl https://<railway-url>/api/health
  ```
  → `status: ok`, `persistence: supabase`, `database: connected`, `document_storage: supabase`

- [ ] Open `https://nexora.vercel.app` in browser → **Sign in with Google** → confirm session is stored (no error, name appears in nav)

- [ ] Upload a small PDF → run it (adhoc or template) → wait for completion
  - Check **Railway worker logs** → should see `Worker picked up job` + `run_id`
  - Run should reach `completed` status in UI

- [ ] Integrations check:
  ```bash
  curl -H "Authorization: Bearer <your-jwt>" https://<railway-url>/api/integrations
  ```
  → `"inbound_configured": false`, `"sheets_configured": true` (if `GOOGLE_SERVICE_ACCOUNT_JSON` is set)

- [ ] (Optional) Sheets test: share a spreadsheet with the `client_email` from `/api/integrations` as **Editor** → go to Workflow Settings → push to Sheets → rows appear in the sheet

- [ ] IDOR check: open a second incognito window → sign in as a different user → try to fetch the first user's run:
  ```bash
  GET /api/runs/<run_id_from_first_user>
  ```
  → expect **403 Forbidden**

---

## Phase 9 — Mailgun inbound (skip — needs a domain you own)

> Skip for launch / this CV demo. Railway `*.up.railway.app` is **HTTP only** — it cannot receive `flow-…@` mail. Do this when you buy a domain and can add MX + TXT.

Webhook URL when you do it:

`https://nexora-api-production-065e.up.railway.app/api/inbound/email`

- [ ] Create Mailgun account **nexora** at [mailgun.com](https://mailgun.com)
- [ ] **Sending** → **Domains** → **Add domain** → `ingest.<your-domain>`
  - Complete DNS verification: add MX + TXT records Mailgun shows you
  - Wait for DNS propagation and Mailgun to verify
- [ ] **Receiving** → **Routes** → **Create route**:
  - Expression: `match_recipient(".*@ingest.<your-domain>")`
  - Action: **Store and notify** → URL: `https://nexora-api-production-065e.up.railway.app/api/inbound/email`
- [ ] Copy the domain's **HTTP webhook signing key** from Mailgun domain settings
- [ ] Add to Railway (both nexora-api and nexora-worker):
  ```env
  INBOUND_EMAIL_DOMAIN=ingest.<your-domain>
  INBOUND_WEBHOOK_SECRET=<signing key from Mailgun>
  ```
  Redeploy nexora-api.
- [ ] Verify:
  ```bash
  curl https://nexora-api-production-065e.up.railway.app/api/integrations
  ```
  → `"inbound_configured": true`
- [ ] Create an inbound address in Workflow Settings → send a small PDF as an email attachment to it → confirm run appears

---

## Quick reference — all env vars in one place

### Railway (nexora-api + nexora-worker)

| Variable | Value |
|----------|-------|
| `APP_ENV` | `production` |
| `SUPABASE_URL` | from Phase 1 |
| `SUPABASE_SECRET_KEY` | from Phase 1 |
| `JWT_SECRET_KEY` | generated locally |
| `OPENAI_API_KEY` | from OpenAI |
| `GROQ_API_KEY` | from Groq |
| `GOOGLE_CLIENT_ID` | from Phase 2 |
| `AUTH_ALLOW_EMAIL` | `false` |
| `PERSISTENCE_BACKEND` | `auto` |
| `DOCUMENT_STORAGE` | `auto` |
| `SUPABASE_DOCUMENTS_BUCKET` | `documents` |
| `USER_TEMPLATE_STORAGE` | `auto` |
| `SUPABASE_USER_TEMPLATES_BUCKET` | `user-templates` |
| `REDIS_URL` | from Phase 3 (`rediss://…`) |
| `CORS_ORIGINS` | Vercel URL (after Phase 7) |
| `RESEND_API_KEY` | from Phase 4 |
| `RESEND_FROM_EMAIL` | `onboarding@resend.dev` |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | minified JSON from Phase 2 |
| `INBOUND_EMAIL_DOMAIN` | skip until you own a domain |
| `INBOUND_WEBHOOK_SECRET` | skip until Mailgun |

### Vercel (nexora frontend)

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://nexora-api-production-065e.up.railway.app` |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | from Phase 2 |
| `NEXT_PUBLIC_AUTH_ALLOW_EMAIL` | `false` |
| `NEXT_PUBLIC_MAX_UPLOAD_SIZE_MB` | `10` |

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Health returns `503` or `degraded` | Check `SUPABASE_URL` + `SUPABASE_SECRET_KEY` in Railway |
| `relation "users" does not exist` | Re-run `schema.sql` in Supabase SQL Editor |
| Google sign-in fails | Check `GOOGLE_CLIENT_ID` matches in Railway + Vercel; Vercel URL must be in GCP Authorized JS origins |
| CORS error in browser | Update `CORS_ORIGINS` in Railway to exact Vercel URL (no trailing slash); redeploy |
| Worker never picks up jobs | Check `REDIS_URL` is identical in both services; check worker logs for `redis connection successful` |
| Storage 404 after run | Confirm `DOCUMENT_STORAGE=auto`, buckets exist in Supabase, `013_storage_private.sql` was run |
| Buckets show `Public: ON` | Re-run `013_storage_private.sql`; or toggle Public OFF in Supabase Storage settings |
| Sheets push fails | Confirm SA `client_email` from `/api/integrations` has **Editor** access on the spreadsheet |
