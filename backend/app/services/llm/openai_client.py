"""
OpenAI LLM client — structured extraction with native JSON Schema mode.

Uses response_format type=json_schema for constrained output.
This guarantees valid JSON matching the provided schema — zero format errors.
"""

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional, Union

from openai import AsyncOpenAI, APIConnectionError, APIStatusError
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.services.llm.openai_cost import (
    OpenAIBudgetError,
    check_openai_budget_allowed,
    estimate_from_response,
    log_openai_usage_event,
    record_openai_usage,
)

logger = logging.getLogger("llm")

_client: Optional[AsyncOpenAI] = None


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, APIConnectionError):
        return True
    if isinstance(exc, APIStatusError):
        return exc.status_code in (500, 502, 503, 504, 429)
    return False


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Add it to backend/.env"
            )
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception(_is_retryable),
)
async def _create_completion(
    client: AsyncOpenAI,
    *,
    model_name: str,
    system_prompt: str,
    user_prompt: str,
    json_schema: Optional[dict[str, Any]] = None,
):
    response_format: dict[str, Any]
    if json_schema:
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "extraction_result",
                # Dynamic field values (arrays/objects) need non-strict mode.
                "strict": False,
                "schema": json_schema,
            },
        }
    else:
        response_format = {"type": "json_object"}

    return await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format=response_format,
        temperature=0,
        logprobs=True,
        top_logprobs=5,
    )


@dataclass
class LLMResult:
    """Result from an LLM call, including parsed JSON and token logprobs."""

    parsed: dict[str, Any]
    logprobs: Optional[list[Any]] = None  # Token-level logprobs for confidence scoring


async def complete_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: Optional[str] = None,
    json_schema: Optional[dict[str, Any]] = None,
    return_logprobs: bool = False,
    return_usage: bool = False,
) -> Union[dict[str, Any], LLMResult, tuple[dict[str, Any], int]]:
    """
    Call OpenAI and parse the response as JSON.

    If json_schema is provided, uses response_format type=json_schema
    for constrained output (guaranteed valid). Otherwise falls back to
    json_object mode.

    If return_logprobs=True, returns LLMResult with both parsed JSON and
    token logprobs (for confidence scoring). Otherwise returns dict.
    If return_usage=True, returns ``(parsed, total_tokens)`` (not combined
    with return_logprobs).
    """
    if return_logprobs and return_usage:
        raise ValueError("return_logprobs and return_usage cannot both be True")

    check_openai_budget_allowed()

    client = _get_client()
    primary = model or settings.openai_model
    candidates = [primary]
    for name in settings.openai_fallback_models_list:
        if name and name not in candidates:
            candidates.append(name)

    last_exc: Optional[BaseException] = None

    for index, model_name in enumerate(candidates):
        logger.info(
            "OpenAI request — model=%s%s",
            model_name,
            " (primary)" if index == 0 else " (fallback)",
        )
        try:
            response = await _create_completion(
                client,
                model_name=model_name,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                json_schema=json_schema,
            )
            estimate = estimate_from_response(model_name, response)
            if estimate is not None:
                record_openai_usage(estimate)
                try:
                    await log_openai_usage_event(estimate)
                except Exception:
                    logger.debug("OpenAI usage analytics log failed", exc_info=True)

            raw = response.choices[0].message.content or "{}"
            try:
                parsed = json.loads(raw)
                total_tokens = int(estimate.total_tokens) if estimate is not None else 0
                if return_logprobs:
                    token_logprobs = None
                    if response.choices[0].logprobs and response.choices[0].logprobs.content:
                        token_logprobs = response.choices[0].logprobs.content
                    return LLMResult(parsed=parsed, logprobs=token_logprobs)
                if return_usage:
                    return parsed, total_tokens
                return parsed
            except json.JSONDecodeError as e:
                last_exc = RuntimeError("LLM returned invalid JSON")
                last_exc.__cause__ = e
                logger.error(
                    "OpenAI model=%s returned invalid JSON (%d chars)",
                    model_name,
                    len(raw),
                )
        except OpenAIBudgetError:
            raise
        except BaseException as exc:
            last_exc = exc

        if index < len(candidates) - 1:
            logger.warning(
                "OpenAI failed on model=%s (%s) — trying fallback model=%s",
                model_name,
                last_exc,
                candidates[index + 1],
            )
            continue

        break

    assert last_exc is not None
    raise last_exc
