# Nexora — Next Steps

**Updated:** 2026-08-16  
**Branch:** `feature/hard-usage-caps` → merge to `develop`

Launch product (V2/V3 + auth/metering) is built. Remaining work below.

---

## This week (ship)

| # | Task | Est. | Notes |
|---|------|------|-------|
| 1 | ~~**Hard usage caps per feature**~~ | done | Pages/extract, refine (cap + out-of-scope refuse), email/Sheets HTTP + agents; clear 429 modal; account shows outbound bars. |
| 2 | **Deploy** | ~4h | Supabase + Upstash Redis + Railway API + Worker + Vercel + smoke. See [DEPLOYMENT.md](./DEPLOYMENT.md) + [SCALING-AND-JOBS.md](./SCALING-AND-JOBS.md). |
| 3 | **Real-doc testing** | ~3h | 3–5 docs each: invoice, receipt, resume. Score accuracy before extra hardening. |
| 4 | **Launch kit** | ~2h | 60s Loom + Reddit / IH / HN drafts + README screenshots + live URL. |

---

## Deferred (post-launch)

- SEO template pages (`/templates/[slug]`)
- Inbound email IMAP poll (unread + attachments → batched run)
- Job queue / Redis / multi-replica — **queue shipped** (Arq + Upstash); scale worker replicas for Reddit. Multi-replica API still deferred — [SCALING-AND-JOBS.md](./SCALING-AND-JOBS.md)
- GitHub Actions CI (`pytest` + `npm run build`)
- Frontend tests (Vitest)
- Supabase Auth (password / magic link) — JWT+Google is enough for launch
- **`transform.calculator`** — derived fields (`tax_pct = tax / subtotal`) without LLM math; after normalize/rules. Also [AGENTS.md](./AGENTS.md) Tier 2.
- **Visual rule editor** — point-and-click `field + operator + value + action` on workflow settings; same JSON as chat/templates. Discoverability polish once chat authoring is proven.
- Per-transaction / nested array rules (`transactions[]`) — [SCALING-AND-JOBS.md](./SCALING-AND-JOBS.md)
### Privacy, logging, retention (decided)

- **Stdout = metadata only.** Do not log OCR/extract strings, field values, prompt tails, LLM JSON, or recipient emails in production. Keep `run_id` / `user_id` / timings / `prompt_fp`. Verbose refine dumps need `LOG_PAYLOADS=true` (local only).
- **Per-user “who did what”.** Stdout has `rid=` / `uid=`. Postgres: `audit_events` (auth, upload, run, refine, workflow, delivery, inbound, waitlist) plus `usage_events` / `analytics_events`. Apply migration `016_audit_events.sql` on deploy.
- **Keep uploaded files and extraction results for MVP.** History and refine need stored OCR text (`cached_documents`). Do **not** ship or advertise 24-hour auto-delete. Privacy copy should say we store docs so you can reopen runs; auto-delete is post-launch after we hear from users.
- **Upload TTL sweep** — deferred as its own **RetentionCleanupService** (not mixed into owner refine). See below and [SCALING-AND-JOBS.md](./SCALING-AND-JOBS.md).

---

## Post-launch: owner / master refine

User chat refine stays on [`RefineService`](../backend/app/services/pipeline/refine_service.py): child runs + that user’s versions. Saving a workflow keeps **their** generalized prompt. Catalog Invoice/resume is unchanged until **you** apply.

Grow [`TemplateMasterRefineService`](../backend/app/services/templates/template_master_refine_service.py) into **`OwnerRefineService`** (admin APIs already under `/api/admin/templates/`). Human-in-the-loop: harvest → synthesize → optional shadow-test → you edit → apply. Do not auto-publish user wording to master.

| Step | Behavior |
|------|----------|
| **harvest** | Always: `refinement_events` + version blobs (`prompt_before`, `prompt_after`, **`prompt_generalized`**, field names, user message). Optionally attach truncated OCR/text or sample rows **if the run still has them**. Missing PDFs is normal — harvest must not fail. |
| **synthesize** | Curator LLM. Docs optional; improve master from prompt/field diffs alone when there is no file. |
| **shadow_test** | Only if ≥1 sample still has cached text or a file. Re-extract current master vs proposed. Skip if no PDFs. |
| **apply** | Write `extraction_instructions` / fields / rules to **`pipeline_templates`**. Make that table the runtime source of truth; seed Python **insert-if-missing** only (today boot overwrites apply). |

Do **not** copy PDFs into an admin bucket. Read in place or skip.

**Not in this service:** TTL, auto-publish, writing Python template files, pushing master into existing user workflows.

### RetentionCleanupService (separate, later)

Owns **what to delete vs keep**. Do not implement inside OwnerRefineService.

- **Delete (when you ship it):** upload objects, `cached_documents`, `result` cell values (otherwise “file TTL” still leaves invoices in Postgres).
- **Keep:** `refinement_events`, `user_template_versions` + prompt blobs, `pipeline_templates`, workflow metadata — so owner refine still works prompt-only after wipe.

Until this exists, keep files and results for MVP (history + user refine). No 24h/7d auto-delete in product copy.

---

## Later product ideas

| Idea | Notes |
|------|-------|
| Live PDF preview + field highlights | Split view; highlight source spans |
| Auto-correct / learning from edits | Store corrections → few-shot on next similar docs |
| Editable cells + run diff / validation suggestions | Results UX polish |
| Watch folder / inbox automation | Drive/Gmail → saved workflow → Sheets/email |
| New agents | Summarizer, classifier, table extract, calculator — [AGENTS.md](./AGENTS.md) |
| Visual rule editor | Workflow settings UI for flag/filter/set rules (see Deferred above) |
| Stripe, dynamic schema via chat | Monetization / power features |

**Research locks (do not reopen for launch):** GPT-4o extract, RapidOCR, per-page metering, no blind prompt hardening, no Claude routing yet.

---

## Immediate next action

**Deploy** (#2), then real-doc testing + launch kit.
