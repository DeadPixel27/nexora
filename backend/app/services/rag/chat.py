"""Answer questions over a run's indexed document chunks."""

from __future__ import annotations

import logging
from typing import Any

from app.config import settings
from app.services.llm.openai_client import complete_json
from app.services.rag.embeddings import embed_texts
from app.services.rag.index import index_run_documents
from app.services.rag import store as rag_store

logger = logging.getLogger("rag")


async def _ensure_indexed(run_id: str) -> int:
    """
    If this run has no chunks yet, build them from cached document text.

    Needed when extraction was finished by a worker that did not have
    RAG_ENABLED (e.g. shared Redis / production worker).
    """
    from app.persistence import get_run

    run = get_run(run_id)
    if run is None:
        return 0
    docs = run.cached_documents or []
    if not docs:
        return 0
    return await index_run_documents(
        run_id=run_id,
        user_id=run.user_id,
        documents=docs,
    )


async def chat_over_run(
    *,
    run_id: str,
    question: str,
) -> dict[str, Any]:
    """
    Retrieve top-k chunks for ``run_id`` and answer with the chat model.

    Returns answer + citation metadata (filename / chunk_index). Does not
    echo full retrieved text in the API response by default — only short
    snippets for grounding UI.
    """
    if not settings.rag_enabled:
        raise RuntimeError(
            "RAG is disabled. Set RAG_ENABLED=true after applying migration 019."
        )

    q = (question or "").strip()
    if not q:
        raise ValueError("Question is required")

    query_emb = (await embed_texts([q]))[0]
    matches = rag_store.match_chunks(
        run_id=run_id,
        query_embedding=query_emb,
        match_count=settings.rag_top_k,
    )

    if not matches:
        try:
            n = await _ensure_indexed(run_id)
            if n:
                logger.info("Lazy-indexed %d chunks for run_id=%s", n, run_id)
                matches = rag_store.match_chunks(
                    run_id=run_id,
                    query_embedding=query_emb,
                    match_count=settings.rag_top_k,
                )
        except Exception:
            logger.exception("Lazy RAG index failed for run=%s", run_id)

    if not matches:
        return {
            "answer": (
                "No indexed document text found for this run. "
                "Wait for extraction to finish, then ask again."
            ),
            "citations": [],
        }

    context_blocks = []
    citations = []
    for i, m in enumerate(matches, start=1):
        content = str(m.get("content") or "")
        context_blocks.append(f"[{i}] ({m.get('filename') or 'doc'}):\n{content}")
        citations.append(
            {
                "filename": m.get("filename") or "",
                "document_id": m.get("document_id") or "",
                "chunk_index": m.get("chunk_index"),
                "similarity": m.get("similarity"),
                "snippet": content[:180] + ("…" if len(content) > 180 else ""),
            }
        )

    system = (
        "You answer questions using only the provided document excerpts. "
        "If the answer is not in the excerpts, say you do not know. "
        "Respond as JSON: {\"answer\": string}."
    )
    user = (
        "Document excerpts:\n\n"
        + "\n\n".join(context_blocks)
        + f"\n\nQuestion: {q}"
    )

    parsed = await complete_json(system, user)
    if not isinstance(parsed, dict):
        answer = str(parsed)
    else:
        answer = str(parsed.get("answer") or "").strip() or "I could not form an answer."

    return {"answer": answer, "citations": citations}
