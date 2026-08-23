"""Deterministic normalization of extracted row fields (dates, amounts, etc.)."""

from typing import Any

from app.agents.core.base import StepHandler, StepResult
from app.agents.core.context import WorkflowContext
from app.agents.core.registry import register_agent
from app.services.extraction.normalize_values import (
    build_field_type_map,
    normalize_field_value,
)

_SKIP_KEYS = frozenset({"flags", "document_id", "filename"})


class NormalizeHandler(StepHandler):
    async def execute(
        self,
        ctx: WorkflowContext,
        config: dict[str, Any],
    ) -> StepResult:
        rows = ctx.data.get("rows", [])
        if not rows:
            raise ValueError("No rows available — run field_extractor first")

        field_names: list[str] = []
        for row in rows:
            for key in row:
                if key not in _SKIP_KEYS and key not in field_names:
                    field_names.append(key)

        field_types = build_field_type_map(
            field_names,
            date_fields=config.get("date_fields"),
            amount_fields=config.get("amount_fields"),
            currency_fields=config.get("currency_fields"),
            phone_fields=config.get("phone_fields"),
        )

        fields_touched = 0
        values_changed = 0
        for row in rows:
            for key in list(row.keys()):
                if key in _SKIP_KEYS:
                    continue
                if isinstance(row[key], (list, dict)):
                    continue
                before = row[key]
                after = normalize_field_value(key, before, field_types=field_types)
                fields_touched += 1
                if after != before:
                    row[key] = after
                    values_changed += 1

        ctx.data["rows"] = rows
        return StepResult(
            output={
                "fields_touched": fields_touched,
                "values_changed": values_changed,
            }
        )


register_agent(
    "transform.normalize",
    name="Normalize Agent",
    description=(
        "Deterministically clean extracted values: dates → YYYY-MM-DD, "
        "amounts → plain numbers, currency → ISO codes, phones → digits. "
        "Run after field_extractor and before rules."
    ),
    example_config={
        "date_fields": ["invoice_date", "due_date"],
        "amount_fields": ["total_amount", "tax_amount"],
        "currency_fields": ["currency"],
    },
    handler=NormalizeHandler(),
)
