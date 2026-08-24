"""Inbound email webhook — receives forwarded emails from Mailgun."""

import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import InboundEmailServiceDep, WorkflowServiceDep
from app.api.usage_http import charge_run_pages_or_abandon, enforce_upload_usage
from app.config import settings
from app.jobs import schedule_run
from app.models.domain.document import InvalidUploadError
from app.models.domain.email import InboundAddressNotFoundError
from app.rate_limit import limiter
from app.services.documents.upload_loader import UploadNotFoundError
from app.services.workflows.workflow_service import WorkflowNotFoundError

router = APIRouter(prefix="/api/inbound", tags=["inbound"])
logger = logging.getLogger("inbound")

# Single-replica seen-token cache: token -> expires_at (unix seconds)
_seen_tokens: dict[str, float] = {}


def reset_seen_tokens() -> None:
    """Clear replay cache (tests only)."""
    _seen_tokens.clear()


def _prune_seen_tokens(now: float) -> None:
    expired = [token for token, exp in _seen_tokens.items() if exp <= now]
    for token in expired:
        _seen_tokens.pop(token, None)


def _is_token_seen(token: str, *, now: Optional[float] = None) -> bool:
    current = now if now is not None else time.time()
    _prune_seen_tokens(current)
    exp = _seen_tokens.get(token)
    return exp is not None and exp > current


def _mark_token_seen(token: str, *, now: Optional[float] = None) -> None:
    current = now if now is not None else time.time()
    _prune_seen_tokens(current)
    ttl = max(1, int(settings.inbound_webhook_token_ttl_seconds))
    _seen_tokens[token] = current + ttl


def _verify_mailgun_signature(token: str, timestamp: str, signature: str) -> None:
    """
    Verify Mailgun webhook signature + timestamp skew.

    Raises HTTPException(403) on failure. Fail closed when secret is unset.
    """
    if not settings.inbound_webhook_secret:
        logger.error("INBOUND_WEBHOOK_SECRET is not set — rejecting webhook")
        raise HTTPException(status_code=403, detail="Invalid signature")

    if not token or not timestamp or not signature:
        raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        ts = int(timestamp)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid signature") from exc

    now = int(time.time())
    max_age = max(0, int(settings.inbound_webhook_max_age_seconds))
    delta = abs(now - ts)
    if delta > max_age:
        if ts < now:
            raise HTTPException(status_code=403, detail="Webhook timestamp expired")
        raise HTTPException(status_code=403, detail="Webhook timestamp too far in future")

    hmac_digest = hmac.new(
        key=settings.inbound_webhook_secret.encode(),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, hmac_digest):
        raise HTTPException(status_code=403, detail="Invalid signature")


@router.post("/email")
@limiter.limit(settings.rate_limit_inbound)
async def receive_inbound_email(
    request: Request,
    inbound: InboundEmailServiceDep,
    workflows: WorkflowServiceDep,
):
    """Mailgun posts here when email arrives at *@ingest.nexora.app."""
    form = await request.form()
    token = str(form.get("token", ""))
    timestamp = str(form.get("timestamp", ""))
    signature = str(form.get("signature", ""))

    _verify_mailgun_signature(token, timestamp, signature)

    if _is_token_seen(token):
        logger.info("Ignoring duplicate inbound webhook token=%s…", token[:8])
        return {"status": "duplicate"}

    recipient = str(form.get("recipient", ""))
    sender = str(form.get("sender", ""))

    attachments = []
    for key in form:
        if key.startswith("attachment-"):
            file = form[key]
            content = await file.read()
            attachments.append({
                "filename": file.filename,
                "content": content,
                "content_type": file.content_type or "application/octet-stream",
            })

    try:
        upload_id, workflow_id, _reply_to, owner_user_id = await inbound.process_inbound(
            recipient, sender, attachments
        )
        page_count = await enforce_upload_usage(owner_user_id, upload_id)
        run = await workflows.start_workflow_run(workflow_id, upload_id)
        await charge_run_pages_or_abandon(
            owner_user_id,
            run,
            page_count=page_count,
            template_id=getattr(run, "template_id", None),
            event_type="inbound_email",
        )
        from app.logging_context import set_user_id
        from app.services.audit.events import log_audit

        set_user_id(owner_user_id)
        await schedule_run(run.run_id)
        _mark_token_seen(token)
        await log_audit(
            "inbound.received",
            actor_user_id=owner_user_id,
            resource_type="run",
            resource_id=run.run_id,
            metadata={"workflow_id": workflow_id, "upload_id": upload_id},
        )
        return {"status": "processing", "run_id": run.run_id}
    except InboundAddressNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (
        WorkflowNotFoundError,
        UploadNotFoundError,
        ValueError,
        InvalidUploadError,
    ) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
