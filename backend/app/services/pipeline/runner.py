"""
Workflow runner — executes an ordered list of steps against an upload.

Runs are started with status "running" and step rows "queued", then executed
in a background task with progress persisted after each step for polling.
"""

import logging
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Optional

import app.agents.handlers  # noqa: F401 — register agents
from app.agents.core.context import WorkflowContext, documents_to_dicts
from app.agents.core.registry import get_handler
from app.models.domain.pipeline import PlannedStep
from app.models.domain.run import RunResult, StepRunRecord
from app.persistence import get_run, get_repository, get_user_template_store, save_run
from app.services.documents.upload_loader import load_upload_documents
from app.services.pipeline.extraction_prompt import (
    read_prompt_from_steps,
    resolve_run_extraction_prompt,
    sync_prompt_to_steps,
)
from app.services.templates.user_template_version_service import UserTemplateVersionService
from app.validation.task_input import sanitize_task_input

logger = logging.getLogger("runner")

_PROCESSOR_AGENTS = frozenset({"processor.ocr", "processor.text_extract"})


def _sorted_steps(steps: list[PlannedStep]) -> list[PlannedStep]:
    return sorted(steps, key=lambda s: s.step_order)


def _snapshot_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "document_id": doc.get("document_id", ""),
            "filename": doc.get("filename", ""),
            "file_type": doc.get("file_type", ""),
            "text": doc.get("text", ""),
            "extraction_method": doc.get("extraction_method", ""),
            "storage_key": doc.get("storage_key", ""),
        }
        for doc in documents
    ]


def _version_service() -> UserTemplateVersionService:
    return UserTemplateVersionService(get_repository(), get_user_template_store())


