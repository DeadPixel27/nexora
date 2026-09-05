"""Admin routes — owner master template refining + OpenAI spend + evals."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import MasterRefineServiceDep
from app.config import settings
from app.services.evals.harness import harness_result_dict, run_eval_suite
from app.services.evals import store as eval_store
from app.services.llm.openai_cost import get_openai_spend_today

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(x_admin_key: Optional[str] = Header(default=None)) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="Admin API not configured")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin API key")


class EvalRunRequest(BaseModel):
    template_id: Optional[str] = Field(
        default=None,
        description="Filter golden set: invoice | receipt | all (default)",
    )
    limit: Optional[int] = Field(default=None, ge=1, le=20)
    min_field_accuracy: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Regression gate — fail if field accuracy is below this",
    )


@router.get("/openai-spend")
async def openai_spend_today(
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """In-process estimated OpenAI spend for the current UTC day."""
    return get_openai_spend_today()


@router.post("/evals/run")
async def run_evals(
    body: EvalRunRequest,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """
    Run the golden-set eval harness (inline; keep suite ≤10 docs).

    Calls OpenAI for each fixture — respects OPENAI_DAILY_BUDGET_USD.
    """
    result = await run_eval_suite(
        template_id=body.template_id,
        limit=body.limit,
        min_field_accuracy=body.min_field_accuracy,
    )
    payload = harness_result_dict(result)
    if not result.gate_passed:
        raise HTTPException(status_code=422, detail=payload)
    return payload


@router.get("/evals")
async def list_evals(
    limit: int = 20,
    _: None = Depends(_require_admin),
) -> list[dict[str, Any]]:
    return eval_store.list_eval_runs(limit=min(max(limit, 1), 100))


@router.get("/evals/{eval_id}")
async def get_eval(
    eval_id: str,
    include_field_details: bool = False,
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    row = eval_store.get_eval_run(
        eval_id, include_field_details=include_field_details
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return row


templates_router = APIRouter(prefix="/templates", tags=["admin"])


@templates_router.get("/feedback")
async def list_refinement_feedback(
    master: MasterRefineServiceDep,
    template_id: Optional[str] = None,
    limit: int = 100,
    _: None = Depends(_require_admin),
) -> list[dict]:
    return master.list_feedback(template_id=template_id, limit=limit)


@templates_router.post("/{template_id}/synthesize")
async def synthesize_master_template(
    template_id: str,
    master: MasterRefineServiceDep,
    _: None = Depends(_require_admin),
) -> dict:
    try:
        return await master.synthesize(template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@templates_router.post("/{template_id}/preview")
async def preview_master_template(
    template_id: str,
    synthesis: dict,
    master: MasterRefineServiceDep,
    _: None = Depends(_require_admin),
) -> dict:
    try:
        updated = master.preview_apply(template_id, synthesis)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "template_id": updated.template_id,
        "extraction_instructions": updated.extraction_instructions,
        "fields": updated.fields,
        "rules": updated.rules,
    }


@templates_router.post("/{template_id}/apply")
async def apply_master_template(
    template_id: str,
    synthesis: dict,
    master: MasterRefineServiceDep,
    _: None = Depends(_require_admin),
) -> dict:
    """Persist owner synthesis to the master template catalog."""
    try:
        updated = master.apply_synthesis(template_id, synthesis)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "template_id": updated.template_id,
        "extraction_instructions": updated.extraction_instructions,
        "fields": updated.fields,
        "rules": updated.rules,
        "message": "Master template updated.",
    }


router.include_router(templates_router)
