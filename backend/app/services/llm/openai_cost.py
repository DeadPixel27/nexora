"""
OpenAI usage estimates — token → USD and a process-local daily spend tracker.

Used for ops visibility (logs + analytics) and an optional daily USD budget
gate so a small OpenAI credit balance cannot be burned in one busy day.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from threading import Lock
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("llm")

# Published list prices ($ / 1M tokens). Update when OpenAI changes rates.
# Cached-input / batch discounts are ignored — estimates are slightly high.
_MODEL_PRICES_PER_M: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-2024-08-06": (2.50, 10.00),
    "gpt-4o-2024-11-20": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    # Embeddings: (input, output) — output unused; keep 0
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}

_DEFAULT_PRICES = (2.50, 10.00)  # assume gpt-4o-class if unknown


class OpenAIBudgetError(Exception):
    """Raised when estimated OpenAI spend hits the daily USD budget."""


@dataclass(frozen=True)
class OpenAIUsageEstimate:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_usd: float


_lock = Lock()
_spend_day: Optional[date] = None
_spend_usd: float = 0.0
_call_count: int = 0
_prompt_tokens: int = 0
_completion_tokens: int = 0


def reset_openai_spend_tracker() -> None:
    """Clear in-process spend totals (tests only)."""
    global _spend_day, _spend_usd, _call_count, _prompt_tokens, _completion_tokens
    with _lock:
        _spend_day = None
        _spend_usd = 0.0
        _call_count = 0
        _prompt_tokens = 0
        _completion_tokens = 0


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _ensure_day_locked() -> None:
    global _spend_day, _spend_usd, _call_count, _prompt_tokens, _completion_tokens
    today = _today_utc()
    if _spend_day != today:
        _spend_day = today
        _spend_usd = 0.0
        _call_count = 0
        _prompt_tokens = 0
        _completion_tokens = 0


def prices_for_model(model: str) -> tuple[float, float]:
    """Return (input_usd_per_1m, output_usd_per_1m) for a model name."""
    key = (model or "").strip().lower()
    if key in _MODEL_PRICES_PER_M:
        return _MODEL_PRICES_PER_M[key]
    # Prefix match: gpt-4o-mini-… before gpt-4o-…
    for name, prices in sorted(
        _MODEL_PRICES_PER_M.items(), key=lambda item: -len(item[0])
    ):
        if key.startswith(name):
            return prices
    return _DEFAULT_PRICES


def estimate_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> float:
    input_rate, output_rate = prices_for_model(model)
    return (prompt_tokens / 1_000_000) * input_rate + (
        completion_tokens / 1_000_000
    ) * output_rate


def estimate_from_response(model: str, response: Any) -> Optional[OpenAIUsageEstimate]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or (prompt + completion))
    return OpenAIUsageEstimate(
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        estimated_usd=estimate_usd(model, prompt, completion),
    )


def get_openai_spend_today() -> dict[str, Any]:
    """Snapshot of in-process estimated OpenAI spend for the UTC day."""
    with _lock:
        _ensure_day_locked()
        budget = float(settings.openai_daily_budget_usd)
        return {
            "day": _spend_day.isoformat() if _spend_day else _today_utc().isoformat(),
            "estimated_usd": round(_spend_usd, 6),
            "calls": _call_count,
            "prompt_tokens": _prompt_tokens,
            "completion_tokens": _completion_tokens,
            "budget_usd": budget,
            "budget_remaining_usd": (
                None if budget <= 0 else round(max(0.0, budget - _spend_usd), 6)
            ),
        }


def check_openai_budget_allowed() -> None:
    """Raise OpenAIBudgetError if today's estimated spend is at/over budget."""
    budget = float(settings.openai_daily_budget_usd)
    if budget <= 0:
        return
    with _lock:
        _ensure_day_locked()
        if _spend_usd >= budget:
            raise OpenAIBudgetError(
                f"OpenAI daily budget reached "
                f"(${_spend_usd:.4f} / ${budget:.2f}). Try again tomorrow."
            )


def record_openai_usage(estimate: OpenAIUsageEstimate) -> None:
    """Accumulate spend and emit a structured log line."""
    global _spend_usd, _call_count, _prompt_tokens, _completion_tokens
    with _lock:
        _ensure_day_locked()
        _spend_usd += estimate.estimated_usd
        _call_count += 1
        _prompt_tokens += estimate.prompt_tokens
        _completion_tokens += estimate.completion_tokens
        day_total = _spend_usd

    logger.info(
        "OpenAI usage — model=%s in=%d out=%d total=%d cost≈$%.4f day_total≈$%.4f",
        estimate.model,
        estimate.prompt_tokens,
        estimate.completion_tokens,
        estimate.total_tokens,
        estimate.estimated_usd,
        day_total,
    )


async def log_openai_usage_event(estimate: OpenAIUsageEstimate) -> None:
    """Best-effort analytics row for later spend review."""
    from app.logging_context import get_run_id, get_user_id
    from app.services.analytics.events import log_event

    uid = get_user_id()
    rid = get_run_id()
    await log_event(
        "openai_usage",
        user_id=None if uid in ("", "-") else uid,
        run_id=None if rid in ("", "-") else rid,
        metadata={
            "model": estimate.model,
            "prompt_tokens": estimate.prompt_tokens,
            "completion_tokens": estimate.completion_tokens,
            "total_tokens": estimate.total_tokens,
            "estimated_usd": round(estimate.estimated_usd, 6),
        },
    )
