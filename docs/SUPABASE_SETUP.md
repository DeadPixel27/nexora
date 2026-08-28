# Supabase setup guide

Follow these steps to persist users, workflows, and runs in Postgres (survives server restarts).

## 1. Create a project

1. Go to [https://supabase.com](https://supabase.com) and sign in
2. **New project** → pick org, name (e.g. `nexora`), database password, region
3. Wait ~2 minutes for provisioning

## 2. Run the schema

Keep numbered files under [`backend/supabase/migrations/`](../backend/supabase/migrations/) (`001`–`017`). Do **not** squash them into one dump — they are the history for existing databases.

**New project (recommended):** three SQL Editor runs, not sixteen:

1. [`backend/supabase/schema.sql`](../backend/supabase/schema.sql) — current tables through `017_enable_rls` (includes RLS)
2. [`backend/supabase/seed_templates.sql`](../backend/supabase/seed_templates.sql) — pipeline template catalog
3. [`backend/supabase/migrations/013_storage_private.sql`](../backend/supabase/migrations/013_storage_private.sql) — private `documents` + `user-templates` buckets and client deny policy

You should see `Success` after each.

Tables created:

| Table | Purpose |
|-------|---------|
| `users` | App users |
| `workflows` | Saved workflow templates |
| `workflow_steps` | Steps per workflow |
| `workflow_runs` | Execution history |
| `workflow_step_runs` | Per-step run output |
| `pipeline_templates` | Landing-page task presets (editable in Table Editor) |
| `uploads` | Upload ownership registry (`user_id` binding) |

### Existing projects — run migrations

If the project already had an older schema, apply numbered files under [`backend/supabase/migrations/`](../backend/supabase/migrations/) in order through `017_enable_rls.sql` instead of re-running the full `schema.sql`.

> Older note: [`002_add_users_and_run_document_ids.sql`](../backend/supabase/migrations/002_add_users_and_run_document_ids.sql) was the first incremental migration for very early schemas.

## 3. Get API keys

1. Dashboard → **Project Settings** → **API**
2. Copy:
   - **Project URL** → `SUPABASE_URL`
   - **Secret key** (`sb_secret_...`) → `SUPABASE_SECRET_KEY`

Use the **secret** key on the backend only — never expose it in the frontend (and never as `NEXT_PUBLIC_*`).

**Production (Railway):** set `APP_ENV=production` plus real `SUPABASE_URL` / `SUPABASE_SECRET_KEY`. If Supabase is missing, the API refuses to start and `/api/health` returns **503** (in-memory fallback is local/dev only).

## 4. Update `.env`

```bash
cd backend
cp .env.example .env   # if you haven't already
```

Add to `backend/.env`:

```env
SUPABASE_URL=https://xxxxxxxx.supabase.co
SUPABASE_SECRET_KEY=sb_secret_xxxxxxxx
```

Keep your existing `GROQ_API_KEY` line.

## 5. Enable document + template storage (Supabase Storage)

Uploaded PDFs/images and user-template version payloads are stored in **private** buckets. The API serves documents after auth/ownership checks; the frontend must never talk to Storage with the anon key.

### Create the buckets

1. Dashboard → **Storage** → **New bucket**
2. Name: `documents` (must match `SUPABASE_DOCUMENTS_BUCKET` in `.env`)
3. **Public bucket**: **OFF**
4. Click **Create bucket**
5. Repeat for `user-templates` (must match `SUPABASE_USER_TEMPLATES_BUCKET`) — **Public**: **OFF**

Or run [`backend/supabase/migrations/013_storage_private.sql`](../backend/supabase/migrations/013_storage_private.sql) in the SQL Editor — it upserts both buckets as private and adds a restrictive Storage policy so `anon` / `authenticated` cannot read or write those objects (service role still works).

### Defense in depth

API ownership checks (#6) do **not** protect a **public** bucket. If `public=true` or permissive Storage policies allow listing/download, anyone who can guess `{upload_id}/...` can leak files without your JWT. Keep buckets private and run `013_storage_private.sql` in production.

### Configure `.env`

```env
DOCUMENT_STORAGE=auto
SUPABASE_DOCUMENTS_BUCKET=documents
SUPABASE_USER_TEMPLATES_BUCKET=user-templates
```

| `DOCUMENT_STORAGE` | Behavior |
|--------------------|----------|
| `auto` (default) | Supabase Storage when `SUPABASE_*` is set, else `backend/uploads/` |
| `local` | Always local disk |
| `supabase` | Always Supabase Storage |

Restart the server after changing env vars.

## 6. Verify

```bash
cd backend
source .venv/bin/activate
python scripts/verify_supabase.py
```

Expected:

```
OK: Connected to Supabase
  OK  table: users
  OK  table: workflows
  ...
  OK  bucket: documents (private)
  OK  bucket: user-templates (private)
All checks passed.
```

Restart the server:

```bash
uvicorn app.main:app --reload
```

Check health:

```bash
curl http://localhost:8000/api/health
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

## 7. Confirm persistence

1. Create a user via API
2. **Restart** uvicorn
3. `GET /api/users` — user should still exist

Without Supabase, data is in-memory and lost on restart.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `not_configured` in health | Add both env vars to `.env`, restart server |
| `relation "users" does not exist` | Run `schema.sql` in SQL Editor |
| `Invalid API key` | Use **secret** key, not publishable |
| `degraded` status | Run `python scripts/verify_supabase.py` for details |
| RLS disabled warning in Dashboard | Run [`017_enable_rls.sql`](../backend/supabase/migrations/017_enable_rls.sql) in SQL Editor (no policies needed — service role bypasses RLS) |
| RLS errors on backend | Backend uses service role key; Storage/Postgres RLS is bypassed for that key |
| `must be owner of table objects` | Do not `ALTER TABLE storage.objects` (RLS is already on). Re-run the current `013_storage_private.sql`. If `CREATE POLICY` still fails, run only the `storage.buckets` upsert block (sets `public=false`) and manage policies in Dashboard → Storage → Policies (empty allow-list = deny for anon) |
| `Bucket not found` | Create `documents` / `user-templates` or run `013_storage_private.sql` |
| Bucket marked public in verify | Turn Public OFF in Storage settings and re-run `013_storage_private.sql` |
| Files 404 after deploy | Set `DOCUMENT_STORAGE=auto` and configure Supabase Storage |

## Optional: view data

Supabase Dashboard → **Table Editor** → browse `users`, `workflows`, `workflow_runs`, `uploads`.
