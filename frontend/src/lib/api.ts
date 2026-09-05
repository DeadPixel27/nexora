const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const AUTH_TOKEN_KEY = "nexora_access_token";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(AUTH_TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token);
}

export function clearAccessToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY);
}

/** Fired when a stored JWT is rejected so UI can open the sign-in dialog. */
export const SESSION_EXPIRED_EVENT = "nexora:session-expired";

function clearLocalSessionAndPromptSignIn(): void {
  clearAccessToken();
  localStorage.removeItem("nexora_user_id");
  localStorage.removeItem("nexora_user_name");
  localStorage.removeItem("nexora_user_email");
  window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const token = getAccessToken();
  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore
    }

    // Prompt sign-in dialog when a sent token was rejected (expired session).
    // Unsigned callers (no token) should stay on the current page.
    if (res.status === 401 && typeof window !== "undefined" && token) {
      clearLocalSessionAndPromptSignIn();
      throw new ApiError("Session expired. Please sign in again.", 401);
    }

    throw new ApiError(String(detail), res.status);
  }
  return res.json() as Promise<T>;
}

export interface User {
  user_id: string;
  name: string;
  email: string;
  created_at: string | null;
  auth_provider?: string | null;
}

export interface UploadedDocument {
  document_id: string;
  filename: string;
  file_type: string;
  storage_path: string;
  extracted_text?: string;
  extraction_method?: string;
}

export interface UploadResponse {
  upload_id: string;
  documents: UploadedDocument[];
  message: string;
}

export interface UploadedDocumentSummary {
  document_id: string;
  filename: string;
  file_type: string;
  extraction_method?: string;
}

export interface UploadDocumentsResponse {
  upload_id: string;
  documents: UploadedDocumentSummary[];
}

export interface StepRun {
  step_order: number;
  agent_type: string;
  status: string;
  output: Record<string, unknown>;
  error_message?: string | null;
}

export interface PlannedStep {
  step_order: number;
  agent_type: string;
  config: Record<string, unknown>;
  reason: string;
}

export interface PipelineTemplateSummary {
  template_id: string;
  name: string;
  description: string;
  icon: string;
  category: string;
}

export interface PipelineTemplate extends PipelineTemplateSummary {
  task_description?: string;
  default_task: string;
  fields?: string[];
  extraction_instructions?: string;
  rules?: Record<string, unknown>[];
  output_format?: string;
  suggested_steps?: string[];
  example_output_fields?: string[];
  sort_order?: number;
}

export interface TemplateListResponse {
  templates: PipelineTemplateSummary[];
  count: number;
}

export interface FieldConfidence {
  [fieldName: string]: number; // 0.0 to 1.0
}

export interface ValidationWarning {
  field: string;
  message: string;
  severity: "warning" | "error";
}

export interface RunResult {
  format?: string;
  content?: string;
  rows?: Record<string, unknown>[];
  row_count?: number;
  filtered_count?: number;
  field_confidence?: Record<string, FieldConfidence>;
  validation_warnings?: Record<string, ValidationWarning[]>;
}

export interface RunDocumentSummary {
  document_id: string;
  filename: string;
}

export interface RunResponse {
  run_id: string;
  upload_id: string;
  task_description: string;
  status: string;
  document_ids: string[];
  documents?: RunDocumentSummary[];
  steps: StepRun[];
  planned_steps: PlannedStep[];
  workflow_id: string | null;
  parent_run_id?: string | null;
  template_id?: string | null;
  current_template_version_id?: string | null;
  extraction_prompt?: string | null;
  refine_summary?: string | null;
  result: RunResult | null;
  error_message: string | null;
  created_at?: string | null;
}

export interface RunRefineResponse {
  run: RunResponse;
  refine_summary: string;
}

// --- Plan Mode types ---

export interface RefinePlanMessage {
  role: "user" | "assistant";
  content: string;
}

export interface RefinePreviewField {
  field: string;
  before: unknown;
  after: unknown;
}

export interface RefinePreviewRow {
  document_id: string;
  filename: string;
  fields: RefinePreviewField[];
}

export interface RefinePlanResponse {
  ready: boolean;
  message: string;
  planned_changes: string[];
  accumulated_instruction: string;
  preview: RefinePreviewRow[];
  in_scope?: boolean;
}

export interface TemplateVersionSummary {
  version_id: string;
  version_number: number;
  refine_summary: string;
  parent_version_id: string | null;
  is_current: boolean;
  created_at: string | null;
  template_id: string;
}

export interface TemplateVersionDetail extends TemplateVersionSummary {
  extraction_prompt: string;
  planned_steps: PlannedStep[];
  user_message?: string | null;
}

export interface WorkflowStep {
  step_order: number;
  agent_type: string;
  config: Record<string, unknown>;
  reason: string;
}

