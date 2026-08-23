"""Format final results as CSV or JSON."""

import csv
import io
import json
from typing import Any

from app.agents.core.base import StepHandler, StepResult
from app.agents.core.context import WorkflowContext
from app.agents.core.registry import register_agent


class FormatterHandler(StepHandler):
    async def execute(
        self,
        ctx: WorkflowContext,
        config: dict[str, Any],
    ) -> StepResult:
        rows = ctx.data.get("rows", [])
        filtered_rows = ctx.data.get("filtered_rows") or []
        if not rows and not filtered_rows:
            raise ValueError("No rows available — nothing to format")

        output_format = config.get("output_format", "json").lower()
        include_flags = config.get("include_flags", True)

        if output_format == "csv":
            content = _rows_to_csv(rows, include_flags) if rows else ""
        else:
            content = json.dumps(rows, indent=2, default=str)
            output_format = "json"

        filtered_count = len(filtered_rows)
        output = {
            "format": output_format,
            "content": content,
            "rows": rows,
            "row_count": len(rows),
            "filtered_count": filtered_count,
            "field_confidence": ctx.data.get("field_confidence") or {},
            "validation_warnings": ctx.data.get("validation_warnings") or {},
        }
        ctx.data["output"] = output

        return StepResult(
            output={
                "format": output_format,
                "row_count": len(rows),
                "filtered_count": filtered_count,
                "content_preview": content[:200],
                "documents_with_warnings": sum(
                    1
                    for warnings in (ctx.data.get("validation_warnings") or {}).values()
                    if warnings
                ),
            }
        )


def _rows_to_csv(rows: list[dict[str, Any]], include_flags: bool) -> str:
    base_keys: list[str] = []
    for row in rows:
        for key in row:
            if key == "flags":
                continue
            if key not in base_keys:
                base_keys.append(key)

    flag_keys: list[str] = []
    if include_flags:
        for row in rows:
            for flag in row.get("flags", {}):
                if flag not in flag_keys:
                    flag_keys.append(flag)

    fieldnames = base_keys + flag_keys
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")

    writer.writeheader()
    for row in rows:
        flat = {k: row.get(k) for k in base_keys}
        if include_flags:
            flat.update(row.get("flags", {}))
        writer.writerow(flat)

    return buffer.getvalue()


register_agent(
    "output.formatter",
    name="Formatter Agent",
    description="Compile final results into CSV, JSON, or a table.",
    example_config={
        "output_format": "csv",
        "include_flags": True,
    },
    handler=FormatterHandler(),
)
