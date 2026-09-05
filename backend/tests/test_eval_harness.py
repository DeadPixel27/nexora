"""Eval harness — scoring + memory store (no OpenAI)."""

from pathlib import Path

import pytest

from app.services.evals import store as eval_store
from app.services.evals.golden_set import GoldenCase, default_golden_cases
from app.services.evals.harness import run_eval_suite
from app.services.evals.scoring import (
    DocResult,
    FieldScore,
    amount_match,
    date_match,
    score_fields,
    vendor_match,
)


@pytest.fixture(autouse=True)
def _reset_evals(monkeypatch):
    eval_store.reset_memory_evals()
    monkeypatch.setattr(
        "app.persistence.supabase_repository.is_supabase_configured",
        lambda: False,
    )
    yield
    eval_store.reset_memory_evals()


def test_golden_set_nonempty_and_fixtures_exist():
    cases = default_golden_cases()
    assert len(cases) >= 3
    assert len(cases) <= 10
    from app.services.evals.golden_set import fixture_path

    for case in cases:
        assert fixture_path(case.relative_path).exists(), case.relative_path


def test_score_fields_per_field_accuracy():
    scores = score_fields(
        {"vendor_name": "Acme", "total_amount": 100.0, "invoice_date": "2026-01-15"},
        {"vendor_name": "Acme Inc", "total_amount": 100.0, "invoice_date": "2026-01-16"},
        {
            "vendor_name": vendor_match,
            "total_amount": amount_match,
            "invoice_date": date_match,
        },
    )
    by_field = {s.field: s.ok for s in scores}
    assert by_field["vendor_name"] is True
    assert by_field["total_amount"] is True
    assert by_field["invoice_date"] is False


@pytest.mark.asyncio
async def test_run_eval_suite_persists_and_gates():
    async def fake_extract(case: GoldenCase) -> DocResult:
        ok = case.template_id == "invoice"
        scores = [
            FieldScore(field=name, expected=exp, actual=exp if ok else None, ok=ok)
            for name, exp in case.expected.items()
        ]
        return DocResult(
            path=Path(case.relative_path),
            template_id=case.template_id,
            text_method="fake",
            text_len=100,
            scores=scores,
        )

    result = await run_eval_suite(
        template_id="invoice",
        limit=2,
        min_field_accuracy=0.5,
        extract_one=fake_extract,
    )
    assert result.doc_count == 2
    assert result.gate_passed is True
    assert result.field_accuracy == 1.0
    listed = eval_store.list_eval_runs()
    assert len(listed) == 1
    detail = eval_store.get_eval_run(result.eval_id)
    assert detail is not None
    assert detail["status"] == "completed"
    assert len(detail["items"]) == 2
    # Privacy: default view has no expected/actual
    assert "expected" not in detail["items"][0]["field_scores"][0]


@pytest.mark.asyncio
async def test_run_eval_suite_fails_gate():
    async def fake_extract(case: GoldenCase) -> DocResult:
        scores = [
            FieldScore(field=name, expected=exp, actual=None, ok=False)
            for name, exp in case.expected.items()
        ]
        return DocResult(
            path=Path(case.relative_path),
            template_id=case.template_id,
            text_method="fake",
            text_len=10,
            scores=scores,
        )

    result = await run_eval_suite(
        limit=1,
        min_field_accuracy=0.9,
        extract_one=fake_extract,
    )
    assert result.gate_passed is False
    assert result.status == "failed_gate"
