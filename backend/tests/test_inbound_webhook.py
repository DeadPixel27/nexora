"""Inbound Mailgun webhook — HMAC, timestamp skew, replay token cache."""

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_inbound_email_service, get_workflow_service
from app.api.routes import inbound as inbound_route
from app.config import settings
from app.main import app
from app.models.domain.run import RunResult

client = TestClient(app)

SECRET = "test-mailgun-signing-key"


@pytest.fixture(autouse=True)
def _inbound_test_env(monkeypatch):
    monkeypatch.setattr(settings, "inbound_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "inbound_webhook_max_age_seconds", 300)
    monkeypatch.setattr(settings, "inbound_webhook_token_ttl_seconds", 900)
    inbound_route.reset_seen_tokens()
    yield
    inbound_route.reset_seen_tokens()
    app.dependency_overrides.clear()


def _sign(timestamp: str, token: str) -> str:
    return hmac.new(
        key=SECRET.encode(),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _form(*, token: str = "tok-1", timestamp: str | None = None, signature: str | None = None):
    ts = timestamp if timestamp is not None else str(int(time.time()))
    sig = signature if signature is not None else _sign(ts, token)
    return {
        "token": token,
        "timestamp": ts,
        "signature": sig,
        "recipient": "flow-abc@ingest.nexora.app",
        "sender": "sender@example.com",
    }


def _mock_pipeline(monkeypatch):
    process = AsyncMock(return_value=("up-1", "wf-1", "sender@example.com", "user-1"))
    inbound_svc = MagicMock()
    inbound_svc.process_inbound = process

    run = RunResult(
        run_id="run-1",
        upload_id="up-1",
        task_description="Inbound",
        status="running",
        steps=[],
        document_ids=["d1"],
        workflow_id="wf-1",
        user_id="user-1",
    )
    workflows = MagicMock()
    workflows.start_workflow_run = AsyncMock(return_value=run)

    monkeypatch.setattr(
        "app.api.routes.inbound.enforce_upload_usage",
        AsyncMock(return_value=1),
    )
    monkeypatch.setattr(
        "app.api.routes.inbound.charge_run_pages_or_abandon",
        AsyncMock(),
    )
    monkeypatch.setattr(
        "app.api.routes.inbound.schedule_run",
        AsyncMock(),
    )

    app.dependency_overrides[get_inbound_email_service] = lambda: inbound_svc
    app.dependency_overrides[get_workflow_service] = lambda: workflows
    return process


def test_valid_signature_processes(monkeypatch):
    process = _mock_pipeline(monkeypatch)
    response = client.post("/api/inbound/email", data=_form())
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processing"
    assert response.json()["run_id"] == "run-1"
    process.assert_awaited_once()


def test_stale_timestamp_rejected(monkeypatch):
    process = _mock_pipeline(monkeypatch)
    stale = str(int(time.time()) - 301)
    response = client.post(
        "/api/inbound/email",
        data=_form(timestamp=stale),
    )
    assert response.status_code == 403
    assert "expired" in response.json()["detail"].lower()
    process.assert_not_awaited()


def test_future_timestamp_rejected(monkeypatch):
    process = _mock_pipeline(monkeypatch)
    future = str(int(time.time()) + 301)
    response = client.post(
        "/api/inbound/email",
        data=_form(timestamp=future),
    )
    assert response.status_code == 403
    assert "future" in response.json()["detail"].lower()
    process.assert_not_awaited()


def test_duplicate_token_returns_200_without_reprocess(monkeypatch):
    process = _mock_pipeline(monkeypatch)
    data = _form(token="same-token")

    first = client.post("/api/inbound/email", data=data)
    assert first.status_code == 200
    assert first.json()["status"] == "processing"

    second = client.post("/api/inbound/email", data=data)
    assert second.status_code == 200
    assert second.json()["status"] == "duplicate"
    process.assert_awaited_once()


def test_bad_signature_rejected(monkeypatch):
    process = _mock_pipeline(monkeypatch)
    response = client.post(
        "/api/inbound/email",
        data=_form(signature="deadbeef"),
    )
    assert response.status_code == 403
    process.assert_not_awaited()
