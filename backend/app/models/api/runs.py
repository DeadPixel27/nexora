from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.api.pipeline import PlannedStepResponse


class PlannedStepInput(BaseModel):
    step_order: int
    agent_type: str
    config: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class RunRequest(BaseModel):
    upload_id: str
    steps: list[PlannedStepInput] = Field(min_length=1)
    task_description: str = ""


class RunTemplateRequest(BaseModel):
    upload_id: str
    template_id: str = Field(min_length=1)


class RunRefineRequest(BaseModel):
    message: str = Field(min_length=1)


class RefineChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class RefinePlanRequest(BaseModel):
    """Plan mode: clarify user intent before expensive re-run."""

    message: str = Field(min_length=1)
    chat_history: list[RefineChatMessage] = Field(default_factory=list)


class RefinePreviewField(BaseModel):
    field: str
    before: Any = None
    after: Any = None


class RefinePreviewRow(BaseModel):
    document_id: str
    filename: str = ""
    fields: list[RefinePreviewField] = Field(default_factory=list)


class RefinePlanResponse(BaseModel):
    """Response from plan mode clarification."""

    ready: bool  # true = user can click Apply
    message: str  # assistant response to show in chat
    planned_changes: list[str] = Field(default_factory=list)
    accumulated_instruction: str = ""  # full instruction to send to /refine when ready
    preview: list[RefinePreviewRow] = Field(default_factory=list)
    in_scope: bool = True  # false = refused; no preview / Apply


class RunAdhocRequest(BaseModel):
    upload_id: str
    task_description: str = Field(min_length=1)


class RunDocChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class RunDocChatCitation(BaseModel):
    filename: str = ""
    document_id: str = ""
    chunk_index: Optional[int] = None
    similarity: Optional[float] = None
    snippet: str = ""


class RunDocChatResponse(BaseModel):
    answer: str
    citations: list[RunDocChatCitation] = Field(default_factory=list)
    tokens_used: int = 0


class StepRunResponse(BaseModel):
    step_order: int
    agent_type: str
    status: str
    output: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None


class RunDocumentSummary(BaseModel):
    document_id: str
    filename: str = ""


class RunResponse(BaseModel):
    run_id: str
    upload_id: str
    task_description: str
    status: str
    document_ids: list[str] = Field(default_factory=list)
    documents: list[RunDocumentSummary] = Field(default_factory=list)
    steps: list[StepRunResponse]
    planned_steps: list[PlannedStepResponse] = Field(default_factory=list)
    workflow_id: Optional[str] = None
    parent_run_id: Optional[str] = None
    template_id: Optional[str] = None
    current_template_version_id: Optional[str] = None
    extraction_prompt: Optional[str] = None
    refine_summary: Optional[str] = None
    result: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None


class RunRefineResponse(BaseModel):
    run: RunResponse
    refine_summary: str
