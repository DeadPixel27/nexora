"""Upload ownership — bind upload_id to user_id (IDOR prevention)."""

import io
from unittest.mock import AsyncMock

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.api.dependencies import get_doc_store, get_repo, get_upload_service
from app.config import settings
from app.main import app
from app.models.domain.upload import UploadRecord
from app.models.domain.user import UserRecord
from app.persistence.documents.local_repository import LocalDocumentRepository
from app.persistence.memory_repository import MemoryRepository
from app.services.analytics import events as analytics_events
from app.services.documents.upload_service import UploadService
from app.services.usage import metering
from tests.auth_helpers import auth_user, override_current_user

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    metering.reset_memory_usage()
    analytics_events.reset_memory_analytics()
    monkeypatch.setattr(
        "app.persistence.supabase_repository.is_supabase_configured",
        lambda: False,
    )
    yield
    metering.reset_memory_usage()
    analytics_events.reset_memory_analytics()
    app.dependency_overrides.clear()


@pytest.fixture
def owned_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    if not settings.jwt_secret_key:
        monkeypatch.setattr(settings, "jwt_secret_key", "test-secret-upload-ownership")

    repo = MemoryRepository()
    owner = UserRecord(user_id="user-1", name="Owner", email="owner@example.com")
    other = UserRecord(user_id="user-2", name="Other", email="other@example.com")
    repo.save_user(owner)
    repo.save_user(other)

    store = LocalDocumentRepository()
    upload_id = "up-owned"

    async def _seed():
        saved = await store.save_document(
            upload_id,
            UploadFile(filename="inv.pdf", file=io.BytesIO(b"%PDF-1.4 hello")),
        )
        repo.save_upload(UploadRecord(upload_id=upload_id, user_id=owner.user_id))
        return saved

    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_doc_store] = lambda: store
    return {
        "repo": repo,
        "store": store,
        "owner": owner,
        "other": other,
        "upload_id": upload_id,
        "seed": _seed,
    }


@pytest.mark.asyncio
async def test_owner_can_list_upload(owned_upload):
    await owned_upload["seed"]()
    override_current_user(auth_user(user_id="user-1", email="owner@example.com"))

    response = client.get(f"/api/uploads/{owned_upload['upload_id']}")
    assert response.status_code == 200
    assert response.json()["upload_id"] == owned_upload["upload_id"]


@pytest.mark.asyncio
async def test_other_user_list_returns_403(owned_upload):
    await owned_upload["seed"]()
    override_current_user(auth_user(user_id="user-2", email="other@example.com"))

    response = client.get(f"/api/uploads/{owned_upload['upload_id']}")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unknown_upload_returns_404(owned_upload):
    override_current_user(auth_user(user_id="user-1"))
    response = client.get("/api/uploads/does-not-exist")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_other_user_mint_returns_403(owned_upload):
    saved = await owned_upload["seed"]()
    override_current_user(auth_user(user_id="user-2", email="other@example.com"))

    response = client.post(
        f"/api/uploads/{owned_upload['upload_id']}/documents/{saved.document_id}/access",
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_other_user_extract_returns_403(owned_upload, monkeypatch):
    await owned_upload["seed"]()
    override_current_user(auth_user(user_id="user-2", email="other@example.com"))

    extract = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.api.routes.extract.extract_fields_from_upload",
        extract,
    )
    monkeypatch.setattr(
        "app.api.routes.extract.count_upload_pages",
        AsyncMock(return_value=1),
    )

    response = client.post(
        "/api/extract/from-upload",
        json={
            "upload_id": owned_upload["upload_id"],
            "fields": ["vendor"],
        },
    )
    assert response.status_code == 403
    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_other_user_adhoc_returns_403(owned_upload, monkeypatch):
    await owned_upload["seed"]()
    override_current_user(auth_user(user_id="user-2", email="other@example.com"))

    plan = AsyncMock()
    monkeypatch.setattr("app.api.routes.runs.create_plan", plan)
    monkeypatch.setattr(
        "app.api.usage_http.count_upload_pages",
        AsyncMock(return_value=1),
    )

    response = client.post(
        "/api/runs/adhoc",
        json={
            "upload_id": owned_upload["upload_id"],
            "task_description": "extract fields",
        },
    )
    assert response.status_code == 403
    plan.assert_not_awaited()


@pytest.mark.asyncio
async def test_upload_create_persists_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", tmp_path)
    if not settings.jwt_secret_key:
        monkeypatch.setattr(settings, "jwt_secret_key", "test-secret-upload-ownership")

    repo = MemoryRepository()
    user = UserRecord(user_id="user-1", name="Owner", email="owner@example.com")
    repo.save_user(user)
    store = LocalDocumentRepository()

    async def _fake_extract(_path):
        from app.services.documents.text_extractor import ExtractionResult

        return ExtractionResult(text="hello", method="stub", error_message=None)

    monkeypatch.setattr(
        "app.services.documents.upload_service.extract_text",
        _fake_extract,
    )

    service = UploadService(store, repo)
    app.dependency_overrides[get_repo] = lambda: repo
    app.dependency_overrides[get_doc_store] = lambda: store
    app.dependency_overrides[get_upload_service] = lambda: service
    override_current_user(auth_user(user_id="user-1", email="owner@example.com"))

    response = client.post(
        "/api/upload",
        files=[("files", ("a.pdf", b"%PDF-1.4 x", "application/pdf"))],
    )
    assert response.status_code == 200, response.text
    upload_id = response.json()["upload_id"]
    recorded = repo.get_upload(upload_id)
    assert recorded is not None
    assert recorded.user_id == "user-1"


@pytest.mark.asyncio
async def test_inbound_process_binds_address_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "upload_dir", tmp_path)

    from app.models.domain.email import InboundAddress
    from app.services.email.inbound_service import InboundEmailService

    repo = MemoryRepository()
    store = LocalDocumentRepository()
    repo.save_inbound_address(
        InboundAddress(
            address_id="flow-abc",
            full_address="flow-abc@inbound.test",
            user_id="user-owner",
            workflow_id="wf-1",
        )
    )
    service = InboundEmailService(repo, store)
    upload_id, workflow_id, _sender, owner = await service.process_inbound(
        "flow-abc@inbound.test",
        "sender@example.com",
        [
            {
                "filename": "inv.pdf",
                "content": b"%PDF-1.4",
                "content_type": "application/pdf",
            }
        ],
    )
    assert workflow_id == "wf-1"
    assert owner == "user-owner"
    recorded = repo.get_upload(upload_id)
    assert recorded is not None
    assert recorded.user_id == "user-owner"


def test_create_inbound_address_is_idempotent_per_workflow(monkeypatch):
    monkeypatch.setattr(settings, "inbound_email_domain", "ingest.test")

    from app.services.email.inbound_service import InboundEmailService

    repo = MemoryRepository()
    service = InboundEmailService(repo, LocalDocumentRepository())
    first = service.create_inbound_address("user-1", "wf-1")
    second = service.create_inbound_address("user-1", "wf-1")
    assert first.address_id == second.address_id
    assert first.full_address == second.full_address
    other = service.create_inbound_address("user-1", "wf-2")
    assert other.address_id != first.address_id
    assert len(repo.list_inbound_addresses("user-1")) == 2
