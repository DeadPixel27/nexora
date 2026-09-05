"""OpenTelemetry step tracing — metadata only (no document / field payloads)."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from app.config import settings

logger = logging.getLogger("observability")

_tracer = None
_initialized = False


def reset_tracing_for_tests() -> None:
    global _tracer, _initialized
    _tracer = None
    _initialized = False


def _init_tracer() -> Any:
    global _tracer, _initialized
    if _initialized:
        return _tracer
    _initialized = True

    if not settings.otel_enabled:
        _tracer = None
        return None

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        logger.warning("OTEL_ENABLED but opentelemetry packages not installed")
        _tracer = None
        return None

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)

    endpoint = (settings.otel_exporter_otlp_endpoint or "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
            )
        except Exception:
            logger.exception("Failed to configure OTLP exporter; using console")
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    elif settings.app_env.strip().lower() in {"development", "dev", "test"}:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("nexora.pipeline")
    logger.info(
        "OpenTelemetry tracing enabled service=%s otlp=%s",
        settings.otel_service_name,
        bool(endpoint),
    )
    return _tracer


@contextmanager
def agent_step_span(
    *,
    agent_type: str,
    run_id: str,
    step_order: int,
) -> Iterator[Any]:
    """
    Span around one DAG step. Attributes are metadata-only.

    Never attach OCR text, prompts, or extracted field values.
    """
    tracer = _init_tracer()
    if tracer is None:
        yield None
        return

    from opentelemetry import trace

    with tracer.start_as_current_span(f"agent.{agent_type}") as span:
        span.set_attribute("nexora.run_id", run_id)
        span.set_attribute("nexora.agent_type", agent_type)
        span.set_attribute("nexora.step_order", step_order)
        try:
            yield span
            span.set_attribute("nexora.status", "completed")
        except Exception as exc:
            span.set_attribute("nexora.status", "failed")
            span.set_attribute("nexora.error_type", type(exc).__name__)
            span.set_status(trace.Status(trace.StatusCode.ERROR, type(exc).__name__))
            raise


def mark_span_skipped(span: Any, reason: str = "cached_document_text") -> None:
    if span is None:
        return
    try:
        span.set_attribute("nexora.status", "skipped")
        span.set_attribute("nexora.skip_reason", reason)
    except Exception:
        pass
