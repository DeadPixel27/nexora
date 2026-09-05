"""Phase 2 smoke tests — usage metering, waitlist, analytics, caps."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.models.domain.run import RunResult
from app.persistence.memory_repository import MemoryRepository
from app.services.analytics import events as analytics_events
from app.services.usage import metering
from app.services.usage.metering import (
    GlobalCapError,
    RefineLimitError,
    UsageLimitError,
    check_refine_allowed,
    check_usage_allowed,
    get_usage_summary,
    record_usage,
)
from tests.auth_helpers import auth_user, override_current_user

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_phase2_state(monkeypatch):
    metering.reset_memory_usage()
    analytics_events.reset_memory_analytics()
    from app.api.routes import waitlist as waitlist_route

    waitlist_route.reset_memory_waitlist()
    # Force in-memory path even if local .env has Supabase credentials
    monkeypatch.setattr(
        "app.persistence.supabase_repository.is_supabase_configured",
        lambda: False,
    )
    monkeypatch.setattr(settings, "free_page_limit_monthly", 50)
    monkeypatch.setattr(settings, "global_daily_page_limit", 500)
    monkeypatch.setattr(settings, "max_refines_per_run", 10)
    monkeypatch.setattr(settings, "rate_limit_waitlist", "100/minute")
    yield
    metering.reset_memory_usage()
    analytics_events.reset_memory_analytics()
    waitlist_route.reset_memory_waitlist()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_record_and_summarize_usage():
    await record_usage("user-1", 3, run_id="run-a")
    await record_usage("user-1", 2, run_id="run-b")
    summary = await get_usage_summary("user-1")
    assert summary["pages_used"] == 5
    assert summary["pages_limit"] == 50
    assert summary["emails_used"] == 0
    assert summary["emails_limit"] == settings.free_email_limit_monthly
    assert summary["sheets_used"] == 0
    assert summary["sheets_limit"] == settings.free_sheets_limit_monthly
    assert summary["rag_tokens_used"] == 0
    assert summary["rag_tokens_limit"] == settings.free_rag_token_limit_monthly
    assert summary["resets_at"]


@pytest.mark.asyncio
async def test_monthly_cap_raises_usage_limit_error(monkeypatch):
    monkeypatch.setattr(settings, "free_page_limit_monthly", 5)
    await record_usage("user-1", 5)
    with pytest.raises(UsageLimitError):
        await check_usage_allowed("user-1", 1)


@pytest.mark.asyncio
async def test_global_cap_raises_503_style_error(monkeypatch):
    monkeypatch.setattr(settings, "global_daily_page_limit", 4)
    await record_usage("user-a", 2)
    await record_usage("user-b", 2)
    with pytest.raises(GlobalCapError):
        await check_usage_allowed("user-c", 1)


@pytest.mark.asyncio
async def test_refine_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_refines_per_run", 2)
    repo = MemoryRepository()
    parent = "parent-run"
    repo.save_run(
        RunResult(
            run_id="child-1",
            upload_id="u1",
            task_description="",
            status="completed",
            steps=[],
            parent_run_id=parent,
        )
    )
    repo.save_run(
        RunResult(
            run_id="child-2",
            upload_id="u1",
            task_description="",
            status="completed",
            steps=[],
            parent_run_id=parent,
        )
    )
    monkeypatch.setattr("app.persistence.get_repository", lambda: repo)

    with pytest.raises(RefineLimitError):
        await check_refine_allowed(parent)


def test_waitlist_public_and_dedupes():
    first = client.post(
        "/api/waitlist",
        json={"email": "pro@example.com", "name": "Pro", "source": "normal"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["already_joined"] is False

    second = client.post(
        "/api/waitlist",
        json={"email": "pro@example.com", "name": "Pro"},
    )
    assert second.status_code == 200
    assert second.json()["already_joined"] is True


def test_waitlist_stores_optional_feedback(monkeypatch):
    from app.api.routes import waitlist as waitlist_route

    waitlist_route.reset_memory_waitlist()
    monkeypatch.setattr(settings, "rate_limit_waitlist", "100/minute")
    monkeypatch.setattr(
        "app.api.routes.waitlist._supabase_client",
        lambda: None,
    )

    response = client.post(
        "/api/waitlist",
        json={
            "email": "feedback@example.com",
            "name": "Ada",
            "source": "pages_exhausted",
            "feedback": "  Need higher limits for invoices  ",
        },
    )
    assert response.status_code == 200
    entry = waitlist_route._memory_waitlist[-1]
    assert entry["feedback"] == "Need higher limits for invoices"

    again = client.post(
        "/api/waitlist",
        json={
            "email": "feedback@example.com",
            "feedback": "Also want inbound email",
        },
    )
    assert again.status_code == 200
    assert again.json()["already_joined"] is True
    assert entry["feedback"] == "Also want inbound email"


def test_waitlist_rejects_oversized_feedback(monkeypatch):
    from app.api.routes import waitlist as waitlist_route

    waitlist_route.reset_memory_waitlist()
    monkeypatch.setattr(settings, "rate_limit_waitlist", "100/minute")
    monkeypatch.setattr(
        "app.api.routes.waitlist._supabase_client",
        lambda: None,
    )

    too_long = "x" * 1001
    response = client.post(
        "/api/waitlist",
        json={"email": "long@example.com", "feedback": too_long},
    )
    assert response.status_code == 422


def test_waitlist_normalizes_legacy_and_feature_sources(monkeypatch):
    from app.api.routes import waitlist as waitlist_route

    waitlist_route.reset_memory_waitlist()
    monkeypatch.setattr(settings, "rate_limit_waitlist", "100/minute")
    monkeypatch.setattr(
        "app.api.routes.waitlist._supabase_client",
        lambda: None,
    )

    legacy = client.post(
        "/api/waitlist",
        json={"email": "legacy@example.com", "source": "pricing_page"},
    )
    assert legacy.status_code == 200
    assert waitlist_route._memory_waitlist[-1]["source"] == "normal"

    inbound = client.post(
        "/api/waitlist",
        json={"email": "inbound@example.com", "source": "inbound_email"},
    )
    assert inbound.status_code == 200
    assert waitlist_route._memory_waitlist[-1]["source"] == "inbound_email"

    pages = client.post(
        "/api/waitlist",
        json={"email": "pages@example.com", "source": "pages_exhausted"},
    )
    assert pages.status_code == 200
    assert waitlist_route._memory_waitlist[-1]["source"] == "pages_exhausted"


def test_waitlist_requires_no_auth():
    response = client.post(
        "/api/waitlist",
        json={"email": "anon@example.com"},
    )
    assert response.status_code == 200


def test_usage_endpoint_requires_auth():
    response = client.get("/api/users/me/usage")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_usage_endpoint_returns_summary():
    override_current_user(auth_user(user_id="user-usage"))
    await record_usage("user-usage", 7)

    response = client.get("/api/users/me/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pages_used"] == 7
    assert body["pages_limit"] == 50


@pytest.mark.asyncio
async def test_run_adhoc_returns_429_when_over_monthly_cap(monkeypatch):
    from app.api.dependencies import get_repo
    from app.models.domain.upload import UploadRecord
    from app.models.domain.user import UserRecord
    from app.persistence.memory_repository import MemoryRepository

    monkeypatch.setattr(settings, "free_page_limit_monthly", 1)
    await record_usage("user-1", 1)

    repo = MemoryRepository()
    repo.save_user(UserRecord(user_id="user-1", name="Test", email="test@example.com"))
    repo.save_upload(UploadRecord(upload_id="upload-1", user_id="user-1"))
    app.dependency_overrides[get_repo] = lambda: repo

    async def _fake_pages(_upload_id: str) -> int:
        return 1

    monkeypatch.setattr("app.api.usage_http.count_upload_pages", _fake_pages)
    override_current_user()

    response = client.post(
        "/api/runs/adhoc",
        json={"upload_id": "upload-1", "task_description": "extract fields"},
    )
    assert response.status_code == 429
    detail = response.json()["detail"].lower()
    assert "free pages" in detail or "used" in detail


@pytest.mark.asyncio
async def test_refine_apply_returns_429_when_over_monthly_cap(monkeypatch):
    """Apply refine must meter pages — not only max_refines_per_run."""
    from app.api.dependencies import get_refine_service, get_repo
    from app.models.domain.pipeline import PlannedStep
    from app.models.domain.run import RunResult, StepRunRecord
    from app.persistence.memory_repository import MemoryRepository
    from app.persistence.user_templates.local_repository import LocalUserTemplateRepository
    from app.services.pipeline.refine_service import RefineService
    from app.services.templates.user_template_version_service import UserTemplateVersionService

    monkeypatch.setattr(settings, "free_page_limit_monthly", 1)
    await record_usage("user-1", 1)

    async def _fake_pages(_upload_id: str) -> int:
        return 1

    monkeypatch.setattr("app.api.usage_http.count_upload_pages", _fake_pages)

    repo = MemoryRepository()
    repo.save_run(
        RunResult(
            run_id="run-parent",
            upload_id="upload-1",
            task_description="extract",
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
            user_id="user-1",
            result={"rows": [{"vendor": "Acme"}]},
        )
    )
    app.dependency_overrides[get_repo] = lambda: repo
    versions = UserTemplateVersionService(repo, LocalUserTemplateRepository())
    app.dependency_overrides[get_refine_service] = lambda: RefineService(repo, versions)
    override_current_user()

    response = client.post(
        "/api/runs/run-parent/refine",
        json={"message": "fix vendor casing"},
    )
    assert response.status_code == 429
    detail = response.json()["detail"].lower()
    assert "free pages" in detail or "used" in detail


@pytest.mark.asyncio
async def test_refine_plan_preview_returns_429_when_over_monthly_cap(monkeypatch):
    """Ready plan + preview must meter GPT-4o pages before extract_fields."""
    from app.api.dependencies import get_repo, get_version_service
    from app.models.domain.pipeline import PlannedStep
    from app.models.domain.run import RunResult, StepRunRecord
    from app.persistence.memory_repository import MemoryRepository
    from app.persistence.user_templates.local_repository import LocalUserTemplateRepository
    from app.services.templates.user_template_version_service import UserTemplateVersionService

    monkeypatch.setattr(settings, "free_page_limit_monthly", 1)
    await record_usage("user-1", 1)

    async def _fake_pages(_upload_id: str) -> int:
        return 1

    monkeypatch.setattr("app.api.usage_http.count_upload_pages", _fake_pages)

    preview_calls = {"n": 0}

    async def _fake_plan(**_kwargs):
        return {
            "ready": True,
            "message": "Ready to apply.",
            "planned_changes": ["Normalize vendor"],
            "accumulated_instruction": "Normalize vendor casing.",
        }

    async def _fake_preview(*_args, **_kwargs):
        preview_calls["n"] += 1
        return []

    monkeypatch.setattr(
        "app.services.pipeline.refine_chat.plan_refinement",
        _fake_plan,
    )
    monkeypatch.setattr(
        "app.services.pipeline.refine_preview.preview_refinement",
        _fake_preview,
    )

    repo = MemoryRepository()
    repo.save_run(
        RunResult(
            run_id="run-parent",
            upload_id="upload-1",
            task_description="extract",
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
            user_id="user-1",
            result={"rows": [{"vendor": "Acme"}]},
        )
    )
    app.dependency_overrides[get_repo] = lambda: repo
    versions = UserTemplateVersionService(repo, LocalUserTemplateRepository())
    app.dependency_overrides[get_version_service] = lambda: versions
    override_current_user()

    response = client.post(
        "/api/runs/run-parent/refine/plan",
        json={"message": "fix vendor", "chat_history": []},
    )
    assert response.status_code == 429
    assert preview_calls["n"] == 0  # must not burn GPT-4o when over cap


@pytest.mark.asyncio
async def test_refine_plan_returns_429_when_refine_cap_hit(monkeypatch):
    """Plan mode must block at max_refines_per_run before Groq/preview spend."""
    from app.api.dependencies import get_repo, get_version_service
    from app.models.domain.pipeline import PlannedStep
    from app.models.domain.run import RunResult, StepRunRecord
    from app.persistence.memory_repository import MemoryRepository
    from app.persistence.user_templates.local_repository import LocalUserTemplateRepository
    from app.services.templates.user_template_version_service import UserTemplateVersionService

    monkeypatch.setattr(settings, "max_refines_per_run", 1)

    plan_calls = {"n": 0}

    async def _fake_plan(**_kwargs):
        plan_calls["n"] += 1
        return {
            "in_scope": True,
            "ready": True,
            "message": "Ready",
            "planned_changes": ["x"],
            "accumulated_instruction": "x",
        }

    monkeypatch.setattr(
        "app.services.pipeline.refine_chat.plan_refinement",
        _fake_plan,
    )

    repo = MemoryRepository()
    parent = RunResult(
        run_id="run-parent",
        upload_id="upload-1",
        task_description="extract",
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
        user_id="user-1",
        result={"rows": [{"vendor": "Acme"}]},
    )
    child = RunResult(
        run_id="run-child",
        upload_id="upload-1",
        task_description="extract",
        status="completed",
        parent_run_id="run-parent",
        steps=[],
        planned_steps=parent.planned_steps,
        user_id="user-1",
        result={"rows": [{"vendor": "Acme"}]},
    )
    repo.save_run(parent)
    repo.save_run(child)
    app.dependency_overrides[get_repo] = lambda: repo
    versions = UserTemplateVersionService(repo, LocalUserTemplateRepository())
    app.dependency_overrides[get_version_service] = lambda: versions
    override_current_user()

    response = client.post(
        "/api/runs/run-parent/refine/plan",
        json={"message": "fix vendor", "chat_history": []},
    )
    assert response.status_code == 429
    assert plan_calls["n"] == 0


@pytest.mark.asyncio
async def test_analytics_log_event_memory():
    await analytics_events.log_event(
        "run_started",
        user_id="user-1",
        run_id="run-1",
        page_count=2,
    )
    assert len(analytics_events._memory_analytics_events) == 1
    assert analytics_events._memory_analytics_events[0]["event_type"] == "run_started"
