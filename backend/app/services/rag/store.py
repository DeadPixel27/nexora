"""Persist and search document chunks (PGVector via Supabase)."""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import uuid4

logger = logging.getLogger("rag")

_memory_chunks: dict[str, list[dict[str, Any]]] = {}


def reset_memory_chunks() -> None:
    _memory_chunks.clear()


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
        logger.debug("RAG store skip supabase: %s", e)
        return None


def replace_run_chunks(
    *,
    run_id: str,
    user_id: Optional[str],
    rows: list[dict[str, Any]],
) -> int:
    """Replace all chunks for a run. Each row needs document_id, filename, chunk_index, content, embedding."""
    client = _supabase_client()
    if client is not None:
        client.table("document_chunks").delete().eq("run_id", run_id).execute()
        if not rows:
            return 0
        payload = [
            {
                "run_id": run_id,
                "user_id": user_id,
                "document_id": r["document_id"],
                "filename": r.get("filename") or "",
                "chunk_index": r["chunk_index"],
                "content": r["content"],
                "embedding": r["embedding"],
            }
            for r in rows
        ]
        client.table("document_chunks").insert(payload).execute()
        return len(payload)

    _memory_chunks[run_id] = [
        {
            "id": str(uuid4()),
            "run_id": run_id,
            "user_id": user_id,
            "document_id": r["document_id"],
            "filename": r.get("filename") or "",
            "chunk_index": r["chunk_index"],
            "content": r["content"],
            "embedding": r["embedding"],
        }
        for r in rows
    ]
    return len(rows)


def match_chunks(
    *,
    run_id: str,
    query_embedding: list[float],
    match_count: int = 6,
) -> list[dict[str, Any]]:
    client = _supabase_client()
    if client is not None:
        try:
            resp = client.rpc(
                "match_document_chunks",
                {
                    "query_embedding": query_embedding,
                    "match_run_id": run_id,
                    "match_count": match_count,
                },
            ).execute()
            return list(resp.data or [])
        except Exception:
            logger.exception("match_document_chunks RPC failed")
            return []

    chunks = _memory_chunks.get(run_id) or []
    scored: list[tuple[float, dict[str, Any]]] = []
    for chunk in chunks:
        emb = chunk.get("embedding") or []
        if not emb or len(emb) != len(query_embedding):
            continue
        # Cosine similarity
        dot = sum(a * b for a, b in zip(emb, query_embedding))
        na = sum(a * a for a in emb) ** 0.5
        nb = sum(b * b for b in query_embedding) ** 0.5
        sim = (dot / (na * nb)) if na and nb else 0.0
        scored.append(
            (
                sim,
                {
                    "id": chunk["id"],
                    "document_id": chunk["document_id"],
                    "filename": chunk["filename"],
                    "chunk_index": chunk["chunk_index"],
                    "content": chunk["content"],
                    "similarity": sim,
                },
            )
        )
    scored.sort(key=lambda x: -x[0])
    return [row for _, row in scored[:match_count]]
