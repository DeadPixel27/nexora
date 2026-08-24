"""In-memory data repository — dev / tests when no database is configured."""

from dataclasses import replace
from typing import Optional

from app.models.domain.email import InboundAddress
from app.models.domain.run import RunResult
from app.models.domain.upload import UploadRecord
from app.models.domain.user import UserRecord
from app.models.domain.user_template_version import RefinementEvent, UserTemplateVersionRecord
from app.models.domain.workflow import WorkflowRecord, WorkflowSummary
from app.persistence.versioned_persist import strip_run_for_persist, strip_workflow_for_persist


class MemoryRepository:
    backend_name = "memory"

    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}
        self._runs: dict[str, RunResult] = {}
        self._workflows: dict[str, WorkflowRecord] = {}
        self._template_versions: dict[str, UserTemplateVersionRecord] = {}
        self._refinement_events: list[RefinementEvent] = []
        self._inbound_addresses: dict[str, InboundAddress] = {}
        self._uploads: dict[str, UploadRecord] = {}

    def health_check(self) -> tuple[bool, str]:
        return True, "in_memory"

    def save_user(self, user: UserRecord) -> None:
        self._users[user.user_id] = user

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> Optional[UserRecord]:
        normalized = email.strip().lower()
        for user in self._users.values():
            if user.email.strip().lower() == normalized:
                return user
        return None

    def list_users(self) -> list[UserRecord]:
        return list(self._users.values())

    def save_run(self, run: RunResult) -> None:
        self._runs[run.run_id] = strip_run_for_persist(run)

    def get_run(self, run_id: str) -> Optional[RunResult]:
        return self._runs.get(run_id)

    def list_runs_by_workflow(self, workflow_id: str) -> list[RunResult]:
        runs = [run for run in self._runs.values() if run.workflow_id == workflow_id]
        return sorted(
            runs,
            key=lambda run: run.created_at or run.run_id,
            reverse=True,
        )

    def list_runs_by_status(self, status: str) -> list[RunResult]:
        runs = [run for run in self._runs.values() if run.status == status]
        return sorted(
            runs,
            key=lambda run: run.created_at or run.run_id,
        )

    def count_child_runs(self, parent_run_id: str) -> int:
        return sum(
            1 for run in self._runs.values() if run.parent_run_id == parent_run_id
        )

    def save_workflow(self, workflow: WorkflowRecord) -> None:
        self._workflows[workflow.workflow_id] = strip_workflow_for_persist(workflow)

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowRecord]:
        return self._workflows.get(workflow_id)

    def list_workflows(self, user_id: Optional[str] = None) -> list[WorkflowSummary]:
        workflows = self._workflows.values()
        if user_id is not None:
            workflows = [wf for wf in workflows if wf.user_id == user_id]

        return [
            WorkflowSummary(
                workflow_id=wf.workflow_id,
                user_id=wf.user_id,
                name=wf.name,
                description=wf.description,
                source=wf.source,
                step_count=len(wf.steps),
                created_at=wf.created_at,
            )
            for wf in workflows
        ]

    def delete_workflow(self, workflow_id: str) -> None:
        self._workflows.pop(workflow_id, None)
        version_ids = [
            version.version_id
            for version in self._template_versions.values()
            if version.scope_type == "workflow" and version.scope_id == workflow_id
        ]
        for version_id in version_ids:
            self._template_versions.pop(version_id, None)
        self._refinement_events = [
            event
            for event in self._refinement_events
            if not (
                event.scope_type == "workflow" and event.scope_id == workflow_id
            )
        ]
        for address_id, address in list(self._inbound_addresses.items()):
            if address.workflow_id == workflow_id:
                self._inbound_addresses.pop(address_id, None)
        for run_id, run in list(self._runs.items()):
            if run.workflow_id == workflow_id:
                self._runs[run_id] = replace(run, workflow_id=None)

    def save_template_version(self, version: UserTemplateVersionRecord) -> None:
        self._template_versions[version.version_id] = version

    def get_template_version(self, version_id: str) -> Optional[UserTemplateVersionRecord]:
        return self._template_versions.get(version_id)

    def list_template_versions(
        self, scope_type: str, scope_id: str
    ) -> list[UserTemplateVersionRecord]:
        versions = [
            version
            for version in self._template_versions.values()
            if version.scope_type == scope_type and version.scope_id == scope_id
        ]
        return sorted(versions, key=lambda version: version.version_number)

    def save_refinement_event(self, event: RefinementEvent) -> None:
        self._refinement_events.append(event)

    def list_refinement_events(
        self, template_id: Optional[str] = None, limit: int = 100
    ) -> list[RefinementEvent]:
        events = self._refinement_events
        if template_id is not None:
            events = [event for event in events if event.template_id == template_id]
        return sorted(events, key=lambda event: event.created_at or "", reverse=True)[:limit]

    def save_inbound_address(self, address: InboundAddress) -> None:
        self._inbound_addresses[address.address_id] = address

    def get_inbound_address(self, address_id: str) -> Optional[InboundAddress]:
        return self._inbound_addresses.get(address_id)

    def get_inbound_address_for_workflow(
        self, workflow_id: str
    ) -> Optional[InboundAddress]:
        for address in self._inbound_addresses.values():
            if address.workflow_id == workflow_id:
                return address
        return None

    def list_inbound_addresses(self, user_id: str) -> list[InboundAddress]:
        return [
            address
            for address in self._inbound_addresses.values()
            if address.user_id == user_id
        ]

    def delete_inbound_address(self, address_id: str) -> None:
        self._inbound_addresses.pop(address_id, None)

    def save_upload(self, upload: UploadRecord) -> None:
        self._uploads[upload.upload_id] = upload

    def get_upload(self, upload_id: str) -> Optional[UploadRecord]:
        return self._uploads.get(upload_id)
