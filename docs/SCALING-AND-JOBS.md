# Nexora — Scaling, Jobs & Future Ops

**Updated:** 2026-08-24  
**Audience:** ops + architecture for API replicas, workers, and extraction scale.

This doc captures decisions so we do **not** reopen them casually during ship week. For near-term product tasks see [NEXT-STEPS.md](./NEXT-STEPS.md).

**Rule:** Whenever we defer a scaling, reliability, cost, extraction-architecture, or ops change, **add it here in the same PR/change** (see `.cursor/rules/scaling-and-jobs.mdc`). Do not leave “we’ll do it later” only in chat.

---

## Mental model (keep this)

When a user starts an extraction:

1. API writes a run row with `status=running` (sticky note on the wall).
2. API calls `schedule_run(run_id)`:
   - **With `REDIS_URL`:** enqueues `run_id` on Redis (Arq).
   - **Without Redis (local):** `asyncio.create_task(execute_run)` in-process.
3. **Worker process** (`arq app.jobs.worker.WorkerSettings`) pulls the job and runs `execute_run`.

If the **API** process dies (redeploy), workers keep going. If a run is stuck `running` longer than `ORPHAN_RUN_STALE_MINUTES`, **stale reclaim** fails it + refunds pages.

---

## Current posture (shipped)

| Choice | Why |
|--------|-----|
| **Redis + Arq job queue** | Restart-safe extractions; CV/production shape. **Not Kafka** — see below |
| **1 API + 1 worker** on Railway | Cheap CV default (~$5–10/mo); scale workers for Reddit |
| **Upstash Redis** (free tier) | Queue only — stores `run_id`. Worker polls every **7s** (`poll_delay`) to stay under 500K cmds/month |
| **No Redis application cache** | Metering/rate limits stay in-process until multi-replica API |
| **Orphan reclaim** | Queue on → `reclaim_stale_running` on API startup; queue off → `reclaim_all_running` |
| **No extraction parallelism yet** | Batch LLM call is simpler/cheaper |
| **Max 10 pages per file** | Single GPT-4o call; raise when chunked extract ships |
| **OpenAI spend brakes** | Global daily pages + `OPENAI_DAILY_BUDGET_USD` |

### Code map

| Piece | Path |
|-------|------|
| Enqueue | `backend/app/jobs/enqueue.py` → `schedule_run` |
| Worker | `backend/app/jobs/worker.py` → `WorkerSettings` |
| Routes | `runs.py`, `workflows.py`, `inbound.py` call `await schedule_run(...)` |
| Config | `REDIS_URL` / `settings.job_queue_enabled` |

### Scale workers for traffic

Railway worker service → **Replicas = 3** for a Reddit spike, then back to **1**. No code change. Three replicas = up to three concurrent extractions.

```
User → API
         ├─► Postgres (run status)
         └─► Redis queue (run_id)
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
      Worker 1              Worker N
         │                     │
         └──────► GPT / OCR ───┘
                      │
                      ▼
                   Postgres
```

**Do not** turn on multi-replica **API** autoscaling until OpenAI daily spend / rate limits are shared (Redis or DB) — today those counters are in-process.

---

## Why not Kafka for the job queue

Same *idea* (API hands work to another process), different *tool*. Redis + Arq is a **task queue** (consume a `run_id` once). Kafka is a **durable event log** (many consumers, replay history). Routes already only call `schedule_run(run_id)` — they do not know about Redis.

| | Redis + Arq (shipped) | Kafka now |
|---|---|---|
| **Current behavior** | Enqueue `run_id`; worker runs `execute_run`. Upstash stores the job, not documents. | Topics + consumer groups + offsets; still call `execute_run` after consume. |
| **Cost (this stage)** | **$0/mo** Upstash free (500K commands). Idle poll is the bulk of usage, not jobs. `poll_delay=7` + `health_check_interval=60` so one 24/7 worker stays under free. Default 0.5s poll would blow 500K in ~2 days. | Managed Kafka typically **~$50–300/mo** at tiny volume (Confluent Basic / Aiven / MSK). Dedicated starts higher. Upstash Kafka **discontinued** (Mar 2025) — no same-vendor swap. |

- **Why deferred:** Scaling is worker replicas, then shared OpenAI metering, then chunked extract — not “Redis → Kafka.” Kafka would not avoid recoding: a transport swap is `enqueue.py` + `worker.py` (~80 lines, 1–2 days), not the app. Extra ops (partitions, offsets, monitoring) with no product win.
- **Trigger to build:** Independent consumers of the *same* stream (billing + webhooks + search + analytics), **months of event replay** after a bug, or millions of msgs/day with long retention.
- **Preferred approach:** Keep Redis + Arq. Keep **`schedule_run()` as the only enqueue API** so a future swap stays isolated. If Kafka is needed later, add it as an **event bus** *alongside* the job queue — do not replace Arq with Kafka for “run this extraction once.”

---

## Later: extraction architecture

(unchanged intent — chunked extract, parallel OCR/LLM when page limits rise)

See sections below for page limits and cost ops.

---

## Later: cost & metering ops

| Item | Notes |
|------|--------|
| Persist OpenAI spend beyond one API process | Today `openai_cost` day totals are **in-process**; multi-replica API needs Redis/DB |
| Admin `/api/admin/openai-spend` | Snapshot only for the replica that handled calls |
| Route simple templates to `gpt-4o-mini` | Big $/page win once quality is validated |
| Upload TTL cleanup sweep | Deferred — [NEXT-STEPS.md](./NEXT-STEPS.md) |
| Redis as cache (rate limits, inbound replay tokens) | Only when multi-replica API |

---

## Triggers: when to scale further

- Scale **workers** 1 → 3 when concurrent extractions queue up (Reddit).
- Add **Redis cache** for OpenAI budget / rate limits when running **>1 API** replica.
- Raise per-file page limits / chunked extract when users hit the 10-page reject often.
- Consider Kafka (or similar) only as an **event bus** when multiple systems must independently consume/replay run events — not as a replacement for the Arq job queue.
