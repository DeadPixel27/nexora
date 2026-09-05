"""Observability — OTel disabled is a no-op."""

from app.services.observability.tracing import agent_step_span, reset_tracing_for_tests


def test_agent_step_span_noop_when_disabled(monkeypatch):
    reset_tracing_for_tests()
    monkeypatch.setattr("app.services.observability.tracing.settings.otel_enabled", False)
    with agent_step_span(agent_type="transform.field_extractor", run_id="r1", step_order=1) as span:
        assert span is None
