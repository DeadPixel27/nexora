"""Tests for transform.rules (Rules Agent)."""

import json

import pytest

import app.agents.handlers  # noqa: F401 — register agents
from app.agents.core.context import WorkflowContext
from app.agents.core.registry import get_agent_catalog, get_handler


def _ctx_with_rows(rows: list[dict]) -> WorkflowContext:
    return WorkflowContext(
        upload_id="test-upload",
        task_description="flag high amounts",
        data={"rows": rows},
    )


HIGH_VALUE_RULE = {
    "field": "amount",
    "operator": "gt",
    "value": 50000,
    "flag_name": "high_value",
}


@pytest.mark.asyncio
async def test_flags_row_when_amount_exceeds_threshold():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"vendor": "Acme Corp", "amount": 75000, "date": "2026-08-03"}])

    result = await handler.execute(ctx, {"rules": [HIGH_VALUE_RULE]})

    assert result.output["rules_applied"] == 1
    assert result.output["flags_raised"] == 1
    assert result.output["rows_filtered"] == 0
    assert ctx.data["rows"][0]["flags"] == {"high_value": True}


@pytest.mark.asyncio
async def test_does_not_flag_when_amount_below_threshold():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"vendor": "Small Co", "amount": 12000}])

    result = await handler.execute(ctx, {"rules": [HIGH_VALUE_RULE]})

    assert result.output["flags_raised"] == 0
    assert ctx.data["rows"][0]["flags"] == {}


@pytest.mark.asyncio
async def test_skips_rule_when_field_missing():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"vendor": "No Amount Inc"}])

    result = await handler.execute(ctx, {"rules": [HIGH_VALUE_RULE]})

    assert result.output["flags_raised"] == 0
    assert ctx.data["rows"][0]["flags"] == {}


@pytest.mark.asyncio
async def test_raises_when_no_rows_available():
    handler = get_handler("transform.rules")
    ctx = WorkflowContext(upload_id="test-upload", data={})

    with pytest.raises(ValueError, match="No rows available"):
        await handler.execute(ctx, {"rules": [HIGH_VALUE_RULE]})


@pytest.mark.asyncio
async def test_multiple_rules_on_same_row():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"amount": 75000, "status": "pending"}])

    result = await handler.execute(
        ctx,
        {
            "rules": [
                HIGH_VALUE_RULE,
                {
                    "field": "status",
                    "operator": "eq",
                    "value": "pending",
                    "flag_name": "needs_review",
                },
            ]
        },
    )

    assert result.output["rules_applied"] == 2
    assert result.output["flags_raised"] == 2
    assert ctx.data["rows"][0]["flags"] == {
        "high_value": True,
        "needs_review": True,
    }


@pytest.mark.asyncio
async def test_type_mismatch_does_not_crash():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"amount": "not-a-number"}])

    result = await handler.execute(ctx, {"rules": [HIGH_VALUE_RULE]})

    assert result.output["flags_raised"] == 0
    assert ctx.data["rows"][0]["flags"] == {}


@pytest.mark.asyncio
async def test_string_amount_coerced_for_comparison():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"amount": "75000"}])

    result = await handler.execute(ctx, {"rules": [HIGH_VALUE_RULE]})

    assert result.output["flags_raised"] == 1


@pytest.mark.asyncio
async def test_filter_action_removes_rows():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows(
        [
            {"vendor": "A", "status": "unpaid", "amount": 10},
            {"vendor": "B", "status": "paid", "amount": 20},
        ]
    )

    result = await handler.execute(
        ctx,
        {
            "rules": [
                {
                    "field": "status",
                    "operator": "eq",
                    "value": "unpaid",
                    "action": "filter",
                }
            ]
        },
    )

    assert result.output["rows_filtered"] == 1
    assert len(ctx.data["rows"]) == 1
    assert ctx.data["rows"][0]["vendor"] == "B"
    assert len(ctx.data["filtered_rows"]) == 1


@pytest.mark.asyncio
async def test_set_action_writes_field():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows([{"due_date": "2020-01-01", "amount": 1}])

    result = await handler.execute(
        ctx,
        {
            "rules": [
                {
                    "field": "due_date",
                    "operator": "lt",
                    "value": "today",
                    "action": "set",
                    "set_field": "payment_status",
                    "set_value": "overdue",
                }
            ]
        },
    )

    assert result.output["fields_set"] == 1
    assert ctx.data["rows"][0]["payment_status"] == "overdue"


@pytest.mark.asyncio
async def test_contains_and_exists_operators():
    handler = get_handler("transform.rules")
    ctx = _ctx_with_rows(
        [
            {"vendor": "Acme Corp", "notes": "rush"},
            {"vendor": "Beta", "notes": None},
        ]
    )

    await handler.execute(
        ctx,
        {
            "rules": [
                {
                    "field": "vendor",
                    "operator": "contains",
                    "value": "acme",
                    "flag_name": "is_acme",
                },
                {
                    "field": "notes",
                    "operator": "exists",
                    "flag_name": "has_notes",
                },
            ]
        },
    )

    assert ctx.data["rows"][0]["flags"].get("is_acme") is True
    assert ctx.data["rows"][0]["flags"].get("has_notes") is True
    assert ctx.data["rows"][1]["flags"].get("is_acme") is None
    assert not ctx.data["rows"][1]["flags"].get("has_notes")


@pytest.mark.asyncio
async def test_rules_output_flows_to_formatter():
    """Rules flags should appear in formatter JSON output."""
    rules = get_handler("transform.rules")
    formatter = get_handler("output.formatter")
    ctx = _ctx_with_rows([{"vendor": "Acme Corp", "amount": 75000}])

    await rules.execute(ctx, {"rules": [HIGH_VALUE_RULE]})
    await formatter.execute(ctx, {"output_format": "json"})

    parsed = json.loads(ctx.data["output"]["content"])
    assert parsed[0]["flags"] == {"high_value": True}
    assert parsed[0]["amount"] == 75000
    assert ctx.data["output"]["filtered_count"] == 0


def test_rules_agent_registered_in_catalog():
    catalog = get_agent_catalog()
    assert "transform.rules" in catalog
    assert catalog["transform.rules"]["name"] == "Rules Agent"
    assert "rules" in catalog["transform.rules"]["example_config"]
