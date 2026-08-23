"""Template catalog and template-run tests."""

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_template_repo
from app.main import app
from app.models.domain.template import TemplateNotFoundError
from app.persistence.templates.memory_repository import MemoryTemplateRepository
from app.services.templates.template_service import TemplateService
from app.templates.invoice import INVOICE_TEMPLATE
from app.services.pipeline.template_planner import create_plan_from_template

client = TestClient(app)


def test_memory_repository_lists_seven_templates():
    repo = MemoryTemplateRepository()
    templates = repo.list_templates()
    assert len(templates) == 8
    assert templates[0].template_id == "invoice"


def test_memory_repository_filters_by_category():
    repo = MemoryTemplateRepository()
    finance = repo.list_templates(category="finance")
    assert len(finance) == 4
    assert all(item.category == "finance" for item in finance)


def test_invoice_template_has_extraction_instructions():
    assert INVOICE_TEMPLATE.extraction_instructions
    assert "line_items" in INVOICE_TEMPLATE.fields
    assert INVOICE_TEMPLATE.rules


def test_template_service_raises_for_missing():
    service = TemplateService(MemoryTemplateRepository())
    with pytest.raises(TemplateNotFoundError):
        service.get_template("does-not-exist")


def test_list_templates_api():
    memory = MemoryTemplateRepository()
    app.dependency_overrides[get_template_repo] = lambda: memory
    try:
        response = client.get("/api/templates")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] == 8
        first = data["templates"][0]
        assert first["template_id"] == "invoice"
        assert "icon" in first
        assert "default_task" not in first
    finally:
        app.dependency_overrides.clear()


def test_get_template_api_returns_full_detail():
    memory = MemoryTemplateRepository()
    app.dependency_overrides[get_template_repo] = lambda: memory
    try:
        response = client.get("/api/templates/invoice")
        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "Invoice Parser"
        assert body["fields"]
        assert body["extraction_instructions"]
        assert body["default_task"] == body["task_description"]
        missing = client.get("/api/templates/missing-id")
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_supabase_repository_falls_back_when_table_missing(monkeypatch):
    from postgrest.exceptions import APIError

    from app.persistence.templates.supabase_repository import SupabaseTemplateRepository

    class _BrokenClient:
        def table(self, name: str):
            raise APIError({"message": "missing", "code": "PGRST205"})

    monkeypatch.setattr(
        "app.persistence.templates.supabase_repository._get_client",
        lambda: _BrokenClient(),
    )
    repo = SupabaseTemplateRepository()
    templates = repo.list_templates()
    assert len(templates) == 8
    assert templates[0].template_id == "invoice"


@pytest.mark.asyncio
async def test_create_plan_from_template_includes_extractor_config(monkeypatch):
    class _FakeDoc:
        document_id = "doc-1"
        filename = "invoice.pdf"
        file_type = ".pdf"
        extraction_method = "pymupdf"
        has_text = True
        text = "Invoice total 1000"
        text_preview = "Invoice"
        storage_key = "k"

    async def _fake_load(upload_id: str):
        return [_FakeDoc()]

    monkeypatch.setattr(
        "app.services.pipeline.template_planner.load_upload_documents",
        _fake_load,
    )

    plan = await create_plan_from_template(INVOICE_TEMPLATE, "upload-1")
    assert plan.task_description == INVOICE_TEMPLATE.task_description
    extractor = next(
        step for step in plan.steps if step.agent_type == "transform.field_extractor"
    )
    assert extractor.config["fields"] == INVOICE_TEMPLATE.fields
    assert extractor.config["instructions"] == INVOICE_TEMPLATE.extraction_instructions
    normalize = next(
        step for step in plan.steps if step.agent_type == "transform.normalize"
    )
    assert normalize.step_order == extractor.step_order + 1
    rules_step = next(
        step for step in plan.steps if step.agent_type == "transform.rules"
    )
    assert rules_step.config["rules"] == INVOICE_TEMPLATE.rules
    assert rules_step.step_order == normalize.step_order + 1
