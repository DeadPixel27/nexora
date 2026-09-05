"""Persist eval runs — Supabase when configured, else in-memory (tests/local)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger("evals")

_memory_runs: dict[str, dict[str, Any]] = {}
_memory_items: dict[str, list[dict[str, Any]]] = {}


def reset_memory_evals() -> None:
    """Clear in-memory eval store (tests only)."""
    _memory_runs.clear()
    _memory_items.clear()


def _supabase_client():
    from app.persistence.supabase_repository import (
        get_supabase_client,
        is_supabase_configured,
    )

    if not is_supabase_configured():
        return None
    try:
        return get_supabase_client()
    except Exception as e:
        logger.debug("Eval store skip supabase: %s", e)
        return None


def create_eval_run(
    *,
    suite: str,
    template_filter: Optional[str],
    model: Optional[str],
    metadata: Optional[dict[str, Any]] = None,
) -> str:
    eval_id = str(uuid4())
    row = {
        "id": eval_id,
        "status": "running",
        "suite": suite,
        "template_filter": template_filter,
        "model": model,
        "doc_count": 0,
        "field_checks": 0,
        "field_ok": 0,
        "docs_passed": 0,
        "field_accuracy": None,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    client = _supabase_client()
    if client is not None:
        client.table("eval_runs").insert(row).execute()
    else:
        _memory_runs[eval_id] = row
        _memory_items[eval_id] = []
    return eval_id


def complete_eval_run(
    eval_id: str,
    *,
    status: str,
    doc_count: int,
    field_checks: int,
    field_ok: int,
    docs_passed: int,
    field_accuracy: Optional[float],
    error_message: Optional[str] = None,
    items: Optional[list[dict[str, Any]]] = None,
) -> None:
    patch = {
        "status": status,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "doc_count": doc_count,
        "field_checks": field_checks,
        "field_ok": field_ok,
        "docs_passed": docs_passed,
        "field_accuracy": field_accuracy,
        "error_message": error_message,
    }
    client = _supabase_client()
    if client is not None:
        client.table("eval_runs").update(patch).eq("id", eval_id).execute()
        if items:
            rows = [{**item, "eval_run_id": eval_id} for item in items]
            client.table("eval_run_items").insert(rows).execute()
        return

    run = _memory_runs.get(eval_id)
    if run is None:
        return
    run.update(patch)
    if items:
        _memory_items[eval_id] = [
            {**item, "id": str(uuid4()), "eval_run_id": eval_id} for item in items
        ]


def list_eval_runs(limit: int = 20) -> list[dict[str, Any]]:
    client = _supabase_client()
    if client is not None:
        resp = (
            client.table("eval_runs")
            .select(
                "id,created_at,completed_at,status,suite,template_filter,model,"
                "doc_count,field_checks,field_ok,docs_passed,field_accuracy,error_message"
            )
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return list(resp.data or [])

    runs = sorted(
        _memory_runs.values(),
        key=lambda r: r.get("created_at") or "",
        reverse=True,
    )
    return [
        {
            k: r.get(k)
            for k in (
                "id",
                "created_at",
                "completed_at",
                "status",
                "suite",
                "template_filter",
                "model",
                "doc_count",
                "field_checks",
                "field_ok",
                "docs_passed",
                "field_accuracy",
                "error_message",
            )
        }
        for r in runs[:limit]
    ]


def get_eval_run(eval_id: str, *, include_field_details: bool = False) -> Optional[dict[str, Any]]:
    client = _supabase_client()
    if client is not None:
        resp = (
            client.table("eval_runs")
            .select("*")
            .eq("id", eval_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        run = dict(rows[0])
        items_resp = (
            client.table("eval_run_items")
            .select("*")
            .eq("eval_run_id", eval_id)
            .execute()
        )
        run["items"] = [
            _public_item(item, include_field_details=include_field_details)
            for item in (items_resp.data or [])
        ]
        return run

    run = _memory_runs.get(eval_id)
    if run is None:
        return None
    out = dict(run)
    out["items"] = [
        _public_item(item, include_field_details=include_field_details)
        for item in _memory_items.get(eval_id, [])
    ]
    return out


def _public_item(item: dict[str, Any], *, include_field_details: bool) -> dict[str, Any]:
    """Strip expected/actual values unless explicitly requested (privacy)."""
    scores = item.get("field_scores") or []
    if include_field_details:
        public_scores = scores
    else:
        public_scores = [
            {
                "field": s.get("field"),
                "ok": s.get("ok"),
                "note": s.get("note") or "",
            }
            for s in scores
            if isinstance(s, dict)
        ]
    return {
        "id": item.get("id"),
        "fixture_path": item.get("fixture_path"),
        "template_id": item.get("template_id"),
        "passed": item.get("passed"),
        "field_checks": item.get("field_checks"),
        "field_ok": item.get("field_ok"),
        "text_method": item.get("text_method"),
        "text_len": item.get("text_len"),
        "error_message": item.get("error_message"),
        "field_scores": public_scores,
    }
