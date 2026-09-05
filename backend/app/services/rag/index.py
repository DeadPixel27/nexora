"""Index cached run documents into PGVector for RAG chat."""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.config import settings
from app.services.rag.chunking import chunk_text
from app.services.rag.embeddings import embed_texts
from app.services.rag import store as rag_store

logger = logging.getLogger("rag")


async def index_run_documents(
    *,
    run_id: str,
    user_id: Optional[str],
    documents: list[dict[str, Any]],
) -> int:
    """
    Chunk + embed document text for a completed run.

    No-ops when RAG is disabled. Failures are logged and swallowed so
    extraction success is never blocked by indexing.
    """
    if not settings.rag_enabled:
        return 0

    try:
        chunks = []
        for doc in documents:
            text = doc.get("text") or ""
            if not str(text).strip():
                continue
            chunks.extend(
                chunk_text(
                    str(text),
                    document_id=str(doc.get("document_id") or ""),
                    filename=str(doc.get("filename") or ""),
                    chunk_size=settings.rag_chunk_size,
                    overlap=settings.rag_chunk_overlap,
                )
            )

        if not chunks:
            rag_store.replace_run_chunks(run_id=run_id, user_id=user_id, rows=[])
            return 0

        # Batch embeddings (cap batch size for API limits)
        embeddings: list[list[float]] = []
        batch_size = 32
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            embeddings.extend(await embed_texts([c.content for c in batch]))

        rows = [
            {
                "document_id": c.document_id,
                "filename": c.filename,
                "chunk_index": c.chunk_index,
                "content": c.content,
                "embedding": emb,
            }
            for c, emb in zip(chunks, embeddings)
        ]
        count = rag_store.replace_run_chunks(
            run_id=run_id, user_id=user_id, rows=rows
        )
        logger.info(
            "RAG indexed run_id=%s chunks=%d user=%s",
            run_id,
            count,
            user_id,
        )
        return count
    except Exception:
        logger.exception("RAG index failed for run=%s", run_id)
        return 0
