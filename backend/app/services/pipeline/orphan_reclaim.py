"""
Reclaim orphaned pipeline runs left in status=running after process death.

Without Redis: BackgroundTasks / in-process tasks die with the API — reclaim all
running on startup.

With Redis + Arq workers: API restart must not kill jobs still running on workers;
only reclaim *stale* runs (see ORPHAN_RUN_STALE_MINUTES).

See docs/SCALING-AND-JOBS.md.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.config import settings
from app.models.domain.run import RunResult, StepRunRecord
from app.persistence import get_repository, save_run

logger = logging.getLogger("runner")

_STARTUP_REASON = (
    "Interrupted by server restart. Please run extraction again — "
    "pages for this attempt were refunded."
)
_STALE_REASON = (
    "This run was still in progress longer than expected and was marked failed. "
    "Please try again — pages for this attempt were refunded."
)


def _parse_created_at(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _is_stale(run: RunResult, *, max_age_minutes: int, now: Optional[datetime] = None) -> bool:
    created = _parse_created_at(run.created_at)
    if created is None:
        # No timestamp — treat as reclaimable so orphans without created_at
        # cannot stick forever (conservative for launch).
        return True
    current = now or datetime.now(timezone.utc)
    return created <= current - timedelta(minutes=max_age_minutes)


def _fail_open_steps(steps: list[StepRunRecord], reason: str) -> list[StepRunRecord]:
    updated: list[StepRunRecord] = []
    for step in steps:
        if step.status in {"queued", "running"}:
            updated.append(
                replace(
                    step,
                    status="failed",
                    error_message=reason,
                )
            )
        else:
            updated.append(step)
    return updated


async def fail_orphan_run(run: RunResult, reason: str) -> RunResult:
    """Mark a running run failed, persist, and refund usage."""
    if run.status != "running":
        return run

    failed = replace(
        run,
        status="failed",
        error_message=reason,
        steps=_fail_open_steps(list(run.steps), reason),
    )
    save_run(failed)
    logger.warning("Orphan run reclaimed run_id=%s reason=%s", run.run_id, reason)

    try:
        from app.services.usage.metering import refund_usage_for_run

        await refund_usage_for_run(run.run_id, reason="orphan_reclaim")
    except Exception:
        logger.warning(
            "Usage refund failed during orphan reclaim run=%s",
            run.run_id,
            exc_info=True,
        )

    return failed


async def reclaim_all_running(
    *,
    reason: str = _STARTUP_REASON,
) -> int:
    """Fail every run currently status=running. Returns count reclaimed."""
    repo = get_repository()
    list_fn = getattr(repo, "list_runs_by_status", None)
    if not callable(list_fn):
        logger.warning("Repository lacks list_runs_by_status — skip reclaim_all")
        return 0

    running = list_fn("running")
    count = 0
    for run in running:
        await fail_orphan_run(run, reason)
        count += 1
    if count:
        logger.info("Reclaimed %d running orphan run(s) on startup", count)
    return count


async def reclaim_stale_running(
    *,
    max_age_minutes: Optional[int] = None,
    reason: str = _STALE_REASON,
) -> int:
    """Fail running runs older than max_age_minutes. Returns count reclaimed."""
    age = (
        max_age_minutes
        if max_age_minutes is not None
        else settings.orphan_run_stale_minutes
    )
    repo = get_repository()
    list_fn = getattr(repo, "list_runs_by_status", None)
    if not callable(list_fn):
        return 0

    now = datetime.now(timezone.utc)
    count = 0
    for run in list_fn("running"):
        if _is_stale(run, max_age_minutes=age, now=now):
            await fail_orphan_run(run, reason)
            count += 1
    return count


async def maybe_reclaim_run(run: RunResult) -> RunResult:
    """If run is running and stale, fail+refund and return updated run."""
    if run.status != "running":
        return run
    if not _is_stale(run, max_age_minutes=settings.orphan_run_stale_minutes):
        return run
    return await fail_orphan_run(run, _STALE_REASON)
