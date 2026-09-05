# Nexora — Interview Signals (Phase 1)

**Branch:** `feature/interview-signals`  
**Goal:** Ship production-shaped evals, step tracing, and RAG so Applied AI interviews can point at live Nexora behavior — not slides.

Job search stays paused until these ship. Do not edit `cv/` or `docs/JOB-SEARCH-PLAN.md` in this work.

---

## Scope (this PR)

| # | Signal | In scope | Out of scope |
|---|--------|----------|--------------|
| 1 | **Eval harness** | Golden-set registry from fixtures, per-field score, Postgres `eval_runs` / `eval_run_items`, admin run + list APIs, regression gate | Queued 50-doc sweeps, public UI dashboard, CI gate on every PR |
| 2 | **Observability** | OpenTelemetry spans per DAG step (metadata only) | Langfuse UI, payload/PII logging, full distributed tracing mesh |
| 3 | **RAG** | Chunk + embed cached run text into PGVector; chat Q&A over that run | Hybrid search, re-rankers, multi-run corpus, agent tools |

Scaling / deferral notes live in [SCALING-AND-JOBS.md](./SCALING-AND-JOBS.md).

---

## Acceptance criteria

### 1. Eval harness

- [x] Golden set lists fixture paths + expected fields under `backend/app/services/evals/golden_set.py` (subset with ground truth; reuse matchers from accuracy pack).
- [x] `POST /api/admin/evals/run` (admin key) extracts each doc, scores fields, persists an `eval_runs` row + items.
- [x] `GET /api/admin/evals` and `GET /api/admin/evals/{id}` return summaries (field accuracy %, per-field miss counts) — no document text in responses.
- [x] Optional `min_field_accuracy` fails the HTTP response when below threshold (regression gate).
- [x] Unit tests cover scoring + store memory fallback without calling OpenAI.
- [x] Existing CLI packs can import shared scoring helpers (no duplicated matchers).

### 2. Observability

- [x] When `OTEL_ENABLED=true`, each runner step creates a span named `agent.{agent_type}` with attributes: `run_id`, `agent_type`, `step_order`, `status`, duration — **never** OCR text, prompts, or field values ([NEXT-STEPS privacy](./NEXT-STEPS.md)).
- [x] When disabled, zero behavior change (no required exporter).
- [x] Optional OTLP endpoint via `OTEL_EXPORTER_OTLP_ENDPOINT`.

### 3. RAG (minimal)

- [x] After a successful run with cached document text, chunks are embedded and stored in `document_chunks` (pgvector) keyed by `run_id` + `user_id`.
- [x] `POST /api/runs/{run_id}/chat` answers a question using top-k similar chunks + LLM; ownership enforced like other run routes.
- [x] Embeddings count toward OpenAI budget checks (same fail-closed path as extraction).
- [x] Embedding / chat skipped gracefully when pgvector migration not applied or feature flag off.

---

## Non-goals

- Model routing / cost-per-run UI (follow-on once eval baseline exists).
- MCP server.
- Changing launch metering caps or page limits.

---

## Ops checklist (deploy)

1. Apply `018_eval_runs.sql` and `019_document_chunks.sql` in Supabase SQL Editor.
2. Set `OTEL_ENABLED` / OTLP endpoint only if you have a collector (local Jaeger or cloud).
3. Set `RAG_ENABLED=true` after pgvector migration succeeds.
4. Smoke: admin eval on `invoice` golden subset; one completed run → Ask docs chat.
