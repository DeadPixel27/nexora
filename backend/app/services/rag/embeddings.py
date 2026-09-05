"""OpenAI embeddings for RAG — respects daily USD budget."""

from __future__ import annotations

import logging
from typing import Optional

from openai import AsyncOpenAI

from app.config import settings
from app.services.llm.openai_cost import (
    OpenAIUsageEstimate,
    check_openai_budget_allowed,
    estimate_usd,
    log_openai_usage_event,
    record_openai_usage,
)

logger = logging.getLogger("rag")

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not set")
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def embed_texts(texts: list[str]) -> tuple[list[list[float]], int]:
    """Embed strings with text-embedding-3-small (1536 dims).

    Returns ``(embeddings, prompt_tokens)``.
    """
    if not texts:
        return [], 0
    check_openai_budget_allowed()
    model = settings.rag_embedding_model
    client = _get_client()
    response = await client.embeddings.create(model=model, input=texts)
    # Approximate: embeddings API reports total_tokens on usage
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "total_tokens", 0) or 0)
    estimate = OpenAIUsageEstimate(
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=0,
        total_tokens=prompt_tokens,
        estimated_usd=estimate_usd(model, prompt_tokens, 0),
    )
    record_openai_usage(estimate)
    try:
        await log_openai_usage_event(estimate)
    except Exception:
        logger.debug("Embedding usage analytics log failed", exc_info=True)

    # Ensure order matches input
    by_index = sorted(response.data, key=lambda d: d.index)
    return [list(item.embedding) for item in by_index], prompt_tokens