export interface WorkflowSummary {
  workflow_id: string;
  user_id: string;
  name: string;
  description: string;
  source: string;
  step_count: number;
  created_at: string | null;
}

export interface WorkflowResponse {
  workflow_id: string;
  user_id: string;
  name: string;
  description: string;
  source: string;
  task_description: string;
  parent_template_id?: string | null;
  current_template_version_id?: string | null;
  current_version_number?: number | null;
  extraction_prompt?: string | null;
  steps: WorkflowStep[];
  created_at: string | null;
  default_email?: string | null;
  default_sheets_url?: string | null;
  default_sheet_name?: string | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  persistence: string;
  database: string | null;
}

export async function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/api/health");
}

export async function signIn(name: string, email: string): Promise<{
  user: User;
  is_new_user: boolean;
  auth_provider: string;
  token: string;
}> {
  return request("/api/auth/session", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email }),
  });
}

export async function signInWithGoogle(idToken: string): Promise<{
  user: User;
  is_new_user: boolean;
  auth_provider: string;
  token: string;
}> {
  return request("/api/auth/google", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id_token: idToken }),
  });
}

/** @deprecated Use signIn — kept for compatibility */
export async function createUser(name: string, email = ""): Promise<User> {
  const result = await signIn(name, email);
  return result.user;
}

export async function getUser(userId: string): Promise<User> {
  return request<User>(`/api/users/${userId}`);
}

export async function updateMyProfile(name: string): Promise<User> {
  return request<User>("/api/users/me", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export async function getUserWorkflows(userId: string): Promise<WorkflowSummary[]> {
  return request<WorkflowSummary[]>(`/api/users/${userId}/workflows`);
}

export async function getWorkflow(workflowId: string): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(`/api/workflows/${workflowId}`);
}

export async function getWorkflowRuns(workflowId: string): Promise<RunResponse[]> {
  return request<RunResponse[]>(`/api/workflows/${workflowId}/runs`);
}

export async function runWorkflow(
  workflowId: string,
  uploadId: string,
): Promise<RunResponse> {
  return request<RunResponse>(`/api/workflows/${workflowId}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ upload_id: uploadId }),
  });
}

export async function uploadFiles(files: File[]): Promise<UploadResponse> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  return request<UploadResponse>("/api/upload", { method: "POST", body: form });
}

export async function getUploadDocuments(
  uploadId: string,
): Promise<UploadDocumentsResponse> {
  return request<UploadDocumentsResponse>(`/api/uploads/${uploadId}`);
}

/** Mint a short-lived document URL (scoped doc_token — never put session JWT in query). */
export async function fetchDocumentAccessUrl(
  uploadId: string,
  documentId: string,
): Promise<{ url: string; expiresAt: string }> {
  const body = await request<{ url: string; expires_at: string }>(
    `/api/uploads/${uploadId}/documents/${documentId}/access`,
    { method: "POST" },
  );
  return { url: body.url, expiresAt: body.expires_at };
}

export async function listTemplates(category?: string): Promise<TemplateListResponse> {
  const query = category ? `?category=${encodeURIComponent(category)}` : "";
  return request<TemplateListResponse>(`/api/templates${query}`);
}

export async function getTemplate(templateId: string): Promise<PipelineTemplate> {
  return request<PipelineTemplate>(`/api/templates/${templateId}`);
}

export async function runTemplate(
  uploadId: string,
  templateId: string,
): Promise<RunResponse> {
  return request<RunResponse>("/api/runs/template", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      upload_id: uploadId,
      template_id: templateId,
    }),
  });
}

export async function runAdhoc(
  uploadId: string,
  taskDescription: string,
): Promise<RunResponse> {
  return request<RunResponse>("/api/runs/adhoc", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      upload_id: uploadId,
      task_description: taskDescription,
    }),
  });
}

export async function refineRun(
  runId: string,
  message: string,
): Promise<RunRefineResponse> {
  return request<RunRefineResponse>(`/api/runs/${runId}/refine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}

export async function refinePlan(
  runId: string,
  message: string,
  chatHistory: RefinePlanMessage[],
): Promise<RefinePlanResponse> {
  return request<RefinePlanResponse>(`/api/runs/${runId}/refine/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message,
      chat_history: chatHistory,
    }),
  });
}

export async function getRun(runId: string): Promise<RunResponse> {
  return request<RunResponse>(`/api/runs/${runId}`);
}

export interface DocChatCitation {
  filename: string;
  document_id: string;
  chunk_index: number | null;
  similarity: number | null;
  snippet: string;
}

export interface DocChatResponse {
  answer: string;
  citations: DocChatCitation[];
}

export async function chatRunDocuments(
  runId: string,
  question: string,
): Promise<DocChatResponse> {
  return request<DocChatResponse>(`/api/runs/${runId}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

export async function getWorkflowTemplateVersions(
  workflowId: string,
): Promise<TemplateVersionSummary[]> {
  return request<TemplateVersionSummary[]>(
    `/api/workflows/${workflowId}/template-versions`,
  );
}

export async function getWorkflowTemplateVersion(
  workflowId: string,
  versionId: string,
): Promise<TemplateVersionDetail> {
  return request<TemplateVersionDetail>(
    `/api/workflows/${workflowId}/template-versions/${versionId}`,
  );
}

export async function revertWorkflowToVersion(
  workflowId: string,
  versionId: string,
): Promise<{ current_template_version_id: string }> {
  return request<{ current_template_version_id: string }>(
    `/api/workflows/${workflowId}/revert`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ version_id: versionId }),
    },
  );
}

export async function saveWorkflowFromRun(
  runId: string,
  userId: string,
  name: string,
  description = "",
): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(`/api/workflows/from-run/${runId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, name, description }),
  });
}

export interface WorkflowSettingsUpdate {
  name?: string;
  description?: string;
  default_email?: string;
  default_sheets_url?: string;
  default_sheet_name?: string;
}

export async function updateWorkflowSettings(
  workflowId: string,
  data: WorkflowSettingsUpdate,
): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(`/api/workflows/${workflowId}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function updateWorkflowFromRun(
  workflowId: string,
  runId: string,
  versionName?: string,
): Promise<WorkflowResponse> {
  return request<WorkflowResponse>(`/api/workflows/${workflowId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      from_run_id: runId,
      version_name: versionName,
    }),
  });
}

export async function deleteWorkflow(workflowId: string): Promise<void> {
  const headers = new Headers();
  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${API_BASE}/api/workflows/${workflowId}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore
    }
    if (res.status === 401 && typeof window !== "undefined" && token) {
      clearLocalSessionAndPromptSignIn();
      throw new ApiError("Session expired. Please sign in again.", 401);
    }
    throw new ApiError(String(detail), res.status);
  }
}

export async function emailResults(
  runId: string,
  to: string,
  subject: string,
): Promise<{ message: string }> {
  return request<{ message: string }>(`/api/runs/${runId}/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to, subject }),
  });
}

