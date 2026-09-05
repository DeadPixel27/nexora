"""
Runs Route — execute pipeline plans and fetch run results.
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import (
    CurrentUserDep,
    RefineServiceDep,
    RepoDep,
    TemplateServiceDep,
    VersionServiceDep,
)
from app.api.mappers.planned_step import to_planned_steps
from app.api.mappers.run import to_run_response
from app.api.ownership import get_owned_upload
from app.api.usage_http import (
    charge_run_pages,
    charge_run_pages_or_abandon,
    enforce_upload_usage,
    reconcile_rag_chat_tokens,
    refund_rag_chat_tokens,
    reserve_rag_chat_tokens,
)
from app.config import settings
from app.jobs import schedule_run
from app.models.api.runs import (
    RunAdhocRequest,
    RefinePlanRequest,
    RefinePlanResponse,
    RunDocChatRequest,
    RunDocChatResponse,
    RunRefineRequest,
    RunRefineResponse,
    RunRequest,
    RunResponse,
    RunTemplateRequest,
)
from app.services.analytics.events import log_event
from app.services.pipeline.refine_service import (
    RunNotFoundError,
    RunNotRefinableError,
)
from app.services.pipeline.pipeline_refiner import RefinerError
from app.rate_limit import limiter
from app.models.domain.template import TemplateNotFoundError
from app.services.documents.upload_loader import UploadNotFoundError
from app.services.pipeline.planner import create_plan
from app.services.pipeline.runner import start_run
from app.services.usage.metering import RefineLimitError, check_refine_allowed

router = APIRouter(prefix="/api/runs", tags=["runs"])
logger = logging.getLogger("api")


@router.post("/adhoc", response_model=RunResponse)
@limiter.limit(settings.rate_limit_runs_adhoc)
async def run_adhoc(
    request: Request,
    body: RunAdhocRequest,
    repo: RepoDep,
    current_user: CurrentUserDep,
) -> RunResponse:
    """Plan a pipeline and start execution. Poll GET /api/runs/{id} for progress."""
    get_owned_upload(repo, body.upload_id, current_user)
    page_count = await enforce_upload_usage(current_user.user_id, body.upload_id)
    try:
        plan = await create_plan(body.upload_id, body.task_description)
        run = await start_run(
            body.upload_id,
            plan.steps,
            plan.task_description,
            user_id=current_user.user_id,
        )
    except UploadNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    await charge_run_pages_or_abandon(
        current_user.user_id,
        run,
        page_count=page_count,
    )
    await schedule_run(run.run_id)
    return to_run_response(run)


@router.post("/template", response_model=RunResponse)
@limiter.limit(settings.rate_limit_runs_adhoc)
async def run_template(
    request: Request,
    body: RunTemplateRequest,
    template_service: TemplateServiceDep,
    versions: VersionServiceDep,
    repo: RepoDep,
    current_user: CurrentUserDep,
) -> RunResponse:
    """Run a pipeline from a template definition. Poll GET /api/runs/{id} for progress."""
    get_owned_upload(repo, body.upload_id, current_user)
    page_count = await enforce_upload_usage(current_user.user_id, body.upload_id)
    try:
        plan = await template_service.build_plan(body.template_id, body.upload_id)
        template = template_service.get_template(body.template_id)
        run = await start_run(
            body.upload_id,
            plan.steps,
            plan.task_description,
            template_id=template.template_id,
            extraction_prompt=template.extraction_instructions,
            user_id=current_user.user_id,
        )
        run = versions.attach_initial_run_version(
            run,
            template_id=template.template_id,
            planned_steps=run.planned_steps,
            extraction_prompt=template.extraction_instructions,
        )
    except TemplateNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except UploadNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    await charge_run_pages_or_abandon(
        current_user.user_id,
        run,
        page_count=page_count,
        template_id=body.template_id,
    )
    await schedule_run(run.run_id)
    return to_run_response(run)


@router.post("", response_model=RunResponse)
@limiter.limit(settings.rate_limit_runs_adhoc)
async def run_pipeline_steps(
    request: Request,
    body: RunRequest,
    repo: RepoDep,
    current_user: CurrentUserDep,
) -> RunResponse:
    """Run an explicit plan. Poll GET /api/runs/{id} for progress."""
    get_owned_upload(repo, body.upload_id, current_user)
    page_count = await enforce_upload_usage(current_user.user_id, body.upload_id)
    try:
        steps = to_planned_steps(body.steps)
        run = await start_run(
            body.upload_id,
            steps,
            body.task_description,
            user_id=current_user.user_id,
        )
    except UploadNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    await charge_run_pages_or_abandon(
        current_user.user_id,
        run,
        page_count=page_count,
    )
    await schedule_run(run.run_id)
    return to_run_response(run)


@router.post("/{run_id}/refine/plan", response_model=RefinePlanResponse)
@limiter.limit(settings.rate_limit_refine_plan)
async def refine_plan(
    request: Request,
    run_id: str,
    body: RefinePlanRequest,
    repo: RepoDep,
    versions: VersionServiceDep,
    current_user: CurrentUserDep,
) -> RefinePlanResponse:
    """
    Plan Mode: clarify user intent with a cheap/fast model before re-running.
    Call this for each chat message. When response.ready is true,
    call POST /refine with the accumulated_instruction as the message.
    """
    from app.services.pipeline.refine_chat import plan_refinement
    from app.services.pipeline.refine_preview import preview_refinement

    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    from app.api.ownership import require_run_access

    await require_run_access(run, current_user, repo)

    try:
        await check_refine_allowed(run_id, repo=repo)
    except RefineLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e

    run = versions.hydrate_run(run)

    logger.info(
        "[refine] plan request run_id=%s message_len=%d history_turns=%d",
        run_id,
        len(body.message),
        len(body.chat_history),
    )

    rows = (run.result or {}).get("rows", [])
    field_names = list(rows[0].keys()) if rows else []
    skip = {"document_id", "flags", "filename"}
    field_names = [f for f in field_names if f not in skip]

    chat_history = [{"role": m.role, "content": m.content} for m in body.chat_history]

    try:
        result = await plan_refinement(
            message=body.message,
            chat_history=chat_history,
            field_names=field_names,
            sample_rows=rows[:2],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Plan mode failed: {e}") from e

    logger.info(
        "[refine] plan result run_id=%s in_scope=%s ready=%s planned_changes=%s instruction_len=%d",
        run_id,
        result.get("in_scope", True),
        result["ready"],
        result.get("planned_changes"),
        len(str(result.get("accumulated_instruction") or "")),
    )

    # Plan chat (Groq) is cheap and unmetered. Preview re-extracts with GPT-4o —
    # reserve pages before preview (fail-closed); refund if preview crashes.
    # Never preview when out of scope or not ready.
    preview: list = []
    if (
        result.get("in_scope", True)
        and result["ready"]
        and result.get("accumulated_instruction")
    ):
        page_count = await enforce_upload_usage(
            current_user.user_id, run.upload_id
        )
        await charge_run_pages(
            current_user.user_id,
            page_count=page_count,
            run_id=run_id,
            template_id=run.template_id,
            event_type="refine_preview",
        )
        try:
            preview = await preview_refinement(
                run,
                versions,
                str(result["accumulated_instruction"]),
                result.get("planned_changes") or [],
            )
        except Exception as e:
            logger.warning("Refine preview failed run_id=%s: %s", run_id, e, exc_info=True)
            try:
                from app.services.usage.metering import record_usage

                await record_usage(
                    current_user.user_id,
                    -page_count,
                    run_id=run_id,
                    event_type="refund:refine_preview",
                )
            except Exception:
                logger.warning(
                    "Failed to refund refine_preview usage run_id=%s",
                    run_id,
                    exc_info=True,
                )

    if preview:
        for row in preview:
            for field_row in row.get("fields", []):
                logger.info(
                    "[refine] plan preview summary run_id=%s doc=%s %s: %s -> %s",
                    run_id,
                    row.get("document_id"),
                    field_row.get("field"),
                    field_row.get("before"),
                    field_row.get("after"),
                )

    return RefinePlanResponse(
        ready=result["ready"],
        message=result["message"],
        planned_changes=result["planned_changes"],
        accumulated_instruction=result["accumulated_instruction"],
        preview=preview,
        in_scope=bool(result.get("in_scope", True)),
    )


@router.post("/{run_id}/refine", response_model=RunRefineResponse)
@limiter.limit(settings.rate_limit_runs_adhoc)
async def refine_run(
    request: Request,
    run_id: str,
    body: RunRefineRequest,
    refine_service: RefineServiceDep,
    repo: RepoDep,
    current_user: CurrentUserDep,
) -> RunRefineResponse:
    """Refine a completed run's pipeline via chat and start a child run."""
    from app.api.ownership import require_run_access

    parent = repo.get_run(run_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    await require_run_access(parent, current_user, repo)

    logger.info(
        "[refine] apply request parent_run_id=%s message_len=%d",
        run_id,
        len(body.message),
    )
    if parent.status == "running":
        raise HTTPException(
            status_code=400,
            detail="Cannot refine a run that is still in progress",
        )
    try:
        await check_refine_allowed(run_id, repo=repo)
    except RefineLimitError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e

    # Reserve pages before Groq refiner / GPT-4o re-run (fail-closed).
    page_count = await enforce_upload_usage(current_user.user_id, parent.upload_id)
    await charge_run_pages(
        current_user.user_id,
        page_count=page_count,
        run_id=run_id,
        template_id=parent.template_id,
        event_type="refine",
    )

    async def _refund_refine_charge() -> None:
        try:
            from app.services.usage.metering import record_usage

            await record_usage(
                current_user.user_id,
                -page_count,
                run_id=run_id,
                event_type="refund:refine",
            )
        except Exception:
            logger.warning(
                "Failed to refund refine usage parent_run_id=%s",
                run_id,
                exc_info=True,
            )

    try:
        run, summary = await refine_service.refine_and_start(run_id, body.message)
    except RunNotFoundError as e:
        await _refund_refine_charge()
        raise HTTPException(status_code=404, detail=str(e))
    except RunNotRefinableError as e:
        await _refund_refine_charge()
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        await _refund_refine_charge()
        raise HTTPException(status_code=400, detail=str(e))
    except RefinerError as e:
        await _refund_refine_charge()
        raise HTTPException(status_code=502, detail=str(e))

    # Targeted single-field refine returns a completed run — skip re-execution
    if run.status == "running":
        await schedule_run(run.run_id)
    logger.info(
        "[refine] apply queued child_run_id=%s parent_run_id=%s status=%s summary=%r",
        run.run_id,
        run_id,
        run.status,
        summary,
    )
    await log_event(
        "run_refined",
        user_id=current_user.user_id,
        run_id=run.run_id,
        metadata={"parent_run_id": run_id},
    )
    from app.services.audit.events import log_audit

    await log_audit(
        "run.refined",
        actor_user_id=current_user.user_id,
        resource_type="run",
        resource_id=run.run_id,
        metadata={"parent_run_id": run_id},
    )
    return RunRefineResponse(run=to_run_response(run), refine_summary=summary)


@router.post("/{run_id}/chat", response_model=RunDocChatResponse)
@limiter.limit(settings.rate_limit_refine_plan)
async def chat_run_documents(
    request: Request,
    run_id: str,
    body: RunDocChatRequest,
    repo: RepoDep,
    current_user: CurrentUserDep,
) -> RunDocChatResponse:
    """Ask a question over this run's indexed document text (RAG)."""
    from app.api.ownership import require_run_access
    from app.services.llm.openai_cost import OpenAIBudgetError
    from app.services.rag import chat_over_run
    from app.services.rag.chat import estimate_rag_chat_tokens

    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    await require_run_access(run, current_user, repo)
    if run.status != "completed":
        raise HTTPException(
            status_code=400,
            detail="Document chat is only available after the run completes.",
        )

    reserved = estimate_rag_chat_tokens(body.question)
    await reserve_rag_chat_tokens(
        current_user.user_id, reserved, run_id=run_id
    )
    try:
        result = await chat_over_run(run_id=run_id, question=body.question)
    except RuntimeError as e:
        await refund_rag_chat_tokens(
            current_user.user_id, reserved, run_id=run_id
        )
        raise HTTPException(status_code=503, detail=str(e)) from e
    except ValueError as e:
        await refund_rag_chat_tokens(
            current_user.user_id, reserved, run_id=run_id
        )
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OpenAIBudgetError as e:
        await refund_rag_chat_tokens(
            current_user.user_id, reserved, run_id=run_id
        )
        raise HTTPException(status_code=429, detail=str(e)) from e
    except Exception as e:
        await refund_rag_chat_tokens(
            current_user.user_id, reserved, run_id=run_id
        )
        logger.exception("RAG chat failed run_id=%s", run_id)
        raise HTTPException(status_code=502, detail="Document chat failed") from e

    actual = int(result.get("tokens_used") or 0)
    await reconcile_rag_chat_tokens(
        current_user.user_id,
        reserved=reserved,
        actual=actual,
        run_id=run_id,
    )
    return RunDocChatResponse(**result)


@router.get("/{run_id}", response_model=RunResponse)
async def get_run_status(
    run_id: str,
    repo: RepoDep,
    versions: VersionServiceDep,
    current_user: CurrentUserDep,
) -> RunResponse:
    """Fetch a run — poll while status is 'running'."""
    from app.api.ownership import require_run_access
    from app.services.pipeline.orphan_reclaim import maybe_reclaim_run

    run = repo.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    await require_run_access(run, current_user, repo)
    run = await maybe_reclaim_run(run)
    return to_run_response(versions.hydrate_run(run))
