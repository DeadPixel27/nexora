"""Apply flag/filter/set rules to extracted rows."""

from datetime import date, datetime
from typing import Any

from app.agents.core.base import StepHandler, StepResult
from app.agents.core.context import WorkflowContext
from app.agents.core.registry import register_agent
from app.services.extraction.normalize_values import normalize_amount


def _op_contains(a: Any, b: Any) -> bool:
    if a is None:
        return False
    return str(b).lower() in str(a).lower()


def _op_exists(a: Any, _b: Any) -> bool:
    if a is None:
        return False
    if isinstance(a, str) and not a.strip():
        return False
    return True


def _op_not_exists(a: Any, b: Any) -> bool:
    return not _op_exists(a, b)


_OPERATORS = {
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "neq": lambda a, b: a != b,
    "contains": _op_contains,
    "exists": _op_exists,
    "not_exists": _op_not_exists,
}


class RulesHandler(StepHandler):
    async def execute(
        self,
        ctx: WorkflowContext,
        config: dict[str, Any],
    ) -> StepResult:
        rules = config.get("rules", [])
        rows = ctx.data.get("rows", [])
        if not rows:
            raise ValueError("No rows available — run field_extractor first")

        flagged_count = 0
        fields_set = 0
        rows_filtered = 0
        kept: list[dict[str, Any]] = []
        filtered: list[dict[str, Any]] = list(ctx.data.get("filtered_rows") or [])

        for row in rows:
            flags: dict[str, bool] = dict(row.get("flags") or {})
            drop_row = False

            for rule in rules:
                field = rule.get("field")
                operator = rule.get("operator", "gt")
                value = rule.get("value")
                action = str(rule.get("action") or "flag").lower()
                flag_name = rule.get("flag_name", f"{field}_{operator}")

                field_value = row.get(field) if field else None

                # exists / not_exists may run when field is missing
                if operator not in ("exists", "not_exists") and field_value is None:
                    continue

                try:
                    compare_fn = _OPERATORS.get(operator)
                    if compare_fn is None:
                        continue
                    resolved_value = _resolve_compare_value(value)
                    resolved_field = _resolve_field_value(field_value)
                    if operator in ("gt", "gte", "lt", "lte"):
                        resolved_field, resolved_value = _coerce_numeric_pair(
                            resolved_field, resolved_value
                        )
                    if not compare_fn(resolved_field, resolved_value):
                        continue
                except TypeError:
                    continue

                if action == "filter":
                    drop_row = True
                    break
                if action == "set":
                    set_field = rule.get("set_field")
                    if set_field:
                        row[set_field] = rule.get("set_value")
                        fields_set += 1
                    continue
                # default: flag
                flags[flag_name] = True
                flagged_count += 1

            row["flags"] = flags
            if drop_row:
                filtered.append(row)
                rows_filtered += 1
            else:
                kept.append(row)

        ctx.data["rows"] = kept
        ctx.data["filtered_rows"] = filtered
        return StepResult(
            output={
                "rules_applied": len(rules),
                "flags_raised": flagged_count,
                "rows_filtered": rows_filtered,
                "fields_set": fields_set,
            }
        )


def _resolve_compare_value(value: Any) -> Any:
    if value == "today":
        return date.today().isoformat()
    return value


def _resolve_field_value(value: Any) -> Any:
    if isinstance(value, str) and len(value) >= 10 and value[4] == "-" and value[7] == "-":
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date().isoformat()
        except ValueError:
            return value
    return value


def _coerce_numeric_pair(field_value: Any, compare_value: Any) -> tuple[Any, Any]:
    """Best-effort numeric coerce so '75000' vs 50000 works after normalize."""
    if isinstance(field_value, str):
        parsed = normalize_amount(field_value)
        if isinstance(parsed, (int, float)):
            field_value = parsed
    if isinstance(compare_value, str) and compare_value != "today":
        parsed = normalize_amount(compare_value)
        if isinstance(parsed, (int, float)):
            compare_value = parsed
    return field_value, compare_value


register_agent(
    "transform.rules",
    name="Rules Agent",
    description=(
        "Apply conditions to extracted rows after normalize. "
        "Actions: flag (default), filter (drop matching rows), set (write a field). "
        "Operators: gt, gte, lt, lte, eq, ne, contains, exists, not_exists. "
        "Example: flag when amount exceeds a threshold; filter unpaid; set status=overdue."
    ),
    example_config={
        "rules": [
            {
                "field": "amount",
                "operator": "gt",
                "value": 50000,
                "action": "flag",
                "flag_name": "high_value",
            },
            {
                "field": "status",
                "operator": "eq",
                "value": "unpaid",
                "action": "filter",
            },
            {
                "field": "due_date",
                "operator": "lt",
                "value": "today",
                "action": "set",
                "set_field": "payment_status",
                "set_value": "overdue",
            },
        ]
    },
    handler=RulesHandler(),
)
