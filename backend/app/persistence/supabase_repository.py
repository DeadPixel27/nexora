"""Supabase Postgres repository — the only module that talks to Supabase tables."""

import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import Client, create_client

from app.config import settings
from app.models.domain.email import InboundAddress
from app.models.domain.pipeline import PlannedStep
from app.models.domain.run import RunResult, StepRunRecord
from app.models.domain.upload import UploadRecord
from app.models.domain.user import UserRecord
from app.models.domain.user_template_version import RefinementEvent, UserTemplateVersionRecord
from app.models.domain.workflow import WorkflowRecord, WorkflowSummary
from app.persistence.serialization import planned_steps_from_json, planned_steps_to_json
from app.persistence.versioned_persist import strip_run_for_persist, strip_workflow_for_persist

logger = logging.getLogger("db")

_client: Optional[Client] = None


def _is_configured() -> bool:
    return bool(settings.supabase_url and settings.supabase_secret_key)


def _get_client() -> Client:
    global _client
    if not _is_configured():
        raise RuntimeError("Supabase is not configured")
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_secret_key)
        logger.info("Supabase client initialized")
    return _client


class SupabaseRepository:
    backend_name = "supabase"

    def health_check(self) -> tuple[bool, str]:
        if not _is_configured():
            return False, "not_configured"
        try:
            _get_client().table("users").select("id").limit(1).execute()
            return True, "connected"
        except Exception as e:
            logger.warning("Supabase health check failed: %s", e)
            return False, str(e)

    def save_user(self, user: UserRecord) -> None:
        _get_client().table("users").upsert(
            {"id": user.user_id, "name": user.name, "email": user.email}
        ).execute()

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        resp = (
            _get_client().table("users").select("*").eq("id", user_id).maybe_single().execute()
        )
        if not resp.data:
            return None
        row = resp.data
        return UserRecord(
            user_id=row["id"],
            name=row["name"],
            email=row.get("email") or "",
            created_at=row.get("created_at"),
        )

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        normalized = email.strip().lower()
        if not normalized:
            return None
        resp = (
            _get_client()
            .table("users")
            .select("*")
            .eq("email", normalized)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        row = rows[0]
        return UserRecord(
            user_id=row["id"],
            name=row["name"],
            email=row.get("email") or "",
            created_at=row.get("created_at"),
        )

    def list_users(self) -> list[UserRecord]:
        resp = _get_client().table("users").select("*").order("created_at", desc=True).execute()
        return [
            UserRecord(
                user_id=row["id"],
                name=row["name"],
                email=row.get("email") or "",
                created_at=row.get("created_at"),
            )
            for row in resp.data or []
        ]

    def save_run(self, run: RunResult) -> None:
        persist_run = strip_run_for_persist(run)
        now = datetime.now(timezone.utc).isoformat()
        row: dict = {
            "id": persist_run.run_id,
            "workflow_id": persist_run.workflow_id,
            "upload_id": persist_run.upload_id,
            "document_ids": persist_run.document_ids,
            "task_description": persist_run.task_description,
            "status": persist_run.status,
            "planned_steps": planned_steps_to_json(persist_run.planned_steps),
            "result": persist_run.result,
            "error_message": persist_run.error_message,
            "completed_at": now if persist_run.status in ("completed", "failed") else None,
        }
        if persist_run.parent_run_id is not None:
            row["parent_run_id"] = persist_run.parent_run_id
        if persist_run.cached_documents is not None:
            row["cached_documents"] = persist_run.cached_documents
        if persist_run.refine_summary is not None:
            row["refine_summary"] = persist_run.refine_summary
        if persist_run.template_id is not None:
            row["template_id"] = persist_run.template_id
        if persist_run.current_template_version_id is not None:
            row["current_template_version_id"] = persist_run.current_template_version_id
        if persist_run.extraction_prompt is not None:
            row["extraction_prompt"] = persist_run.extraction_prompt
        else:
            row["extraction_prompt"] = None
        if persist_run.user_id is not None:
            row["user_id"] = persist_run.user_id

        _get_client().table("workflow_runs").upsert(row).execute()

        _get_client().table("workflow_step_runs").delete().eq("run_id", persist_run.run_id).execute()
        step_rows = [
            {
                "run_id": run.run_id,
                "step_order": step.step_order,
                "agent_type": step.agent_type,
                "status": step.status,
                "output": step.output,
                "error_message": step.error_message,
            }
            for step in run.steps
        ]
        if step_rows:
            _get_client().table("workflow_step_runs").insert(step_rows).execute()

    def get_run(self, run_id: str) -> Optional[RunResult]:
        run_resp = (
            _get_client().table("workflow_runs").select("*").eq("id", run_id).maybe_single().execute()
        )
        if not run_resp.data:
            return None

        row = run_resp.data
        steps_resp = (
            _get_client()
            .table("workflow_step_runs")
            .select("*")
            .eq("run_id", run_id)
            .order("step_order")
            .execute()
        )
        steps = [
            StepRunRecord(
                step_order=step["step_order"],
                agent_type=step["agent_type"],
                status=step["status"],
                output=step.get("output") or {},
                error_message=step.get("error_message"),
            )
            for step in steps_resp.data or []
        ]
        return RunResult(
            run_id=row["id"],
            workflow_id=row.get("workflow_id"),
            upload_id=row["upload_id"],
            document_ids=row.get("document_ids") or [],
            task_description=row.get("task_description") or "",
            status=row["status"],
            steps=steps,
            planned_steps=planned_steps_from_json(row.get("planned_steps")),
            parent_run_id=row.get("parent_run_id"),
            cached_documents=row.get("cached_documents"),
            refine_summary=row.get("refine_summary"),
            template_id=row.get("template_id"),
            current_template_version_id=row.get("current_template_version_id"),
            extraction_prompt=row.get("extraction_prompt"),
            result=row.get("result"),
            error_message=row.get("error_message"),
            user_id=row.get("user_id"),
            created_at=row.get("created_at"),
        )

    def count_child_runs(self, parent_run_id: str) -> int:
        resp = (
            _get_client()
            .table("workflow_runs")
            .select("id", count="exact")
            .eq("parent_run_id", parent_run_id)
            .execute()
        )
        if getattr(resp, "count", None) is not None:
            return int(resp.count)
        return len(resp.data or [])

    def list_runs_by_workflow(self, workflow_id: str) -> list[RunResult]:
        resp = (
            _get_client()
            .table("workflow_runs")
            .select("id")
            .eq("workflow_id", workflow_id)
            .order("created_at", desc=True)
            .execute()
        )
        runs: list[RunResult] = []
        for row in resp.data or []:
            run = self.get_run(row["id"])
            if run is not None:
                runs.append(run)
        return runs

    def list_runs_by_status(self, status: str) -> list[RunResult]:
        resp = (
            _get_client()
            .table("workflow_runs")
            .select("id")
            .eq("status", status)
            .order("created_at")
            .execute()
        )
        runs: list[RunResult] = []
        for row in resp.data or []:
            run = self.get_run(row["id"])
            if run is not None:
                runs.append(run)
        return runs

    def save_workflow(self, workflow: WorkflowRecord) -> None:
        persist_workflow = strip_workflow_for_persist(workflow)
        _get_client().table("workflows").upsert(
            {
                "id": persist_workflow.workflow_id,
                "user_id": persist_workflow.user_id,
                "name": persist_workflow.name,
                "description": persist_workflow.description,
                "source": persist_workflow.source,
                "task_description": persist_workflow.task_description,
                "parent_template_id": persist_workflow.parent_template_id,
                "current_template_version_id": persist_workflow.current_template_version_id,
                "extraction_prompt": persist_workflow.extraction_prompt,
                "default_email": persist_workflow.default_email,
                "default_sheets_url": persist_workflow.default_sheets_url,
                "default_sheet_name": persist_workflow.default_sheet_name,
            }
        ).execute()

        _get_client().table("workflow_steps").delete().eq(
            "workflow_id", persist_workflow.workflow_id
        ).execute()
        if not persist_workflow.current_template_version_id:
            step_rows = [
                {
                    "workflow_id": persist_workflow.workflow_id,
                    "step_order": step.step_order,
                    "agent_type": step.agent_type,
                    "config": step.config,
                    "reason": step.reason,
                }
                for step in persist_workflow.steps
            ]
            if step_rows:
                _get_client().table("workflow_steps").insert(step_rows).execute()

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        wf_resp = (
            _get_client()
            .table("workflows")
            .select("*")
            .eq("id", workflow_id)
            .maybe_single()
            .execute()
        )
        if not wf_resp.data:
            return None

        steps_resp = (
            _get_client()
            .table("workflow_steps")
            .select("*")
            .eq("workflow_id", workflow_id)
            .order("step_order")
            .execute()
        )
        steps = [
            PlannedStep(
                step_order=step["step_order"],
                agent_type=step["agent_type"],
                config=step.get("config") or {},
                reason=step.get("reason") or "",
            )
            for step in steps_resp.data or []
        ]
        row = wf_resp.data
        return WorkflowRecord(
            workflow_id=row["id"],
            user_id=row["user_id"],
            name=row["name"],
            description=row.get("description") or "",
            source=row.get("source") or "manual",
            task_description=row.get("task_description") or "",
            parent_template_id=row.get("parent_template_id"),
            current_template_version_id=row.get("current_template_version_id"),
            extraction_prompt=row.get("extraction_prompt"),
            steps=steps,
            created_at=row.get("created_at"),
            default_email=row.get("default_email"),
            default_sheets_url=row.get("default_sheets_url"),
            default_sheet_name=row.get("default_sheet_name"),
        )

    def list_workflows(self, user_id: Optional[str] = None) -> list[WorkflowSummary]:
        query = _get_client().table("workflows").select("*").order("created_at", desc=True)
        if user_id is not None:
            query = query.eq("user_id", user_id)
        resp = query.execute()

        steps_resp = _get_client().table("workflow_steps").select("workflow_id").execute()
        step_counts: dict[str, int] = {}
        for step in steps_resp.data or []:
            wf_id = step["workflow_id"]
            step_counts[wf_id] = step_counts.get(wf_id, 0) + 1

        return [
            WorkflowSummary(
                workflow_id=row["id"],
                user_id=row["user_id"],
                name=row["name"],
                description=row.get("description") or "",
                source=row.get("source") or "manual",
                step_count=step_counts.get(row["id"], 0),
                created_at=row.get("created_at"),
            )
            for row in resp.data or []
        ]

    def delete_workflow(self, workflow_id: str) -> None:
        versions_resp = (
            _get_client()
            .table("user_template_versions")
            .select("id")
            .eq("scope_type", "workflow")
            .eq("scope_id", workflow_id)
            .execute()
        )
        version_ids = [row["id"] for row in versions_resp.data or []]
        if version_ids:
            _get_client().table("user_template_versions").delete().in_(
                "id", version_ids
            ).execute()

        _get_client().table("workflows").delete().eq("id", workflow_id).execute()

    def save_template_version(self, version: UserTemplateVersionRecord) -> None:
        _get_client().table("user_template_versions").upsert(
            {
                "id": version.version_id,
                "scope_type": version.scope_type,
                "scope_id": version.scope_id,
                "parent_version_id": version.parent_version_id,
                "template_id": version.template_id,
                "storage_key": version.storage_key,
                "refine_summary": version.refine_summary,
                "version_number": version.version_number,
            }
        ).execute()

    def get_template_version(self, version_id: str) -> Optional[UserTemplateVersionRecord]:
        resp = (
            _get_client()
            .table("user_template_versions")
            .select("*")
            .eq("id", version_id)
            .maybe_single()
            .execute()
        )
        if not resp.data:
            return None
        return _template_version_from_row(resp.data)

    def list_template_versions(
        self, scope_type: str, scope_id: str
    ) -> list[UserTemplateVersionRecord]:
        resp = (
            _get_client()
            .table("user_template_versions")
            .select("*")
            .eq("scope_type", scope_type)
            .eq("scope_id", scope_id)
            .order("version_number")
            .execute()
        )
        return [_template_version_from_row(row) for row in resp.data or []]

    def save_refinement_event(self, event: RefinementEvent) -> None:
        _get_client().table("refinement_events").insert(
            {
                "id": event.event_id,
                "template_id": event.template_id,
                "scope_type": event.scope_type,
                "scope_id": event.scope_id,
                "version_id": event.version_id,
                "parent_version_id": event.parent_version_id,
                "user_message": event.user_message,
                "refine_summary": event.refine_summary,
            }
        ).execute()

    def list_refinement_events(
        self, template_id: Optional[str] = None, limit: int = 100
    ) -> list[RefinementEvent]:
        query = (
            _get_client()
            .table("refinement_events")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
        )
        if template_id is not None:
            query = query.eq("template_id", template_id)
        resp = query.execute()
        return [_refinement_event_from_row(row) for row in resp.data or []]

    def save_inbound_address(self, address: InboundAddress) -> None:
        _get_client().table("inbound_addresses").upsert(
            {
                "address_id": address.address_id,
                "full_address": address.full_address,
                "user_id": address.user_id,
                "workflow_id": address.workflow_id,
            }
        ).execute()

    def get_inbound_address(self, address_id: str) -> Optional[InboundAddress]:
        resp = (
            _get_client()
            .table("inbound_addresses")
            .select("*")
            .eq("address_id", address_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return _inbound_address_from_row(rows[0])

    def get_inbound_address_for_workflow(
        self, workflow_id: str
    ) -> Optional[InboundAddress]:
        resp = (
            _get_client()
            .table("inbound_addresses")
            .select("*")
            .eq("workflow_id", workflow_id)
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return _inbound_address_from_row(rows[0])

    def list_inbound_addresses(self, user_id: str) -> list[InboundAddress]:
        resp = (
            _get_client()
            .table("inbound_addresses")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        return [_inbound_address_from_row(row) for row in resp.data or []]

    def delete_inbound_address(self, address_id: str) -> None:
        _get_client().table("inbound_addresses").delete().eq(
            "address_id", address_id
        ).execute()

    def save_upload(self, upload: UploadRecord) -> None:
        row: dict = {
            "id": upload.upload_id,
            "user_id": upload.user_id,
        }
        if upload.created_at:
            row["created_at"] = upload.created_at
        _get_client().table("uploads").upsert(row).execute()

    def get_upload(self, upload_id: str) -> Optional[UploadRecord]:
        resp = (
            _get_client()
            .table("uploads")
            .select("*")
            .eq("id", upload_id)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            return None
        return _upload_from_row(rows[0])


def _upload_from_row(row: dict) -> UploadRecord:
    return UploadRecord(
        upload_id=row["id"],
        user_id=str(row["user_id"]),
        created_at=row.get("created_at"),
    )


def _inbound_address_from_row(row: dict) -> InboundAddress:
    return InboundAddress(
        address_id=row["address_id"],
        full_address=row["full_address"],
        user_id=row["user_id"],
        workflow_id=row["workflow_id"],
        created_at=row.get("created_at"),
    )


def _template_version_from_row(row: dict) -> UserTemplateVersionRecord:
    return UserTemplateVersionRecord(
        version_id=row["id"],
        scope_type=row["scope_type"],
        scope_id=row["scope_id"],
        parent_version_id=row.get("parent_version_id"),
        template_id=row["template_id"],
        storage_key=row["storage_key"],
        refine_summary=row.get("refine_summary") or "",
        version_number=row["version_number"],
        created_at=row.get("created_at"),
    )


def _refinement_event_from_row(row: dict) -> RefinementEvent:
    return RefinementEvent(
        event_id=row["id"],
        template_id=row["template_id"],
        scope_type=row["scope_type"],
        scope_id=row["scope_id"],
        version_id=row["version_id"],
        parent_version_id=row.get("parent_version_id"),
        user_message=row.get("user_message") or "",
        refine_summary=row.get("refine_summary") or "",
        created_at=row.get("created_at"),
    )


def is_supabase_configured() -> bool:
    """Used only by registry.py to resolve auto backends."""
    return _is_configured()


def get_supabase_client() -> Client:
    """Shared by SupabaseRepository and SupabaseDocumentRepository only."""
    return _get_client()