export async function pushToSheets(
  runId: string,
  url: string,
  sheetName: string,
): Promise<{ message: string }> {
  return request<{ message: string }>(`/api/runs/${runId}/sheets`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, sheet_name: sheetName }),
  });
}

// --- Integrations / inbound ---

export interface IntegrationsStatus {
  email_configured: boolean;
  sheets_configured: boolean;
  sheets_share_email: string | null;
  inbound_email_domain: string;
  inbound_configured: boolean;
}

export async function getIntegrationsStatus(): Promise<IntegrationsStatus> {
  return request<IntegrationsStatus>("/api/integrations");
}

export interface InboundAddress {
  address_id: string;
  full_address: string;
  user_id: string;
  workflow_id: string;
  created_at?: string | null;
}

export async function listInboundAddresses(): Promise<InboundAddress[]> {
  return request<InboundAddress[]>("/api/inbound-addresses");
}

export async function createInboundAddress(
  workflowId: string,
): Promise<InboundAddress> {
  return request<InboundAddress>("/api/inbound-addresses", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ workflow_id: workflowId }),
  });
}

export async function deleteInboundAddress(addressId: string): Promise<void> {
  const headers = new Headers();
  const token = getAccessToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const res = await fetch(`${API_BASE}/api/inbound-addresses/${addressId}`, {
    method: "DELETE",
    headers,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore
    }
    if (res.status === 401 && typeof window !== "undefined" && token) {
      clearLocalSessionAndPromptSignIn();
      throw new ApiError("Session expired. Please sign in again.", 401);
    }
    throw new ApiError(String(detail), res.status);
  }
}

// --- Usage types ---

export interface UsageSummary {
  pages_used: number;
  pages_limit: number;
  emails_used?: number;
  emails_limit?: number;
  sheets_used?: number;
  sheets_limit?: number;
  resets_at: string | null;
}

export async function getUserUsage(): Promise<UsageSummary> {
  return request<UsageSummary>("/api/users/me/usage");
}

// --- Waitlist types ---

export interface WaitlistResponse {
  message: string;
  already_joined: boolean;
}

export async function joinWaitlist(
  email: string,
  name: string = "",
  source: string = "normal",
  feedback: string = "",
): Promise<WaitlistResponse> {
  return request<WaitlistResponse>("/api/waitlist", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      email,
      name,
      source,
      feedback: feedback.trim(),
    }),
  });
}

export function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const keys = Object.keys(rows[0]);
  const escape = (v: unknown) => {
    const s = String(v ?? "");
    return s.includes(",") || s.includes('"') ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [
    keys.join(","),
    ...rows.map((row) => keys.map((k) => escape(row[k])).join(",")),
  ];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
