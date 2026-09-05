"""Outbound metering — email / Sheets monthly caps (separate from page pool)."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_repo
from app.config import settings
from app.main import app
from app.models.domain.email import EmailResult
from app.models.domain.pipeline import PlannedStep
from app.models.domain.run import RunResult, StepRunRecord
from app.models.domain.sheets import SheetsPushResult
from app.persistence.memory_repository import MemoryRepository
from app.services.analytics import events as analytics_events
from app.services.usage import metering
from app.services.usage.metering import (
    EMAIL_EVENT_TYPE,
    RAG_CHAT_EVENT_TYPE,
    SHEETS_EVENT_TYPE,
    UsageLimitError,
    check_outbound_allowed,
    get_user_usage_this_month,
    record_usage,
)
from tests.auth_helpers import override_current_user

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_outbound_state(monkeypatch):
    metering.reset_memory_usage()
    analytics_events.reset_memory_analytics()
    monkeypatch.setattr(
        "app.persistence.supabase_repository.is_supabase_configured",
        lambda: False,
    )
    monkeypatch.setattr(settings, "free_email_limit_monthly", 20)
    monkeypatch.setattr(settings, "free_sheets_limit_monthly", 20)
    monkeypatch.setattr(settings, "free_page_limit_monthly", 50)
    monkeypatch.setattr(settings, "free_rag_token_limit_monthly", 100_000)
    yield
    metering.reset_memory_usage()
    analytics_events.reset_memory_analytics()
    app.dependency_overrides.clear()


def _completed_run(*, user_id: str = "user-1") -> RunResult:
    return RunResult(
        run_id="run-1",
        upload_id="upload-1",
        task_description="Extract invoices",
        status="completed",
        steps=[
            StepRunRecord(
                step_order=1,
                agent_type="transform.field_extractor",
                status="completed",
            )
        ],
        planned_steps=[
            PlannedStep(
                step_order=1,
                agent_type="transform.field_extractor",
                config={"fields": ["vendor"]},
                reason="extract",
            )
        ],
        document_ids=["doc-1"],
        user_id=user_id,
        result={"rows": [{"vendor": "Acme", "amount": 100}]},
    )


@pytest.mark.asyncio
async def test_outbound_units_do_not_count_against_page_pool():
    await record_usage("user-1", 5, event_type="extraction")
    await record_usage("user-1", 1, event_type=EMAIL_EVENT_TYPE)
    await record_usage("user-1", 1, event_type=SHEETS_EVENT_TYPE)
    assert await get_user_usage_this_month("user-1") == 5


@pytest.mark.asyncio
async def test_check_outbound_allowed_raises_at_cap(monkeypatch):
    monkeypatch.setattr(settings, "free_email_limit_monthly", 2)
    await record_usage("user-1", 1, event_type=EMAIL_EVENT_TYPE)
    await record_usage("user-1", 1, event_type=EMAIL_EVENT_TYPE)
    with pytest.raises(UsageLimitError):
        await check_outbound_allowed(
            "user-1",
            EMAIL_EVENT_TYPE,
            settings.free_email_limit_monthly,
        )


@pytest.mark.asyncio
async def test_email_route_returns_429_when_over_cap(monkeypatch):
    monkeypatch.setattr(settings, "free_email_limit_monthly", 1)
    await record_usage("user-1", 1, event_type=EMAIL_EVENT_TYPE)

    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    send = AsyncMock(return_value=EmailResult(email_id="re_1", status="sent"))
    monkeypatch.setattr(
        "app.api.routes.email.send_results_email",
        send,
    )

    response = client.post(
        "/api/runs/run-1/email",
        json={"to_email": "team@example.com", "subject": "Results"},
    )
    assert response.status_code == 429
    assert "email" in response.json()["detail"].lower()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_sheets_route_returns_429_when_over_cap(monkeypatch):
    monkeypatch.setattr(settings, "free_sheets_limit_monthly", 1)
    await record_usage("user-1", 1, event_type=SHEETS_EVENT_TYPE)

    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    push = AsyncMock()
    monkeypatch.setattr(
        "app.api.routes.sheets.push_rows_to_sheet",
        push,
    )

    response = client.post(
        "/api/runs/run-1/sheets",
        json={
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc",
            "sheet_name": "Results",
        },
    )
    assert response.status_code == 429
    assert "sheets" in response.json()["detail"].lower()
    push.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_route_records_unit_on_success(monkeypatch):
    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    monkeypatch.setattr(
        "app.api.routes.email.send_results_email",
        AsyncMock(return_value=EmailResult(email_id="re_1", status="sent")),
    )

    response = client.post(
        "/api/runs/run-1/email",
        json={"to_email": "team@example.com", "subject": "Results"},
    )
    assert response.status_code == 200, response.text
    used = await metering.get_user_outbound_usage_this_month(
        "user-1", EMAIL_EVENT_TYPE
    )
    assert used == 1
    # Still not counted as pages
    assert await get_user_usage_this_month("user-1") == 0


@pytest.mark.asyncio
async def test_sheets_route_records_unit_on_success(monkeypatch):
    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    monkeypatch.setattr(
        "app.api.routes.sheets.push_rows_to_sheet",
        AsyncMock(
            return_value=SheetsPushResult(
                spreadsheet_id="ssid",
                sheet_name="Results",
                rows_written=1,
            )
        ),
    )

    response = client.post(
        "/api/runs/run-1/sheets",
        json={
            "spreadsheet_url": "https://docs.google.com/spreadsheets/d/abc",
            "sheet_name": "Results",
        },
    )
    assert response.status_code == 200, response.text
    used = await metering.get_user_outbound_usage_this_month(
        "user-1", SHEETS_EVENT_TYPE
    )
    assert used == 1


@pytest.mark.asyncio
async def test_auto_delivery_skips_email_when_over_cap(monkeypatch):
    from app.services.email.workflow_delivery import deliver_workflow_defaults

    monkeypatch.setattr(settings, "free_email_limit_monthly", 1)
    await record_usage("u1", 1, event_type=EMAIL_EVENT_TYPE)

    send = AsyncMock()
    with (
        patch(
            "app.services.email.workflow_delivery.get_workflow",
            return_value=type(
                "W",
                (),
                {"default_email": "team@example.com", "default_sheets_url": ""},
            )(),
        ),
        patch(
            "app.services.email.workflow_delivery.send_results_email",
            send,
        ),
    ):
        await deliver_workflow_defaults(
            RunResult(
                run_id="run_1",
                upload_id="up_1",
                task_description="Extract",
                status="completed",
                steps=[],
                document_ids=["d1"],
                workflow_id="wf_1",
                user_id="u1",
            ),
            [{"a": 1}],
        )

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_route_refunds_unit_when_send_fails(monkeypatch):
    from app.models.domain.email import EmailDeliveryError

    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    monkeypatch.setattr(
        "app.api.routes.email.send_results_email",
        AsyncMock(side_effect=EmailDeliveryError("provider down")),
    )

    response = client.post(
        "/api/runs/run-1/email",
        json={"to_email": "team@example.com", "subject": "Results"},
    )
    assert response.status_code == 502
    used = await metering.get_user_outbound_usage_this_month(
        "user-1", EMAIL_EVENT_TYPE
    )
    assert used == 0


@pytest.mark.asyncio
async def test_rag_tokens_do_not_count_against_page_pool():
    await record_usage("user-1", 5, event_type="extraction")
    await record_usage("user-1", 1200, event_type=RAG_CHAT_EVENT_TYPE)
    assert await get_user_usage_this_month("user-1") == 5
    used = await metering.get_user_outbound_usage_this_month(
        "user-1", RAG_CHAT_EVENT_TYPE
    )
    assert used == 1200


@pytest.mark.asyncio
async def test_rag_chat_route_returns_429_when_over_cap(monkeypatch):
    monkeypatch.setattr(settings, "free_rag_token_limit_monthly", 100)
    monkeypatch.setattr(settings, "rag_enabled", True)
    await record_usage("user-1", 100, event_type=RAG_CHAT_EVENT_TYPE)

    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    chat = AsyncMock()
    monkeypatch.setattr("app.services.rag.chat_over_run", chat)

    response = client.post(
        "/api/runs/run-1/chat",
        json={"question": "What is the vendor?"},
    )
    assert response.status_code == 429
    assert "ask-docs" in response.json()["detail"].lower()
    chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_rag_chat_route_records_actual_tokens(monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", True)

    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    monkeypatch.setattr(
        "app.services.rag.chat_over_run",
        AsyncMock(
            return_value={
                "answer": "Acme",
                "citations": [],
                "tokens_used": 42,
            }
        ),
    )

    response = client.post(
        "/api/runs/run-1/chat",
        json={"question": "What is the vendor?"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["tokens_used"] == 42
    used = await metering.get_user_outbound_usage_this_month(
        "user-1", RAG_CHAT_EVENT_TYPE
    )
    assert used == 42
    assert await get_user_usage_this_month("user-1") == 0


@pytest.mark.asyncio
async def test_rag_chat_route_refunds_on_failure(monkeypatch):
    monkeypatch.setattr(settings, "rag_enabled", True)

    repo = MemoryRepository()
    repo.save_run(_completed_run())
    app.dependency_overrides[get_repo] = lambda: repo
    override_current_user()

    monkeypatch.setattr(
        "app.services.rag.chat_over_run",
        AsyncMock(side_effect=RuntimeError("RAG is disabled")),
    )

    response = client.post(
        "/api/runs/run-1/chat",
        json={"question": "What is the vendor?"},
    )
    assert response.status_code == 503
    used = await metering.get_user_outbound_usage_this_month(
        "user-1", RAG_CHAT_EVENT_TYPE
    )
    assert used == 0
