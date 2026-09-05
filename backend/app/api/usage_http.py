"""HTTP helpers for usage limits (shared by runs / workflows / extract / outbound)."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional

from fastapi import HTTPException

from app.config import settings
from app.models.domain.run import RunResult
from app.persistence import save_run
from app.services.analytics.events import log_event
from app.services.usage.metering import (
    EMAIL_EVENT_TYPE,
    RAG_CHAT_EVENT_TYPE,
    SHEETS_EVENT_TYPE,
    GlobalCapError,
    UsageLimitError,
    check_usage_allowed,
    record_usage,
    refund_outbound_usage,
    reserve_outbound_usage,
    reserve_page_usage,
)
from app.services.usage.page_count import count_upload_pages

logger = logging.getLogger("api")

_RECORD_FAIL_DETAIL = "Unable to record usage. Please try again."


def _http_for_usage_error(exc: Exception) -> HTTPException:
    if isinstance(exc, UsageLimitError):
        return HTTPException(status_code=429, detail=str(exc))
    if isinstance(exc, GlobalCapError):
        return HTTPException(status_code=503, detail=str(exc))
    logger.warning("Usage record failed: %s", exc, exc_info=True)
    return HTTPException(status_code=503, detail=_RECORD_FAIL_DETAIL)


def abandon_unmetered_run(run: RunResult, *, detail: str = _RECORD_FAIL_DETAIL) -> None:
    """Mark a started run failed so it is not left running without a charge."""
    try:
        save_run(
            replace(
                run,
                status="failed",
                error_message=detail,
            )
        )
    except Exception:
        logger.exception("Failed to abandon unmetered run=%s", run.run_id)


async def charge_run_pages(
    user_id: str,
    *,
    page_count: int,
    run_id: Optional[str] = None,
    template_id: Optional[str] = None,
    event_type: str = "extraction",
) -> None:
    """Reserve pages (check+record). Raises 429/503 — fail-closed."""
    try:
        await reserve_page_usage(
            user_id,
            page_count,
            template_id=template_id,
            run_id=run_id,
            event_type=event_type,
        )
    except Exception as e:
        raise _http_for_usage_error(e) from e

    try:
        await log_event(
            "run_started",
            user_id=user_id,
            template_id=template_id,
            run_id=run_id,
            page_count=page_count,
        )
    except Exception as e:
        logger.warning("Failed to record run_started analytics: %s", e)

    try:
        from app.services.audit.events import log_audit

        await log_audit(
            "run.started",
            actor_user_id=user_id,
            resource_type="run",
            resource_id=run_id,
            metadata={"page_count": page_count, "event_type": event_type},
        )
    except Exception as e:
        logger.warning("Failed to record run.started audit: %s", e)


async def charge_run_pages_or_abandon(
    user_id: str,
    run: RunResult,
    *,
    page_count: int,
    template_id: Optional[str] = None,
    event_type: str = "extraction",
) -> None:
    """Charge after start_run; abandon run and raise if metering fails."""
    try:
        await charge_run_pages(
            user_id,
            page_count=page_count,
            run_id=run.run_id,
            template_id=template_id,
            event_type=event_type,
        )
    except HTTPException as e:
        abandon_unmetered_run(run, detail=str(e.detail))
        raise


async def enforce_upload_usage(user_id: str, upload_id: str) -> int:
    """Count pages in an upload (no charge). Callers charge after start_run."""
    page_count = await count_upload_pages(upload_id)
    try:
        await check_usage_allowed(user_id, page_count)
    except UsageLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except GlobalCapError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return page_count


async def charge_extract_pages(user_id: str, page_count: int) -> None:
    """Reserve pages for extract API before LLM work."""
    try:
        await reserve_page_usage(
            user_id,
            page_count,
            event_type="extract_api",
        )
    except Exception as e:
        raise _http_for_usage_error(e) from e

    try:
        await log_event(
            "extract_completed",
            user_id=user_id,
            page_count=page_count,
        )
    except Exception as e:
        logger.warning("Failed to record extract analytics: %s", e)

    try:
        from app.services.audit.events import log_audit

        await log_audit(
            "extract.completed",
            actor_user_id=user_id,
            resource_type="extract",
            metadata={"page_count": page_count},
        )
    except Exception as e:
        logger.warning("Failed to record extract audit: %s", e)


async def refund_extract_pages(user_id: str, page_count: int) -> None:
    """Refund extract_api charge after LLM failure."""
    try:
        await record_usage(
            user_id,
            -page_count,
            event_type="refund:extract_api",
        )
    except Exception:
        logger.warning(
            "Failed to refund extract usage user=%s pages=%s",
            user_id,
            page_count,
            exc_info=True,
        )


async def reserve_email_usage(user_id: str, *, run_id: Optional[str] = None) -> None:
    """Check+record one email unit before calling Resend."""
    try:
        await reserve_outbound_usage(
            user_id,
            EMAIL_EVENT_TYPE,
            settings.free_email_limit_monthly,
            run_id=run_id,
        )
    except Exception as e:
        raise _http_for_usage_error(e) from e


async def reserve_sheets_usage(user_id: str, *, run_id: Optional[str] = None) -> None:
    """Check+record one Sheets unit before calling Google."""
    try:
        await reserve_outbound_usage(
            user_id,
            SHEETS_EVENT_TYPE,
            settings.free_sheets_limit_monthly,
            run_id=run_id,
        )
    except Exception as e:
        raise _http_for_usage_error(e) from e


async def refund_email_usage(user_id: str, *, run_id: Optional[str] = None) -> None:
    try:
        await refund_outbound_usage(
            user_id,
            EMAIL_EVENT_TYPE,
            run_id=run_id,
            reason="email_failed",
        )
    except Exception:
        logger.warning("Failed to refund email usage user=%s", user_id, exc_info=True)


async def refund_sheets_usage(user_id: str, *, run_id: Optional[str] = None) -> None:
    try:
        await refund_outbound_usage(
            user_id,
            SHEETS_EVENT_TYPE,
            run_id=run_id,
            reason="sheets_failed",
        )
    except Exception:
        logger.warning("Failed to refund sheets usage user=%s", user_id, exc_info=True)


async def reserve_rag_chat_tokens(
    user_id: str,
    tokens: int,
    *,
    run_id: Optional[str] = None,
) -> None:
    """Check+record estimated Ask-docs tokens before the OpenAI calls."""
    try:
        await reserve_outbound_usage(
            user_id,
            RAG_CHAT_EVENT_TYPE,
            settings.free_rag_token_limit_monthly,
            run_id=run_id,
            units=max(1, tokens),
        )
    except Exception as e:
        raise _http_for_usage_error(e) from e


async def reconcile_rag_chat_tokens(
    user_id: str,
    *,
    reserved: int,
    actual: int,
    run_id: Optional[str] = None,
) -> None:
    """Refund unused estimate or charge overrun after chat completes."""
    reserved = max(1, reserved)
    actual = max(0, actual)
    if actual < reserved:
        try:
            await refund_outbound_usage(
                user_id,
                RAG_CHAT_EVENT_TYPE,
                run_id=run_id,
                units=reserved - actual,
                reason="rag_token_reconcile",
            )
        except Exception:
            logger.warning(
                "Failed to refund RAG tokens user=%s", user_id, exc_info=True
            )
        return
    if actual > reserved:
        try:
            await reserve_outbound_usage(
                user_id,
                RAG_CHAT_EVENT_TYPE,
                settings.free_rag_token_limit_monthly,
                run_id=run_id,
                units=actual - reserved,
            )
        except UsageLimitError:
            # Answer already returned; charge remaining room only.
            from app.services.usage.metering import get_user_outbound_usage_this_month

            used = await get_user_outbound_usage_this_month(
                user_id, RAG_CHAT_EVENT_TYPE
            )
            room = settings.free_rag_token_limit_monthly - used
            if room > 0:
                await record_usage(
                    user_id,
                    room,
                    run_id=run_id,
                    event_type=RAG_CHAT_EVENT_TYPE,
                )
        except Exception:
            logger.warning(
                "Failed to charge RAG token overrun user=%s", user_id, exc_info=True
            )


async def refund_rag_chat_tokens(
    user_id: str,
    tokens: int,
    *,
    run_id: Optional[str] = None,
) -> None:
    try:
        await refund_outbound_usage(
            user_id,
            RAG_CHAT_EVENT_TYPE,
            run_id=run_id,
            units=max(1, tokens),
            reason="rag_chat_failed",
        )
    except Exception:
        logger.warning("Failed to refund RAG chat usage user=%s", user_id, exc_info=True)


# Back-compat aliases
async def record_run_usage(
    user_id: str,
    *,
    page_count: int,
    run_id: Optional[str] = None,
    template_id: Optional[str] = None,
    event_type: str = "extraction",
) -> None:
    await charge_run_pages(
        user_id,
        page_count=page_count,
        run_id=run_id,
        template_id=template_id,
        event_type=event_type,
    )


async def record_extract_usage(
    user_id: str,
    *,
    page_count: int,
    event_type: str = "extract_api",
) -> None:
    await charge_extract_pages(user_id, page_count)


async def enforce_email_usage(user_id: str) -> None:
    await reserve_email_usage(user_id)


async def enforce_sheets_usage(user_id: str) -> None:
    await reserve_sheets_usage(user_id)


async def record_email_usage(user_id: str, *, run_id: Optional[str] = None) -> None:
    return


async def record_sheets_usage(user_id: str, *, run_id: Optional[str] = None) -> None:
    return
