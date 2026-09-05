"""Run golden-set extraction evals and persist results."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional

from app.config import settings
from app.services.evals import store as eval_store
from app.services.evals.golden_set import GoldenCase, fixture_path, resolve_cases
from app.services.evals.scoring import DocResult, score_fields
from app.services.documents.text_extractor import extract_text
from app.services.extraction.field_extractor import DocumentInput, extract_fields
from app.templates.registry import get_template_by_id

logger = logging.getLogger("evals")


@dataclass
class EvalHarnessResult:
    eval_id: str
    status: str
    doc_count: int
    docs_passed: int
    field_checks: int
    field_ok: int
    field_accuracy: Optional[float]
    gate_passed: bool
    min_field_accuracy: Optional[float]
    items: list[dict[str, Any]]


async def _score_case(case: GoldenCase) -> DocResult:
    path = fixture_path(case.relative_path)
    template = get_template_by_id(case.template_id)
    if template is None:
        return DocResult(
            path=path,
            template_id=case.template_id,
            text_method="error",
            text_len=0,
            error=f"unknown template {case.template_id}",
        )
    if not path.exists():
        return DocResult(
            path=path,
            template_id=case.template_id,
            text_method="error",
            text_len=0,
            error="fixture missing",
        )

    try:
        text_result = await extract_text(path)
        if text_result.error_message or len(text_result.text.strip()) < 20:
            return DocResult(
                path=path,
                template_id=case.template_id,
                text_method=text_result.method,
                text_len=len(text_result.text),
                error=text_result.error_message or "insufficient text extracted",
            )

        docs = await extract_fields(
            [
                DocumentInput(
                    document_id=path.stem,
                    text=text_result.text,
                    filename=path.name,
                )
            ],
            fields=template.fields,
            instructions=template.extraction_instructions,
        )
        fields = docs[0].fields if docs else {}
        return DocResult(
            path=path,
            template_id=case.template_id,
            text_method=text_result.method,
            text_len=len(text_result.text),
            scores=score_fields(case.expected, fields, case.matchers),
        )
    except Exception as exc:
        logger.exception("Eval case failed: %s", case.relative_path)
        return DocResult(
            path=path,
            template_id=case.template_id,
            text_method="error",
            text_len=0,
            error=str(exc),
        )


def _item_row(case: GoldenCase, result: DocResult) -> dict[str, Any]:
    scores = [
        {
            "field": s.field,
            "ok": s.ok,
            "note": s.note,
            # Stored for owner debugging; API strips expected/actual by default
            "expected": s.expected,
            "actual": s.actual,
        }
        for s in result.scores
    ]
    field_ok = sum(1 for s in result.scores if s.ok)
    return {
        "fixture_path": case.relative_path,
        "template_id": case.template_id,
        "passed": result.passed,
        "field_checks": len(result.scores),
        "field_ok": field_ok,
        "text_method": result.text_method,
        "text_len": result.text_len,
        "error_message": result.error,
        "field_scores": scores,
    }


async def run_eval_suite(
    *,
    template_id: Optional[str] = None,
    limit: Optional[int] = None,
    min_field_accuracy: Optional[float] = None,
    suite: str = "golden",
    persist: bool = True,
    extract_one=None,
) -> EvalHarnessResult:
    """
    Run the golden set.

    ``extract_one`` is an optional async callable(case) -> DocResult for tests.
    """
    cases = resolve_cases(template_id=template_id, limit=limit)
    model = settings.openai_model
    eval_id = "ephemeral"
    if persist:
        eval_id = eval_store.create_eval_run(
            suite=suite,
            template_filter=template_id,
            model=model,
            metadata={"limit": limit},
        )

    items: list[dict[str, Any]] = []
    scorer = extract_one or _score_case
    try:
        for case in cases:
            result = await scorer(case)
            items.append(_item_row(case, result))
    except Exception as exc:
        if persist:
            eval_store.complete_eval_run(
                eval_id,
                status="failed",
                doc_count=len(items),
                field_checks=0,
                field_ok=0,
                docs_passed=0,
                field_accuracy=None,
                error_message=str(exc),
                items=items,
            )
        raise

    field_checks = sum(i["field_checks"] for i in items)
    field_ok = sum(i["field_ok"] for i in items)
    docs_passed = sum(1 for i in items if i["passed"])
    accuracy = (field_ok / field_checks) if field_checks else None
    gate_passed = True
    if min_field_accuracy is not None and accuracy is not None:
        gate_passed = accuracy >= min_field_accuracy

    status = "completed" if gate_passed else "failed_gate"
    if persist:
        eval_store.complete_eval_run(
            eval_id,
            status=status,
            doc_count=len(items),
            field_checks=field_checks,
            field_ok=field_ok,
            docs_passed=docs_passed,
            field_accuracy=accuracy,
            error_message=(
                None
                if gate_passed
                else f"field_accuracy {accuracy:.3f} < min {min_field_accuracy}"
            ),
            items=items,
        )

    public_items = [
        {
            "fixture_path": i["fixture_path"],
            "template_id": i["template_id"],
            "passed": i["passed"],
            "field_checks": i["field_checks"],
            "field_ok": i["field_ok"],
            "text_method": i["text_method"],
            "text_len": i["text_len"],
            "error_message": i["error_message"],
            "field_scores": [
                {"field": s["field"], "ok": s["ok"], "note": s.get("note") or ""}
                for s in i["field_scores"]
            ],
        }
        for i in items
    ]

    return EvalHarnessResult(
        eval_id=eval_id,
        status=status,
        doc_count=len(items),
        docs_passed=docs_passed,
        field_checks=field_checks,
        field_ok=field_ok,
        field_accuracy=accuracy,
        gate_passed=gate_passed,
        min_field_accuracy=min_field_accuracy,
        items=public_items,
    )


def harness_result_dict(result: EvalHarnessResult) -> dict[str, Any]:
    return asdict(result)