async def start_run(
    upload_id: str,
    steps: list[PlannedStep],
    task_description: str = "",
    workflow_id: Optional[str] = None,
    parent_run_id: Optional[str] = None,
    template_id: Optional[str] = None,
    extraction_prompt: Optional[str] = None,
    current_template_version_id: Optional[str] = None,
    cached_documents: Optional[list[dict[str, Any]]] = None,
    refine_summary: Optional[str] = None,
    user_id: Optional[str] = None,
) -> RunResult:
    """Create a run record in 'running' state with queued steps."""
    if cached_documents:
        document_ids = [
            doc.get("document_id", "")
            for doc in cached_documents
            if doc.get("document_id")
        ]
        if not document_ids:
            raise ValueError(f"No document ids in cached documents for upload {upload_id}")
    else:
        documents = await load_upload_documents(upload_id)
        if not documents:
            raise ValueError(f"No documents found for upload {upload_id}")
        document_ids = [doc.document_id for doc in documents]
    planned = _sorted_steps(steps)
    prompt = resolve_run_extraction_prompt(extraction_prompt, planned)
    if not prompt:
        prompt = read_prompt_from_steps(planned)
    if prompt:
        planned = sync_prompt_to_steps(planned, prompt)

    run_id = str(uuid.uuid4())

    run = RunResult(
        run_id=run_id,
        upload_id=upload_id,
        task_description=sanitize_task_input(task_description),
        status="running",
        steps=[
            StepRunRecord(
                step_order=step.step_order,
                agent_type=step.agent_type,
                status="queued",
            )
            for step in planned
        ],
        document_ids=document_ids,
        planned_steps=planned,
        workflow_id=workflow_id,
        parent_run_id=parent_run_id,
        template_id=template_id,
        current_template_version_id=current_template_version_id,
        extraction_prompt=prompt or None,
        cached_documents=cached_documents,
        refine_summary=refine_summary,
        user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    save_run(run)
    logger.info(
        "Run %s started — upload_id=%s, %d step(s), parent=%s user=%s",
        run_id,
        upload_id,
        len(planned),
        parent_run_id,
        user_id,
    )
    return run


async def execute_run(run_id: str) -> None:
    """Execute a started run, saving progress after each step."""
    from app.services.analytics.events import log_event, track_duration
    from app.services.usage.metering import get_user_id_for_run
    from app.services.usage.page_count import count_upload_pages

    run = get_run(run_id)
    if run is None:
        logger.error("Run %s not found for execution", run_id)
        return
    if run.status != "running":
        logger.warning("Run %s is not running (status=%s)", run_id, run.status)
        return

    user_id = await get_user_id_for_run(run_id)
    from app.logging_context import set_run_id, set_user_id

    set_run_id(run_id)
    if user_id:
        set_user_id(user_id)
    try:
        page_count = await count_upload_pages(run.upload_id)
    except Exception:
        page_count = len(run.document_ids) or 1

    if run.cached_documents:
        documents = run.cached_documents
    else:
        upload_docs = await load_upload_documents(run.upload_id)
        documents = documents_to_dicts(upload_docs)

    versions = _version_service()
    planned, prompt = versions.resolve_run_plan(run)
    planned = _sorted_steps(planned)
    if prompt:
        planned = sync_prompt_to_steps(planned, prompt)

    from app.services.pipeline.refine_logging import log_prompt, prompt_fingerprint

    log_prompt(
        logger,
        "execute",
        run_id=run_id,
        label="resolved_extraction_prompt",
        prompt=prompt or "",
        extra={"parent_run_id": run.parent_run_id, "prompt_fp": prompt_fingerprint(prompt or "")},
    )

    ctx = WorkflowContext(
        upload_id=run.upload_id,
        task_description=run.task_description,
        data={
            "documents": documents,
            "user_id": user_id,
            "run_id": run_id,
        },
    )

    step_runs = list(run.steps)
    has_cached_text = bool(run.cached_documents)

    with track_duration() as duration:
        try:
            for index, step in enumerate(planned):
                from app.services.observability import agent_step_span, mark_span_skipped

                with agent_step_span(
                    agent_type=step.agent_type,
                    run_id=run_id,
                    step_order=step.step_order,
                ) as span:
                    if has_cached_text and step.agent_type in _PROCESSOR_AGENTS:
                        mark_span_skipped(span)
                        step_runs[index] = replace(
                            step_runs[index],
                            status="skipped",
                            output={"skipped": True, "reason": "cached_document_text"},
                        )
                        save_run(replace(run, steps=step_runs))
                        continue

                    logger.info(
                        "Run %s — step %d: %s",
                        run_id,
                        step.step_order,
                        step.agent_type,
                    )
                    step_runs[index] = replace(
                        step_runs[index],
                        status="running",
                        error_message=None,
                    )
                    save_run(replace(run, steps=step_runs))

                    handler = get_handler(step.agent_type)
                    result = await handler.execute(ctx, step.config)
                    step_runs[index] = replace(
                        step_runs[index],
                        status="completed",
                        output=result.output,
                    )

                    if step.agent_type == "transform.field_extractor":
                        from app.services.pipeline.refine_logging import log_field_snapshot

                        instructions = str(step.config.get("instructions") or "")
                        rows = ctx.data.get("rows", [])
                        logger.info(
                            "[refine] execute field_extractor run_id=%s parent_run_id=%s "
                            "instructions_len=%d row_count=%d",
                            run_id,
                            run.parent_run_id,
                            len(instructions),
                            len(rows),
                        )
                        for row in rows[:3]:
                            yoe_key = "years_of_experience"
                            field_filter = (
                                {yoe_key}
                                if yoe_key in row or yoe_key in step.config.get("fields", [])
                                else None
                            )
                            log_field_snapshot(
                                logger,
                                "execute-extract-result",
                                run_id=run_id,
                                document_id=str(row.get("document_id", "")),
                                fields=row,
                                field_filter=field_filter,
                            )

                    cached = _snapshot_documents(ctx.data.get("documents", []))
                    save_run(
                        replace(
                            run,
                            steps=step_runs,
                            cached_documents=cached,
                        )
                    )

        except Exception as e:
            logger.exception("Run %s failed at step %s", run_id, step.agent_type)
            step_runs[index] = replace(
                step_runs[index],
                status="failed",
                error_message=str(e),
            )
            save_run(
                replace(
                    run,
                    status="failed",
                    steps=step_runs,
                    error_message=str(e),
                    cached_documents=_snapshot_documents(ctx.data.get("documents", [])),
                )
            )
            try:
                from app.services.usage.metering import refund_usage_for_run

                await refund_usage_for_run(run_id, reason="run_failed")
            except Exception:
                logger.warning("Usage refund failed for run=%s", run_id, exc_info=True)
            try:
                await log_event(
                    "run_failed",
                    user_id=user_id,
                    run_id=run_id,
                    template_id=run.template_id,
                    page_count=page_count,
                    duration_ms=duration["ms"],
                    error=type(e).__name__,
                )
            except Exception:
                pass
            try:
                from app.services.audit.events import log_audit

                await log_audit(
                    "run.failed",
                    actor_user_id=user_id,
                    resource_type="run",
                    resource_id=run_id,
                    metadata={"error": type(e).__name__, "step": step.agent_type},
                )
            except Exception:
                pass
            return

    final_output = ctx.data.get("output")
    # Ensure confidence/validation/filter counts survive even if formatter was skipped
    if isinstance(final_output, dict):
        extras: dict = {}
        if "field_confidence" not in final_output and ctx.data.get("field_confidence"):
            extras["field_confidence"] = ctx.data.get("field_confidence") or {}
            extras["validation_warnings"] = ctx.data.get("validation_warnings") or {}
        if "filtered_count" not in final_output and ctx.data.get("filtered_rows"):
            extras["filtered_count"] = len(ctx.data.get("filtered_rows") or [])
        if extras:
            final_output = {**final_output, **extras}
    elif ctx.data.get("field_confidence") or ctx.data.get("validation_warnings"):
        final_output = {
            "rows": ctx.data.get("rows") or [],
            "field_confidence": ctx.data.get("field_confidence") or {},
            "validation_warnings": ctx.data.get("validation_warnings") or {},
            "filtered_count": len(ctx.data.get("filtered_rows") or []),
        }

    logger.info("Run %s completed — %d row(s)", run_id, len(ctx.data.get("rows", [])))
    completed_run = replace(
        run,
        status="completed",
        steps=step_runs,
        result=final_output,
        cached_documents=_snapshot_documents(ctx.data.get("documents", [])),
    )
    save_run(completed_run)
    try:
        from app.services.rag import index_run_documents

        await index_run_documents(
            run_id=run_id,
            user_id=user_id,
            documents=completed_run.cached_documents or [],
        )
    except Exception:
        logger.warning("RAG index hook failed for run=%s", run_id, exc_info=True)
    try:
        await log_event(
            "run_completed",
            user_id=user_id,
            run_id=run_id,
            template_id=run.template_id,
            page_count=page_count,
            duration_ms=duration["ms"],
        )
    except Exception:
        pass
    try:
        from app.services.audit.events import log_audit

        await log_audit(
            "run.completed",
            actor_user_id=user_id,
            resource_type="run",
            resource_id=run_id,
            metadata={"page_count": page_count, "duration_ms": duration["ms"]},
        )
    except Exception:
        pass

    try:
        from app.services.email.workflow_delivery import deliver_workflow_defaults

        rows = []
        if isinstance(final_output, dict):
            rows = final_output.get("rows") or []
        await deliver_workflow_defaults(completed_run, rows)
    except Exception:
        logger.exception("Workflow default delivery failed for run %s", run_id)


async def run_pipeline(
    upload_id: str,
    steps: list[PlannedStep],
    task_description: str = "",
    workflow_id: Optional[str] = None,
) -> RunResult:
    """Run synchronously (used in tests or when background execution is not needed)."""
    run = await start_run(upload_id, steps, task_description, workflow_id)
    await execute_run(run.run_id)
    finished = get_run(run.run_id)
    return finished if finished is not None else run
