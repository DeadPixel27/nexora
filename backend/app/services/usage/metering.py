"""
Usage metering — track and enforce page extraction limits.

Free tier: 50 pages/month per user.
Global daily cap: 100 pages/day across all users (budget protection).
OpenAI USD budget: estimated spend gate (see openai_cost / OPENAI_DAILY_BUDGET_USD).
Refine limit: 10 refinements per run.
Outbound: 20 emails / 20 Sheets pushes per user per month (separate from pages).
RAG chat: 100k OpenAI tokens/month (embed + answer; separate from pages).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.config import settings

logger = logging.getLogger("usage")

# In-memory fallback when Supabase is not configured (dev / tests)
_memory_usage_events: list[dict[str, Any]] = []

EMAIL_EVENT_TYPE = "email_sent"
SHEETS_EVENT_TYPE = "sheets_push"
RAG_CHAT_EVENT_TYPE = "rag_chat"
OUTBOUND_EVENT_TYPES = frozenset(
    {EMAIL_EVENT_TYPE, SHEETS_EVENT_TYPE, RAG_CHAT_EVENT_TYPE}
)

# In-process locks (single-replica launch). Multi-replica needs DB locks later.
_global_usage_lock = asyncio.Lock()
_user_usage_locks: dict[str, asyncio.Lock] = {}
_user_locks_guard = asyncio.Lock()


async def _user_lock(user_id: str) -> asyncio.Lock:
    async with _user_locks_guard:
        lock = _user_usage_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_usage_locks[user_id] = lock
        return lock


def _is_page_event(event_type: Any) -> bool:
    """Outbound units reuse usage_events.pages but must not hit the page pool."""
    return str(event_type or "") not in OUTBOUND_EVENT_TYPES


class UsageLimitError(Exception):
    """Raised when a user exceeds their page limit."""


class GlobalCapError(Exception):
    """Raised when the global daily page cap is hit."""


class RefineLimitError(Exception):
    """Raised when a run exceeds its refine limit."""


def reset_memory_usage() -> None:
    """Clear in-memory usage events (tests only)."""
    _memory_usage_events.clear()
    _user_usage_locks.clear()


def _supabase_client():
    from app.persistence.supabase_repository import (
        get_supabase_client,
        is_supabase_configured,
    )

    if not is_supabase_configured():
        return None
    try:
        return get_supabase_client()
    except Exception as e:
        logger.warning("Supabase client unavailable for usage: %s", e)
        return None


def _month_start(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _day_start(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    return current.replace(hour=0, minute=0, second=0, microsecond=0)


def _parse_created_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def get_user_usage_this_month(user_id: str) -> int:
    """Count extraction pages used by this user in the current calendar month.

    Excludes outbound units (email_sent / sheets_push) so they do not share
    the free page pool.
    """
    month_start = _month_start()
    client = _supabase_client()
    if client is not None:
        result = (
            client.table("usage_events")
            .select("pages,event_type")
            .eq("user_id", user_id)
            .gte("created_at", month_start.isoformat())
            .execute()
        )
        return sum(
            int(row.get("pages") or 0)
            for row in (result.data or [])
            if _is_page_event(row.get("event_type"))
        )

    total = 0
    for event in _memory_usage_events:
        if event.get("user_id") != user_id:
            continue
        if not _is_page_event(event.get("event_type")):
            continue
        if _parse_created_at(event["created_at"]) >= month_start:
            total += int(event.get("pages") or 0)
    return total


async def get_global_usage_today() -> int:
    """Count extraction pages today across all users (excludes outbound)."""
    day_start = _day_start()
    client = _supabase_client()
    if client is not None:
        result = (
            client.table("usage_events")
            .select("pages,event_type")
            .gte("created_at", day_start.isoformat())
            .execute()
        )
        return sum(
            int(row.get("pages") or 0)
            for row in (result.data or [])
            if _is_page_event(row.get("event_type"))
        )

    total = 0
    for event in _memory_usage_events:
        if not _is_page_event(event.get("event_type")):
            continue
        if _parse_created_at(event["created_at"]) >= day_start:
            total += int(event.get("pages") or 0)
    return total


async def get_user_outbound_usage_this_month(user_id: str, event_type: str) -> int:
    """Count outbound units (email/sheets) for this user this month."""
    month_start = _month_start()
    client = _supabase_client()
    if client is not None:
        result = (
            client.table("usage_events")
            .select("pages")
            .eq("user_id", user_id)
            .eq("event_type", event_type)
            .gte("created_at", month_start.isoformat())
            .execute()
        )
        return sum(int(row.get("pages") or 0) for row in (result.data or []))

    total = 0
    for event in _memory_usage_events:
        if event.get("user_id") != user_id:
            continue
        if event.get("event_type") != event_type:
            continue
        if _parse_created_at(event["created_at"]) >= month_start:
            total += int(event.get("pages") or 0)
    return total


async def check_outbound_allowed(
    user_id: str,
    event_type: str,
    limit: int,
    *,
    units: int = 1,
) -> None:
    """Raise UsageLimitError if outbound monthly cap would be exceeded."""
    used = await get_user_outbound_usage_this_month(user_id, event_type)
    if used + units > limit:
        if event_type == EMAIL_EVENT_TYPE:
            label = "emails"
        elif event_type == SHEETS_EVENT_TYPE:
            label = "Sheets pushes"
        elif event_type == RAG_CHAT_EVENT_TYPE:
            label = "Ask-docs tokens"
        else:
            label = "units"
        logger.info(
            "User %s hit outbound limit type=%s: %d + %d > %d",
            user_id,
            event_type,
            used,
            units,
            limit,
        )
        raise UsageLimitError(
            f"You've used {used} of your {limit} free {label} this month. "
            f"Join the Pro waitlist for higher limits."
        )


async def get_run_refine_count(run_id: str, repo=None) -> int:
    """Count how many refinements have been done on this run (child runs)."""
    if repo is not None:
        count_fn = getattr(repo, "count_child_runs", None)
        if callable(count_fn):
            return int(count_fn(run_id))

    from app.persistence import get_repository

    active = get_repository()
    count_fn = getattr(active, "count_child_runs", None)
    if callable(count_fn):
        return int(count_fn(run_id))

    # Last resort: supabase table query
    client = _supabase_client()
    if client is not None:
        result = (
            client.table("workflow_runs")
            .select("id", count="exact")
            .eq("parent_run_id", run_id)
            .execute()
        )
        if getattr(result, "count", None) is not None:
            return int(result.count)
        return len(result.data or [])

    runs = getattr(active, "_runs", None)
    if isinstance(runs, dict):
        return sum(1 for run in runs.values() if getattr(run, "parent_run_id", None) == run_id)
    return 0


async def check_refine_allowed(run_id: str, repo=None) -> None:
    """Check if this run can be refined further."""
    count = await get_run_refine_count(run_id, repo=repo)
    if count >= settings.max_refines_per_run:
        raise RefineLimitError(
            f"This run has reached the maximum of {settings.max_refines_per_run} "
            f"refinements. Start a new extraction to continue."
        )


async def check_usage_allowed(user_id: str, page_count: int = 1) -> None:
    """
    Check all usage limits before allowing an extraction.
    Raises UsageLimitError or GlobalCapError if limits exceeded.
    """
    daily_total = await get_global_usage_today()
    if daily_total + page_count > settings.global_daily_page_limit:
        logger.warning(
            "Global daily cap hit: %d + %d > %d",
            daily_total,
            page_count,
            settings.global_daily_page_limit,
        )
        raise GlobalCapError(
            "Service is temporarily at capacity. Please try again later."
        )

    user_total = await get_user_usage_this_month(user_id)
    if user_total + page_count > settings.free_page_limit_monthly:
        logger.info(
            "User %s hit monthly limit: %d + %d > %d",
            user_id,
            user_total,
            page_count,
            settings.free_page_limit_monthly,
        )
        raise UsageLimitError(
            f"You've used {user_total} of your {settings.free_page_limit_monthly} "
            f"free pages this month. Join the Pro waitlist for unlimited access."
        )


async def record_usage(
    user_id: str,
    pages: int,
    *,
    template_id: str | None = None,
    run_id: str | None = None,
    event_type: str = "extraction",
) -> None:
    """Record a usage event."""
    client = _supabase_client()
    row = {
        "user_id": user_id,
        "pages": pages,
        "template_id": template_id,
        "run_id": run_id,
        "event_type": event_type,
    }
    if client is not None:
        client.table("usage_events").insert(row).execute()
    else:
        _memory_usage_events.append(
            {
                **row,
                "id": str(uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    logger.info(
        "Usage recorded: user=%s pages=%d type=%s run=%s",
        user_id,
        pages,
        event_type,
        run_id,
    )


async def reserve_page_usage(
    user_id: str,
    pages: int,
    *,
    template_id: str | None = None,
    run_id: str | None = None,
    event_type: str = "extraction",
) -> None:
    """
    Atomically (in-process) check page caps and record usage.

    Holds per-user + global locks so concurrent requests on one replica
    cannot both pass check_usage_allowed and overshoot.
    """
    user_lock = await _user_lock(user_id)
    async with _global_usage_lock:
        async with user_lock:
            await check_usage_allowed(user_id, pages)
            await record_usage(
                user_id,
                pages,
                template_id=template_id,
                run_id=run_id,
                event_type=event_type,
            )


async def reserve_outbound_usage(
    user_id: str,
    event_type: str,
    limit: int,
    *,
    run_id: str | None = None,
    units: int = 1,
) -> None:
    """Check outbound cap and record units under a per-user lock."""
    user_lock = await _user_lock(user_id)
    async with user_lock:
        await check_outbound_allowed(user_id, event_type, limit, units=units)
        await record_usage(
            user_id,
            units,
            run_id=run_id,
            event_type=event_type,
        )


async def refund_outbound_usage(
    user_id: str,
    event_type: str,
    *,
    run_id: str | None = None,
    units: int = 1,
    reason: str = "delivery_failed",
) -> None:
    """Compensating negative outbound unit after a failed provider call.

    Uses the same event_type with negative pages so monthly sums stay correct.
    """
    await record_usage(
        user_id,
        -abs(units),
        run_id=run_id,
        event_type=event_type,
    )
    logger.info(
        "Outbound usage refunded: user=%s type=%s units=%d reason=%s",
        user_id,
        event_type,
        units,
        reason,
    )


async def refund_usage_for_run(run_id: str, *, reason: str = "run_failed") -> None:
    """
    Credit back pages charged for a failed run.

    Inserts a compensating usage_events row with negative pages so monthly/global
    sums stay accurate without deleting the original charge.
    """
    charged = await _pages_charged_for_run(run_id)
    if charged <= 0:
        return

    user_id = await get_user_id_for_run(run_id)
    if not user_id:
        # Prefer run.user_id when usage_events lookup misses
        from app.persistence import get_run

        run = get_run(run_id)
        user_id = getattr(run, "user_id", None) if run else None
    if not user_id:
        logger.warning("Cannot refund usage for run=%s — no user linkage", run_id)
        return

    await record_usage(
        user_id,
        -charged,
        run_id=run_id,
        event_type=f"refund:{reason}",
    )
    logger.info("Usage refunded: run=%s pages=%d reason=%s", run_id, charged, reason)


async def _pages_charged_for_run(run_id: str) -> int:
    """Net extraction pages already attributed to this run (excludes outbound)."""
    client = _supabase_client()
    if client is not None:
        try:
            result = (
                client.table("usage_events")
                .select("pages,event_type")
                .eq("run_id", run_id)
                .execute()
            )
            return sum(
                int(row.get("pages") or 0)
                for row in (result.data or [])
                if _is_page_event(row.get("event_type"))
            )
        except Exception as e:
            logger.debug("pages_charged lookup failed for run=%s: %s", run_id, e)
            return 0

    return sum(
        int(event.get("pages") or 0)
        for event in _memory_usage_events
        if event.get("run_id") == run_id and _is_page_event(event.get("event_type"))
    )


async def get_usage_summary(user_id: str) -> dict:
    """Get usage summary for the API response."""
    now = datetime.now(timezone.utc)
    month_start = _month_start(now)

    if now.month == 12:
        next_month = month_start.replace(year=now.year + 1, month=1)
    else:
        next_month = month_start.replace(month=now.month + 1)

    pages_used = await get_user_usage_this_month(user_id)
    emails_used = await get_user_outbound_usage_this_month(user_id, EMAIL_EVENT_TYPE)
    sheets_used = await get_user_outbound_usage_this_month(user_id, SHEETS_EVENT_TYPE)
    rag_tokens_used = await get_user_outbound_usage_this_month(
        user_id, RAG_CHAT_EVENT_TYPE
    )

    return {
        "pages_used": pages_used,
        "pages_limit": settings.free_page_limit_monthly,
        "emails_used": emails_used,
        "emails_limit": settings.free_email_limit_monthly,
        "sheets_used": sheets_used,
        "sheets_limit": settings.free_sheets_limit_monthly,
        "rag_tokens_used": rag_tokens_used,
        "rag_tokens_limit": settings.free_rag_token_limit_monthly,
        "resets_at": next_month.isoformat(),
    }


async def get_user_id_for_run(run_id: str) -> Optional[str]:
    """Look up the user who started a run (run.user_id, then usage_events)."""
    try:
        from app.persistence import get_run

        run = get_run(run_id)
        if run is not None and getattr(run, "user_id", None):
            return str(run.user_id)
    except Exception as e:
        logger.debug("run.user_id lookup failed for run=%s: %s", run_id, e)

    client = _supabase_client()
    if client is not None:
        try:
            result = (
                client.table("usage_events")
                .select("user_id")
                .eq("run_id", run_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            if rows and rows[0].get("user_id"):
                return str(rows[0]["user_id"])
        except Exception as e:
            logger.debug("usage_events lookup failed for run=%s: %s", run_id, e)

    for event in reversed(_memory_usage_events):
        if event.get("run_id") == run_id and event.get("user_id"):
            return str(event["user_id"])
    return None
