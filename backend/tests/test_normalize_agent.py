"""Tests for transform.normalize and normalize_values helpers."""

import pytest

import app.agents.handlers  # noqa: F401
from app.agents.core.context import WorkflowContext
from app.agents.core.registry import get_agent_catalog, get_handler
from app.services.extraction.normalize_values import (
    normalize_amount,
    normalize_currency,
    normalize_date,
    normalize_phone,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("$1,234.56", 1234.56),
        ("€1.234,56", 1234.56),
        ("₹1,50,000", 150000.0),
        ("1,50,000.50", 150000.5),
        ("1234", 1234.0),
        ("", None),
        (None, None),
        (99, 99.0),
    ],
)
def test_normalize_amount(raw, expected):
    assert normalize_amount(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2024-03-15", "2024-03-15"),
        ("15/03/2024", "2024-03-15"),
        ("March 15, 2024", "2024-03-15"),
        ("15th Mar '24", "2024-03-15"),
        ("", None),
        ("not-a-date", "not-a-date"),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_normalize_currency_and_phone():
    assert normalize_currency("$") == "USD"
    assert normalize_currency("₹") == "INR"
    assert normalize_currency("eur") == "EUR"
    assert normalize_phone("+1 (555) 123-4567") == "+15551234567"
    assert normalize_phone("(555) 123-4567") == "5551234567"


@pytest.mark.asyncio
async def test_normalize_agent_mutates_rows():
    handler = get_handler("transform.normalize")
    ctx = WorkflowContext(
        upload_id="u1",
        data={
            "rows": [
                {
                    "document_id": "d1",
                    "total_amount": "$1,234.56",
                    "invoice_date": "15/03/2024",
                    "currency": "₹",
                    "vendor_name": "  Acme  ",
                    "line_items": [{"amount": 1}],
                }
            ]
        },
    )
    result = await handler.execute(ctx, {})
    row = ctx.data["rows"][0]
    assert row["total_amount"] == 1234.56
    assert row["invoice_date"] == "2024-03-15"
    assert row["currency"] == "INR"
    assert row["vendor_name"] == "Acme"
    assert row["line_items"] == [{"amount": 1}]
    assert result.output["values_changed"] >= 4


def test_normalize_agent_registered():
    catalog = get_agent_catalog()
    assert "transform.normalize" in catalog
