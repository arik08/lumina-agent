import type {
  AnnouncementItem,
  AnnouncementList,
  AnnouncementMutationRequest,
  ArtifactDownload,
  ArtifactDraft,
  ArtifactSummary,
  ArtifactVersion,
  AdminAuditList,
  AdminAuditTraffic,
  AdminConversationDetail,
  AdminConversationList,
  AdminEmergencyStopResult,
  AdminInitialExecutionSettings,
  AdminProviderModel,
  AdminProviderSummary,
  AdminRunSafetySettings,
  AdminUsageStatistics,
  AdminUser,
  AdminUserList,
  AttachmentSummary,
  AnswerDeepAnalysisDecisionRequest,
  AuthSession,
  CancelDeepAnalysisMissionRequest,
  CreateKnowledgeTagRequest,
  CreateKnowledgeSpaceRequest,
  CreateAdminUserRequest,
  CreateConversationRequest,
  CreateDeepAnalysisMissionRequest,
  CreateProjectLearningProposalRequest,
  CreateProjectRequest,
  CurrentSettings,
  DeepAnalysisClaim,
  DeepAnalysisEvidence,
  DeepAnalysisMissionDetail,
  DeepAnalysisMissionEvent,
  DeepAnalysisRefreshPreview,
  DeepAnalysisResearchInspector,
  DeepAnalysisMissionProjection,
  DeepAnalysisMissionCosts,
  DeepAnalysisMissionExport,
  DeepAnalysisMissionSummary,
  DeepAnalysisOpenIssue,
  DeepAnalysisWorkflowRevision,
  DeepAnalysisWorkflowPattern,
  DeepAnalysisWorkflowPatternVersion,
  KnowledgeDocument,
  KnowledgeDocumentSummary,
  KnowledgeGraphResponse,
  KnowledgeSpace,
  KnowledgeTag,
  UpdateKnowledgeTagRequest,
  UpdateKnowledgeSpaceRequest,
  CursorPage,
  ListConversationsQuery,
  LoginRequest,
  RegistrationRequest,
  RegistrationResponse,
  RetryDeepAnalysisMissionRequest,
  RestartDeepAnalysisMissionRequest,
  SteerDeepAnalysisMissionRequest,
  RegenerateDeepAnalysisWorkflowRequest,
  InstructionDocument,
  RuntimePromptDocument,
  RuntimePromptKey,
  UpdateInstructionRequest,
  MemoryLearningMode,
  MemoryOptimizationResult,
  MemorySettings,
  ModelSummary,
  NotificationItem,
  NotificationList,
  NotificationReadAllResult,
  NotificationUnreadCount,
  MessageFeedback,
  ProjectSummary,
  ProjectMembership,
  CreateProjectMembershipRequest,
  UpdateProjectMembershipRequest,
  ProviderSummary,
  RunActionRequest,
  RunEvent,
  RunMutationResponse,
  RunSnapshot,
  RunStreamHandlers,
  SaveArtifactVersionRequest,
  StartRunRequest,
  StartDeepAnalysisMissionRequest,
  TurnSetPage,
  UserMemory,
  UpdateAdminUserRequest,
  UpdateProjectRequest,
  UpdateConversationRequest,
  UpdateDeepAnalysisMissionRequest,
  UpdateDeepAnalysisWorkflowDraftRequest,
  UpdateCurrentSettingsRequest,
  ConversationListItem,
  ComposerSuggestion,
  ConversationExportFormat,
  ConversationSearchResponse,
  ConversationShareCreated,
  ExtensionInstallation,
  ExecutionSelection,
  ScheduledRun,
  ScheduledTask,
  ScheduleKind,
  SharedConversationSnapshot,
  HelpItem,
  HelpItemKind,
  HelpItemList,
  SkillDraft,
  SkillCatalogLikeResult,
  SkillCatalogResponse,
  SkillExtension,
  SkillVersion,
  ProjectFileDetail,
  ProjectFilePage,
  ProjectFolderSummary,
  ProjectFileSummary,
  ProjectLearningMutationResult,
  ProjectLearningProposal,
  ProjectLearningProposalStatus,
  ProjectMemory,
  ProjectMemoryHistory,
  McpConfiguration,
  McpDefinition,
  McpDefinitionCreateRequest,
  McpInstallation,
  McpAnswerTestResult,
  WebSourceContentPage,
} from "./api-types";
import { createClientId } from "./client-id";

type QueryValue = string | number | boolean | null | undefined;

interface ApiRequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  query?: Record<string, QueryValue>;
  csrf?: boolean;
  idempotencyKey?: string;
}

const apiBase = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");
const streamBase = (import.meta.env.VITE_STREAM_BASE_URL || "/stream").replace(/\/$/, "");
const BACKEND_CONTRACT_MISMATCH_MESSAGE = "Frontend와 Backend 버전이 일치하지 않습니다. Lumina 실행 창에서 R을 눌러 다시 시작해 주세요.";

export function attachmentContentUrl(attachmentId: string) {
  return `${apiBase}/attachments/${encodeURIComponent(attachmentId)}/content`;
}

let csrfToken: string | null = null;
let csrfBootstrap: Promise<void> | null = null;

const BACKEND_TRANSPORT_FAILURE_EVENT = "lumina:backend-transport-failure";

function reportBackendTransportFailure(error: unknown) {
  if (error instanceof DOMException && error.name === "AbortError") return;
  window.dispatchEvent(new Event(BACKEND_TRANSPORT_FAILURE_EVENT));
}

async function fetchBackend(input: RequestInfo | URL, init?: RequestInit) {
  try {
    return await fetch(input, init);
  } catch (error) {
    reportBackendTransportFailure(error);
    throw error;
  }
}

export function subscribeBackendTransportFailures(listener: () => void) {
  window.addEventListener(BACKEND_TRANSPORT_FAILURE_EVENT, listener);
  return () => window.removeEventListener(BACKEND_TRANSPORT_FAILURE_EVENT, listener);
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly field?: string;
  readonly details?: unknown;

  constructor(
    message: string,
    options: {
      status: number;
      code: string;
      requestId?: string;
      field?: string;
      details?: unknown;
    },
  ) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
    this.requestId = options.requestId;
    this.field = options.field;
    this.details = options.details;
  }
}

function buildUrl(base: string, path: string, query?: Record<string, QueryValue>) {
  const url = new URL(`${base}${path}`, window.location.origin);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      url.searchParams.set(key, String(value));
    }
  });
  return url.toString();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function captureCsrf(response: Response, payload?: unknown) {
  const headerToken = response.headers.get("X-CSRF-Token");
  if (headerToken) csrfToken = headerToken;
  if (isRecord(payload) && typeof payload.csrfToken === "string") {
    csrfToken = payload.csrfToken;
  }
}

async function parseBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined;
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) return response.json();
  return response.text();
}

function apiErrorFrom(response: Response, payload: unknown) {
  if (isRecord(payload)) {
    const routeMissing = response.status === 404 && payload.detail === "Not Found";
    return new ApiError(
      routeMissing
        ? BACKEND_CONTRACT_MISMATCH_MESSAGE
        : typeof payload.message === "string" ? payload.message : "요청을 처리하지 못했습니다.",
      {
        status: response.status,
        code: routeMissing
          ? "backend_contract_mismatch"
          : typeof payload.code === "string" ? payload.code : "request_failed",
        requestId: typeof payload.requestId === "string" ? payload.requestId : undefined,
        field: typeof payload.field === "string" ? payload.field : undefined,
        details: payload.details,
      },
    );
  }
  return new ApiError(
    typeof payload === "string" && payload ? payload : "요청을 처리하지 못했습니다.",
    { status: response.status, code: "request_failed" },
  );
}

async function bootstrapCsrfToken() {
  if (csrfToken) return;
  if (!csrfBootstrap) {
    csrfBootstrap = (async () => {
      const response = await fetchBackend(buildUrl(apiBase, "/auth/session"), {
        credentials: "include",
        headers: { Accept: "application/json" },
      });
      const payload = await parseBody(response);
      captureCsrf(response, payload);
      if (!response.ok) throw apiErrorFrom(response, payload);
      if (!csrfToken) {
        throw new ApiError("보안 토큰을 확인하지 못했습니다. 다시 로그인해 주세요.", {
          status: 403,
          code: "csrf_token_missing",
        });
      }
    })().finally(() => {
      csrfBootstrap = null;
    });
  }
  await csrfBootstrap;
}

async function fetchApi(path: string, options: ApiRequestOptions = {}) {
  const {
    body: requestBody,
    query,
    csrf = true,
    idempotencyKey,
    ...requestInit
  } = options;
  const method = (requestInit.method ?? "GET").toUpperCase();
  const unsafe = !["GET", "HEAD", "OPTIONS"].includes(method);
  if (unsafe && csrf) await bootstrapCsrfToken();

  const headers = new Headers(requestInit.headers);
  headers.set("Accept", "application/json");
  if (unsafe && csrf && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  if (idempotencyKey) {
    headers.set("Idempotency-Key", idempotencyKey);
  }

  let body: BodyInit | undefined;
  if (requestBody instanceof FormData || requestBody instanceof Blob) {
    body = requestBody;
  } else if (requestBody !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(requestBody);
  }

  const response = await fetchBackend(buildUrl(apiBase, path, query), {
    ...requestInit,
    body,
    cache: requestInit.cache ?? "no-store",
    credentials: "include",
    headers,
  });
  captureCsrf(response);

  if (!response.ok) {
    const payload = await parseBody(response);
    captureCsrf(response, payload);
    throw apiErrorFrom(response, payload);
  }
  return response;
}

async function request<T>(path: string, options?: ApiRequestOptions): Promise<T> {
  const response = await fetchApi(path, options);
  const contentType = response.headers.get("content-type") ?? "";
  if (response.status !== 204 && !contentType.includes("application/json")) {
    const backendContractMismatch = contentType.includes("text/html");
    throw new ApiError(backendContractMismatch
      ? BACKEND_CONTRACT_MISMATCH_MESSAGE
      : "서버가 예상하지 못한 응답을 반환했습니다. Lumina 실행 상태를 확인해 주세요.", {
      status: 502,
      code: backendContractMismatch ? "backend_contract_mismatch" : "invalid_api_response",
      details: { contentType, path, method: (options?.method ?? "GET").toUpperCase() },
    });
  }
  const payload = await parseBody(response);
  captureCsrf(response, payload);
  return payload as T;
}

export async function getAuthSession(signal?: AbortSignal) {
  return request<AuthSession>("/auth/session", { signal });
}

export interface UsdKrwExchangeRate {
  base: "USD";
  quote: "KRW";
  rate: number | null;
  asOf: string | null;
  source: string | null;
  status: "fresh" | "stale" | "unavailable";
}

const USD_KRW_FRESH_CACHE_MS = 6 * 60 * 60 * 1_000;
const USD_KRW_RETRY_CACHE_MS = 5 * 60 * 1_000;
let usdKrwExchangeRateRequest: Promise<UsdKrwExchangeRate> | null = null;
let usdKrwExchangeRateExpiresAt = 0;

export function getUsdKrwExchangeRate() {
  if (!usdKrwExchangeRateRequest || Date.now() >= usdKrwExchangeRateExpiresAt) {
    usdKrwExchangeRateExpiresAt = Number.POSITIVE_INFINITY;
    usdKrwExchangeRateRequest = (async () => {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 8_000);
      try {
        const result = await request<UsdKrwExchangeRate>("/finance/exchange-rate/usd-krw", {
          signal: controller.signal,
        });
        usdKrwExchangeRateExpiresAt = Date.now() + (
          result.status === "fresh" ? USD_KRW_FRESH_CACHE_MS : USD_KRW_RETRY_CACHE_MS
        );
        return result;
      } catch {
        usdKrwExchangeRateExpiresAt = Date.now() + USD_KRW_RETRY_CACHE_MS;
        return {
          base: "USD",
          quote: "KRW",
          rate: null,
          asOf: null,
          source: null,
          status: "unavailable",
        } satisfies UsdKrwExchangeRate;
      } finally {
        window.clearTimeout(timeout);
      }
    })();
  }
  return usdKrwExchangeRateRequest;
}

export async function login(payload: LoginRequest, signal?: AbortSignal) {
  return request<AuthSession>("/auth/login", {
    method: "POST",
    body: payload,
    csrf: false,
    signal,
  });
}

export async function registerAccount(payload: RegistrationRequest, signal?: AbortSignal) {
  return request<RegistrationResponse>("/auth/register", {
    method: "POST",
    body: payload,
    csrf: false,
    signal,
  });
}

export async function logout(signal?: AbortSignal) {
  await request<void>("/auth/logout", { method: "POST", signal });
  csrfToken = null;
}

export async function listNotifications(
  unreadOnly = false,
  limit = 50,
  offset = 0,
  signal?: AbortSignal,
) {
  return request<NotificationList>("/notifications", {
    query: { unreadOnly, limit, offset },
    signal,
  });
}

export async function getNotificationUnreadCount(signal?: AbortSignal) {
  return request<NotificationUnreadCount>("/notifications/unread-count", { signal });
}

export async function markNotificationRead(notificationId: string, signal?: AbortSignal) {
  return request<NotificationItem>(`/notifications/${encodeURIComponent(notificationId)}/read`, {
    method: "POST",
    signal,
  });
}

export async function markAllNotificationsRead(signal?: AbortSignal) {
  return request<NotificationReadAllResult>("/notifications/read-all", {
    method: "POST",
    signal,
  });
}

export async function deleteNotification(notificationId: string, signal?: AbortSignal) {
  await request<void>(`/notifications/${encodeURIComponent(notificationId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function deleteAllNotifications(signal?: AbortSignal) {
  await request<void>("/notifications", { method: "DELETE", signal });
}

export async function listProjects(signal?: AbortSignal) {
  return request<ProjectSummary[]>("/projects", { signal });
}

export async function createProject(payload: CreateProjectRequest, signal?: AbortSignal) {
  return request<ProjectSummary>("/projects", {
    method: "POST",
    body: payload,
    signal,
  });
}

export async function updateProject(
  projectId: string,
  payload: UpdateProjectRequest,
  signal?: AbortSignal,
) {
  return request<ProjectSummary>(`/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function archiveProject(projectId: string, signal?: AbortSignal) {
  await request<void>(`/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function getPersonalInstructions(signal?: AbortSignal) {
  return request<InstructionDocument>("/instructions/personal", { signal });
}

export async function updatePersonalInstructions(
  payload: UpdateInstructionRequest,
  signal?: AbortSignal,
) {
  return request<InstructionDocument>("/instructions/personal", {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function getProjectInstructions(projectId: string, signal?: AbortSignal) {
  return request<InstructionDocument>(
    `/projects/${encodeURIComponent(projectId)}/instructions`,
    { signal },
  );
}

export async function updateProjectInstructions(
  projectId: string,
  payload: UpdateInstructionRequest,
  signal?: AbortSignal,
) {
  return request<InstructionDocument>(
    `/projects/${encodeURIComponent(projectId)}/instructions`,
    { method: "PATCH", body: payload, signal },
  );
}

export async function getOrganizationInstructions(signal?: AbortSignal) {
  return request<InstructionDocument>("/admin/organization/instructions", { signal });
}

export async function updateOrganizationInstructions(
  payload: UpdateInstructionRequest,
  signal?: AbortSignal,
) {
  return request<InstructionDocument>("/admin/organization/instructions", {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function updateOrganizationInstructionRevisionLabel(
  revision: number,
  label: string,
  signal?: AbortSignal,
) {
  return request<{ revision: number; label: string }>(
    `/admin/organization/instructions/revisions/${revision}/label`,
    { method: "PATCH", body: { label }, signal },
  );
}

export async function getOrganizationInstructionRevision(
  revision: number,
  signal?: AbortSignal,
) {
  return request<{ revision: number; label: string; content: string }>(
    `/admin/organization/instructions/revisions/${revision}`,
    { signal },
  );
}

export async function updateOrganizationInstructionRevision(
  revision: number,
  content: string,
  signal?: AbortSignal,
) {
  return request<{ revision: number; content: string }>(
    `/admin/organization/instructions/revisions/${revision}`,
    { method: "PATCH", body: { content }, signal },
  );
}

export async function listProjectFiles(
  projectId: string,
  query = "",
  includeDeleted = false,
  cursor?: string,
  signal?: AbortSignal,
) {
  const response = await request<ProjectFilePage | ProjectFileSummary[]>(`/projects/${encodeURIComponent(projectId)}/files`, {
    query: { q: query, includeDeleted, limit: 200, cursor, page: true },
    signal,
  });
  if (Array.isArray(response)) return { items: response, nextCursor: null };
  if (!Array.isArray(response.items)) throw new Error("파일 목록 응답 형식이 올바르지 않습니다.");
  return response;
}

export async function getProjectFile(projectId: string, fileId: string, signal?: AbortSignal) {
  return request<ProjectFileDetail>(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
    { signal },
  );
}

export async function uploadProjectFile(
  projectId: string,
  file: File,
  logicalPath?: string,
  changeReason = "",
  signal?: AbortSignal,
) {
  const body = new FormData();
  body.set("file", file);
  if (logicalPath?.trim()) body.set("logicalPath", logicalPath.trim());
  if (changeReason.trim()) body.set("changeReason", changeReason.trim());
  return request<ProjectFileSummary>(`/projects/${encodeURIComponent(projectId)}/files`, {
    method: "POST",
    body,
    signal,
  });
}

export async function uploadProjectFileVersion(
  projectId: string,
  fileId: string,
  file: File,
  baseVersion: number,
  changeReason = "",
  signal?: AbortSignal,
) {
  const body = new FormData();
  body.set("file", file);
  body.set("baseVersion", String(baseVersion));
  if (changeReason.trim()) body.set("changeReason", changeReason.trim());
  return request<ProjectFileSummary>(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/versions`,
    { method: "POST", body, signal },
  );
}

export async function moveProjectFile(
  projectId: string,
  fileId: string,
  logicalPath: string,
  expectedRevision: number,
  signal?: AbortSignal,
) {
  return request<ProjectFileSummary>(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
    { method: "PATCH", body: { logicalPath, expectedRevision }, signal },
  );
}

export async function downloadProjectFile(
  projectId: string,
  fileId: string,
  version?: number,
  signal?: AbortSignal,
): Promise<ArtifactDownload> {
  const response = await fetchApi(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/download`,
    { query: { version }, signal },
  );
  return {
    blob: await response.blob(),
    fileName: downloadFileName(response, `project-file-${fileId}${version ? `-v${version}` : ""}`),
  };
}

export async function deleteProjectFile(
  projectId: string,
  fileId: string,
  expectedRevision: number,
  signal?: AbortSignal,
) {
  await request<void>(
    `/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}`,
    { method: "DELETE", query: { expectedRevision }, signal },
  );
}

export async function getCurrentSettings(projectId?: string, signal?: AbortSignal) {
  return request<CurrentSettings>("/settings/current", {
    query: { project_id: projectId },
    signal,
  });
}

export async function updateCurrentSettings(
  projectId: string | undefined,
  payload: UpdateCurrentSettingsRequest,
  signal?: AbortSignal,
) {
  return request<CurrentSettings>("/settings/current", {
    method: "PATCH",
    query: { project_id: projectId },
    body: payload,
    signal,
  });
}

export async function listProviders(projectId?: string, signal?: AbortSignal) {
  return request<ProviderSummary[]>("/providers", {
    query: { project_id: projectId },
    signal,
  });
}

export async function listProviderModels(providerId: string, projectId?: string, signal?: AbortSignal) {
  return request<ModelSummary[]>(`/providers/${encodeURIComponent(providerId)}/models`, {
    query: { project_id: projectId },
    signal,
  });
}

export async function listAdminProviderModels(providerId: string, signal?: AbortSignal) {
  return request<AdminProviderModel[]>(`/admin/providers/${encodeURIComponent(providerId)}/models`, { signal });
}

export async function getAdminInitialExecution(signal?: AbortSignal) {
  return request<AdminInitialExecutionSettings>("/admin/providers/initial-execution", { signal });
}

export async function updateAdminInitialExecution(execution: ExecutionSelection, signal?: AbortSignal) {
  return request<AdminInitialExecutionSettings>("/admin/providers/initial-execution", {
    method: "PATCH",
    body: { execution },
    signal,
  });
}

export async function listAnnouncements(limit = 50, offset = 0, signal?: AbortSignal) {
  return request<AnnouncementList>("/notifications/announcements", {
    query: { limit, offset },
    signal,
  });
}

export async function listAdminProviders(signal?: AbortSignal) {
  return request<AdminProviderSummary[]>("/admin/providers", { signal });
}

export async function updateAdminProviderAvailability(providerId: string, enabled: boolean, signal?: AbortSignal) {
  return request<AdminProviderSummary>(`/admin/providers/${encodeURIComponent(providerId)}`, {
    method: "PATCH",
    body: { enabled },
    signal,
  });
}

export async function updateAdminProviderModel(
  providerId: string,
  modelKey: string,
  patch: { enabled?: boolean; capabilities?: Record<string, unknown> },
  signal?: AbortSignal,
) {
  return request<AdminProviderModel>(`/admin/providers/${encodeURIComponent(providerId)}/models/${encodeURIComponent(modelKey)}`, {
    method: "PATCH",
    body: patch,
    signal,
  });
}

export async function listConversations(query: ListConversationsQuery = {}, signal?: AbortSignal) {
  const path = query.titleQuery ? "/conversations/search" : "/conversations";
  return request<CursorPage<ConversationListItem>>(path, {
    query: {
      project_id: query.projectId,
      cursor: query.cursor,
      limit: query.limit,
      title_query: query.titleQuery,
    },
    signal,
  });
}

export async function searchConversationContent(
  query: string,
  projectId?: string,
  signal?: AbortSignal,
) {
  return request<ConversationSearchResponse>("/conversations/content-search", {
    query: { q: query, project_id: projectId, limit: 50 },
    signal,
  });
}

export async function createConversation(payload: CreateConversationRequest, signal?: AbortSignal) {
  return request<ConversationListItem>("/conversations", {
    method: "POST",
    body: payload,
    signal,
  });
}

export async function updateConversation(
  conversationId: string,
  payload: UpdateConversationRequest,
  signal?: AbortSignal,
) {
  const { expectedRevision, ...changes } = payload;
  return request<ConversationListItem>(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "PATCH",
    body: changes,
    headers: { "If-Match": expectedRevision },
    signal,
  });
}

export async function moveConversation(
  conversationId: string,
  projectId: string,
  signal?: AbortSignal,
) {
  return request<ConversationListItem>(`/conversations/${encodeURIComponent(conversationId)}/move`, {
    method: "POST",
    body: { projectId, idempotencyKey: createClientId() },
    signal,
  });
}

export async function deleteConversation(conversationId: string, signal?: AbortSignal) {
  await request<void>(`/conversations/${encodeURIComponent(conversationId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function branchConversation(
  conversationId: string,
  anchorMessageId: string,
  title?: string,
  signal?: AbortSignal,
) {
  return request<ConversationListItem>(`/conversations/${encodeURIComponent(conversationId)}/branch`, {
    method: "POST",
    body: { anchorMessageId, title },
    signal,
  });
}

export async function exportConversation(
  conversationId: string,
  format: ConversationExportFormat,
  includeArtifacts = false,
  signal?: AbortSignal,
): Promise<ArtifactDownload> {
  const response = await fetchApi(`/conversations/${encodeURIComponent(conversationId)}/export`, {
    query: { format, include_artifacts: includeArtifacts },
    signal,
  });
  return {
    blob: await response.blob(),
    fileName: downloadFileName(response, `conversation.${format === "markdown" ? "md" : "json"}`),
  };
}

export async function getConversationTurnSets(
  conversationId: string,
  beforeCursor?: string,
  limitTurnSets = 3,
  signal?: AbortSignal,
) {
  return request<TurnSetPage>(`/conversations/${encodeURIComponent(conversationId)}/turn-sets`, {
    query: {
      before_cursor: beforeCursor,
      limit_turn_sets: limitTurnSets,
    },
    signal,
  });
}

export async function startRun(conversationId: string, payload: StartRunRequest, signal?: AbortSignal) {
  const { idempotencyKey, ...body } = payload;
  return request<RunMutationResponse>(`/conversations/${encodeURIComponent(conversationId)}/runs`, {
    method: "POST",
    body,
    idempotencyKey,
    signal,
  });
}

export async function sendRunAction(runId: string, payload: RunActionRequest, signal?: AbortSignal) {
  const { idempotencyKey, ...body } = payload;
  return request<RunMutationResponse>(`/runs/${encodeURIComponent(runId)}/actions`, {
    method: "POST",
    body,
    idempotencyKey,
    signal,
  });
}

export async function getRunSnapshot(runId: string, signal?: AbortSignal) {
  return request<RunSnapshot>(`/runs/${encodeURIComponent(runId)}/snapshot`, { signal });
}

export async function getProviderCatalog(projectId?: string, signal?: AbortSignal) {
  return request<{
    providers: ProviderSummary[];
    modelsByProvider: Record<string, ModelSummary[]>;
  }>("/provider-catalog", { query: { project_id: projectId }, signal });
}

export async function getRunSnapshots(runIds: string[], signal?: AbortSignal) {
  const uniqueRunIds = [...new Set(runIds)];
  if (uniqueRunIds.length === 0) return [];
  const chunks: string[][] = [];
  for (let index = 0; index < uniqueRunIds.length; index += 20) {
    chunks.push(uniqueRunIds.slice(index, index + 20));
  }
  const pages = await Promise.all(chunks.map((chunk) => request<RunSnapshot[]>("/runs/snapshots", {
    method: "POST",
    body: { runIds: chunk },
    signal,
  })));
  return pages.flat();
}

function isRunEvent(value: unknown): value is RunEvent {
  return isRecord(value)
    && typeof value.runId === "string"
    && typeof value.conversationId === "string"
    && typeof value.sequence === "number"
    && typeof value.type === "string"
    && typeof value.createdAt === "string";
}

export function openRunEventStream(
  runId: string,
  afterSequence: number,
  handlers: RunStreamHandlers,
) {
  const source = new EventSource(
    buildUrl(streamBase, `/runs/${encodeURIComponent(runId)}`, {
      after_sequence: Math.max(0, afterSequence),
    }),
    { withCredentials: true },
  );
  let lastDeliveredSequence = afterSequence;

  const handleMessage = (message: MessageEvent<string>) => {
    try {
      const parsed: unknown = JSON.parse(message.data);
      if (!isRunEvent(parsed)) throw new Error("Run event 형식이 올바르지 않습니다.");
      if (parsed.runId !== runId || parsed.sequence <= lastDeliveredSequence) return;
      lastDeliveredSequence = parsed.sequence;
      handlers.onEvent(parsed);
    } catch (error) {
      handlers.onError?.(error instanceof Error ? error : new Error("Run event를 읽지 못했습니다."));
    }
  };

  source.onopen = () => handlers.onOpen?.();
  source.onerror = (event) => handlers.onError?.(event);
  source.onmessage = handleMessage;
  source.addEventListener("run_event", handleMessage as EventListener);

  return () => source.close();
}

export async function getArtifact(artifactId: string, signal?: AbortSignal) {
  return request<ArtifactSummary>(`/artifacts/${encodeURIComponent(artifactId)}`, { signal });
}

export async function listRuntimePrompts(signal?: AbortSignal) {
  return request<RuntimePromptDocument[]>("/admin/runtime-prompts", { signal });
}

export async function updateRuntimePrompt(
  promptKey: RuntimePromptKey,
  payload: UpdateInstructionRequest,
  signal?: AbortSignal,
) {
  return request<RuntimePromptDocument>(
    `/admin/runtime-prompts/${encodeURIComponent(promptKey)}`,
    { method: "PATCH", body: payload, signal },
  );
}

export async function listProjectFolders(projectId: string, signal?: AbortSignal) {
  return request<ProjectFolderSummary[]>(
    `/projects/${encodeURIComponent(projectId)}/files/folders`,
    { signal },
  );
}

export async function createProjectFolder(projectId: string, logicalPath: string, signal?: AbortSignal) {
  return request<ProjectFolderSummary>(
    `/projects/${encodeURIComponent(projectId)}/files/folders`,
    { method: "POST", body: { logicalPath }, signal },
  );
}

export async function moveProjectFolder(
  projectId: string,
  sourcePath: string,
  targetPath: string,
  signal?: AbortSignal,
) {
  return request<{ fileCount: number; folderCount: number }>(
    `/projects/${encodeURIComponent(projectId)}/files/folders`,
    { method: "PATCH", body: { sourcePath, targetPath }, signal },
  );
}

export async function deleteProjectFolder(projectId: string, logicalPath: string, signal?: AbortSignal) {
  await request<void>(
    `/projects/${encodeURIComponent(projectId)}/files/folders`,
    { method: "DELETE", query: { logicalPath }, signal },
  );
}

export async function listProjectMemberships(
  projectId: string,
  includeRevoked = false,
  signal?: AbortSignal,
) {
  return request<ProjectMembership[]>(
    `/projects/${encodeURIComponent(projectId)}/memberships`,
    { query: { includeRevoked }, signal },
  );
}

export async function addProjectMembership(
  projectId: string,
  payload: CreateProjectMembershipRequest,
  signal?: AbortSignal,
) {
  return request<ProjectMembership>(
    `/projects/${encodeURIComponent(projectId)}/memberships`,
    { method: "POST", body: payload, signal },
  );
}

export async function updateProjectMembership(
  projectId: string,
  membershipId: string,
  payload: UpdateProjectMembershipRequest,
  signal?: AbortSignal,
) {
  return request<ProjectMembership>(
    `/projects/${encodeURIComponent(projectId)}/memberships/${encodeURIComponent(membershipId)}`,
    { method: "PATCH", body: payload, signal },
  );
}

export async function removeProjectMembership(
  projectId: string,
  membershipId: string,
  expectedRole: ProjectMembership["role"],
  expectedStatus: ProjectMembership["status"],
  signal?: AbortSignal,
) {
  await request<void>(
    `/projects/${encodeURIComponent(projectId)}/memberships/${encodeURIComponent(membershipId)}`,
    {
      method: "DELETE",
      query: { expectedRole, expectedStatus },
      signal,
    },
  );
}

export async function createMessageMarkdownArtifact(messageId: string, signal?: AbortSignal) {
  return request<ArtifactSummary>(`/artifacts/from-message/${encodeURIComponent(messageId)}`, {
    method: "POST",
    signal,
  });
}

export async function getArtifactVersion(artifactId: string, version: number, signal?: AbortSignal) {
  return request<ArtifactVersion>(
    `/artifacts/${encodeURIComponent(artifactId)}/versions/${encodeURIComponent(String(version))}`,
    { signal },
  );
}

export async function saveArtifactVersion(
  artifactId: string,
  payload: SaveArtifactVersionRequest,
  etag: string,
  draftEtag?: string,
  signal?: AbortSignal,
) {
  const { idempotencyKey, ...body } = payload;
  return request<ArtifactVersion>(`/artifacts/${encodeURIComponent(artifactId)}/versions`, {
    method: "POST",
    body,
    headers: {
      "If-Match": etag,
      ...(draftEtag ? { "X-Artifact-Draft-If-Match": draftEtag } : {}),
    },
    idempotencyKey,
    signal,
  });
}

export async function getArtifactDraft(artifactId: string, signal?: AbortSignal) {
  try {
    return await request<ArtifactDraft>(`/artifacts/${encodeURIComponent(artifactId)}/draft`, { signal });
  } catch (error) {
    if (error instanceof ApiError && error.status === 404 && error.code === "artifact_draft_not_found") {
      return null;
    }
    throw error;
  }
}

export async function saveArtifactDraft(
  artifactId: string,
  baseVersion: number,
  content: string,
  etag?: string,
  signal?: AbortSignal,
) {
  return request<ArtifactDraft>(`/artifacts/${encodeURIComponent(artifactId)}/draft`, {
    method: "PUT",
    body: { baseVersion, content },
    headers: etag ? { "If-Match": etag } : undefined,
    signal,
  });
}

function downloadFileName(response: Response, fallback: string) {
  const disposition = response.headers.get("content-disposition") ?? "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded);
    } catch {
      return fallback;
    }
  }
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? fallback;
}

export async function downloadArtifactVersion(
  artifactId: string,
  version: number,
  signal?: AbortSignal,
): Promise<ArtifactDownload> {
  const response = await fetchApi(`/artifacts/${encodeURIComponent(artifactId)}/download`, {
    query: { version },
    signal,
  });
  return {
    blob: await response.blob(),
    fileName: downloadFileName(response, `artifact-${artifactId}-v${version}`),
  };
}

export async function putMessageRating(
  messageId: string,
  value: "like" | "dislike",
  signal?: AbortSignal,
) {
  return request<MessageFeedback>(`/messages/${encodeURIComponent(messageId)}/rating`, {
    method: "PUT",
    body: { value },
    signal,
  });
}

export async function deleteMessageRating(messageId: string, signal?: AbortSignal) {
  await request<void>(`/messages/${encodeURIComponent(messageId)}/rating`, {
    method: "DELETE",
    signal,
  });
}

export async function reportMessage(
  messageId: string,
  description: string,
  signal?: AbortSignal,
) {
  return request<MessageFeedback>(`/messages/${encodeURIComponent(messageId)}/reports`, {
    method: "POST",
    body: {
      category: "other",
      description,
      diagnosticScope: {
        includeRunState: true,
        includeToolSummaries: true,
        includeConversation: false,
        includeAttachments: false,
      },
    },
    signal,
  });
}

export async function uploadAttachment(
  conversationId: string,
  file: File,
  source = "upload",
  signal?: AbortSignal,
) {
  const body = new FormData();
  body.set("file", file);
  body.set("source", source);
  return request<AttachmentSummary>(
    `/conversations/${encodeURIComponent(conversationId)}/attachments`,
    { method: "POST", body, signal },
  );
}

export async function uploadPastedText(
  conversationId: string,
  text: string,
  signal?: AbortSignal,
) {
  const body = new FormData();
  body.set("pasted_text", text);
  body.set("source", "paste");
  return request<AttachmentSummary>(
    `/conversations/${encodeURIComponent(conversationId)}/attachments`,
    { method: "POST", body, signal },
  );
}

export async function listComposerSuggestions(
  projectId: string,
  trigger: "@" | "$",
  query: string,
  signal?: AbortSignal,
) {
  return request<CursorPage<ComposerSuggestion>>("/composer/suggestions", {
    query: { project_id: projectId, trigger, query, limit: 12 },
    signal,
  });
}

export async function listArtifacts(projectId?: string, signal?: AbortSignal) {
  return request<CursorPage<ArtifactSummary>>("/artifacts", {
    query: { project_id: projectId, limit: 100 },
    signal,
  });
}

export async function createConversationShare(
  conversationId: string,
  anchorMessageId?: string | null,
  signal?: AbortSignal,
) {
  return request<ConversationShareCreated>("/conversation-shares", {
    method: "POST",
    body: { conversationId, anchorMessageId },
    signal,
  });
}

export async function getSharedConversation(token: string, signal?: AbortSignal) {
  return request<SharedConversationSnapshot>(`/conversation-shares/${encodeURIComponent(token)}`, { signal });
}

export async function downloadSharedArtifact(
  token: string,
  artifactId: string,
  version: number,
  signal?: AbortSignal,
): Promise<ArtifactDownload> {
  const response = await fetchApi(
    `/conversation-shares/${encodeURIComponent(token)}/artifacts/${encodeURIComponent(artifactId)}/download`,
    { query: { version }, signal },
  );
  return {
    blob: await response.blob(),
    fileName: downloadFileName(response, `shared-artifact-${artifactId}-v${version}`),
  };
}

export async function downloadSharedAttachment(
  token: string,
  attachmentId: string,
  signal?: AbortSignal,
): Promise<ArtifactDownload> {
  const response = await fetchApi(
    `/conversation-shares/${encodeURIComponent(token)}/attachments/${encodeURIComponent(attachmentId)}/download`,
    { signal },
  );
  return {
    blob: await response.blob(),
    fileName: downloadFileName(response, `shared-attachment-${attachmentId}`),
  };
}

export async function listExtensions(query?: string, signal?: AbortSignal) {
  return request<SkillExtension[]>("/extensions", { query: { query }, signal });
}

export async function listDeepAnalysisMissions(projectId: string, signal?: AbortSignal) {
  return request<DeepAnalysisMissionSummary[]>(
    `/projects/${encodeURIComponent(projectId)}/deep-analysis/missions`,
    { signal },
  );
}

export async function createDeepAnalysisMission(
  projectId: string,
  payload: CreateDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/projects/${encodeURIComponent(projectId)}/deep-analysis/missions`,
    { method: "POST", body: payload, signal },
  );
}

export async function listDeepAnalysisPatterns(projectId: string, signal?: AbortSignal) {
  return request<DeepAnalysisWorkflowPattern[]>(
    `/projects/${encodeURIComponent(projectId)}/deep-analysis/patterns`,
    { signal },
  );
}

export async function createDeepAnalysisPattern(
  projectId: string,
  payload: { missionId: string; name: string; description?: string },
) {
  return request<DeepAnalysisWorkflowPatternVersion>(
    `/projects/${encodeURIComponent(projectId)}/deep-analysis/patterns`,
    { method: "POST", body: payload },
  );
}

export async function createDeepAnalysisPatternVersion(
  patternId: string,
  payload: { missionId: string; changeSummary?: string },
) {
  return request<DeepAnalysisWorkflowPatternVersion>(
    `/deep-analysis/patterns/${encodeURIComponent(patternId)}/versions`,
    { method: "POST", body: payload },
  );
}

export async function publishDeepAnalysisPatternVersion(patternId: string, versionId: string) {
  return request<DeepAnalysisWorkflowPatternVersion>(
    `/deep-analysis/patterns/${encodeURIComponent(patternId)}/versions/${encodeURIComponent(versionId)}/publish`,
    { method: "POST" },
  );
}

export async function deleteDeepAnalysisPattern(patternId: string) {
  await request<void>(
    `/deep-analysis/patterns/${encodeURIComponent(patternId)}`,
    { method: "DELETE" },
  );
}

export async function getDeepAnalysisMission(missionId: string, signal?: AbortSignal) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}`,
    { signal },
  );
}

export async function listDeepAnalysisMissionEvents(
  missionId: string,
  afterSequence: number,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionEvent[]>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/events`,
    { query: { afterSequence }, signal },
  );
}

export async function getDeepAnalysisMissionProjection(
  missionId: string,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionProjection>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/projection`,
    { signal },
  );
}

export function openDeepAnalysisMissionEventStream(
  missionId: string,
  afterSequence: number,
  handlers: {
    onEvent: (event: DeepAnalysisMissionEvent) => void;
    onOpen?: () => void;
    onError?: (error: unknown) => void;
  },
) {
  const source = new EventSource(
    buildUrl(streamBase, `/deep-analysis/missions/${encodeURIComponent(missionId)}`, {
      after_sequence: Math.max(0, afterSequence),
    }),
    { withCredentials: true },
  );
  let lastDeliveredSequence = afterSequence;
  const handleMessage = (message: MessageEvent<string>) => {
    try {
      const parsed: unknown = JSON.parse(message.data);
      if (
        !isRecord(parsed)
        || parsed.missionId !== missionId
        || typeof parsed.sequence !== "number"
        || typeof parsed.type !== "string"
        || typeof parsed.createdAt !== "string"
        || !isRecord(parsed.payload)
      ) throw new Error("Mission event 형식이 올바르지 않습니다.");
      if (parsed.sequence <= lastDeliveredSequence) return;
      lastDeliveredSequence = parsed.sequence;
      handlers.onEvent(parsed as unknown as DeepAnalysisMissionEvent);
    } catch (error) {
      handlers.onError?.(error);
    }
  };
  source.onopen = () => handlers.onOpen?.();
  source.onerror = (event) => handlers.onError?.(event);
  source.addEventListener("mission_event", handleMessage as EventListener);
  return () => source.close();
}

export async function getDeepAnalysisMissionCosts(
  missionId: string,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionCosts>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/costs`,
    { signal },
  );
}

export async function getDeepAnalysisClaims(missionId: string, signal?: AbortSignal) {
  return request<DeepAnalysisClaim[]>(
    `/api/deep-analysis/missions/${missionId}/claims`,
    { signal },
  );
}

export async function getDeepAnalysisEvidence(missionId: string, signal?: AbortSignal) {
  return request<DeepAnalysisEvidence[]>(
    `/api/deep-analysis/missions/${missionId}/evidence`,
    { signal },
  );
}

export async function getDeepAnalysisOpenIssues(missionId: string, signal?: AbortSignal) {
  return request<DeepAnalysisOpenIssue[]>(
    `/api/deep-analysis/missions/${missionId}/open-issues`,
    { signal },
  );
}

export async function createDeepAnalysisMissionExport(
  missionId: string,
) {
  return request<DeepAnalysisMissionExport>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/exports`,
    { method: "POST", body: {}, idempotencyKey: createClientId() },
  );
}

export async function createDeepAnalysisWorkflowDraft(
  missionId: string,
  expectedRevision: number,
) {
  return request<DeepAnalysisWorkflowRevision>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/revisions`,
    { method: "POST", body: { expectedRevision } },
  );
}

export async function updateDeepAnalysisWorkflowDraft(
  missionId: string,
  payload: UpdateDeepAnalysisWorkflowDraftRequest,
) {
  return request<DeepAnalysisWorkflowRevision>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/draft`,
    { method: "PATCH", body: payload },
  );
}

export async function activateDeepAnalysisWorkflowDraft(
  missionId: string,
  expectedRevision: number,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/draft/activate`,
    { method: "POST", body: { expectedRevision } },
  );
}

export async function startDeepAnalysisMission(
  missionId: string,
  payload: StartDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/start`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function cancelDeepAnalysisMission(
  missionId: string,
  payload: CancelDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/cancel`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function pauseDeepAnalysisMission(
  missionId: string,
  payload: CancelDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/pause`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function resumeDeepAnalysisMission(
  missionId: string,
  payload: CancelDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/resume`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function retryDeepAnalysisMission(
  missionId: string,
  payload: RetryDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/retry`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function deleteDeepAnalysisMission(
  missionId: string,
  expectedRevision: number,
  signal?: AbortSignal,
) {
  await request<void>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}`,
    { method: "DELETE", query: { expected_revision: expectedRevision }, signal },
  );
}

export async function updateDeepAnalysisMission(
  missionId: string,
  payload: UpdateDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}`,
    { method: "PATCH", body: payload, signal },
  );
}

export async function restartDeepAnalysisMission(
  missionId: string,
  payload: RestartDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/restart`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function getDeepAnalysisResearchInspector(
  missionId: string,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisResearchInspector>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/research-inspector`,
    { signal },
  );
}

export async function getDeepAnalysisRefreshPreview(
  missionId: string,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisRefreshPreview>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/refresh-preview`,
    { signal },
  );
}

export async function steerDeepAnalysisMission(
  missionId: string,
  payload: SteerDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/steer`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function refreshDeepAnalysisMission(
  missionId: string,
  payload: RestartDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/refresh`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function regenerateDeepAnalysisWorkflow(
  missionId: string,
  payload: RegenerateDeepAnalysisWorkflowRequest,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/workflow/regenerate`,
    { method: "POST", body: payload, idempotencyKey: createClientId() },
  );
}

export async function moveDeepAnalysisMission(
  missionId: string,
  projectId: string,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionSummary>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/move`,
    { method: "POST", body: { projectId }, signal },
  );
}

export async function answerDeepAnalysisDecision(
  missionId: string,
  decisionId: string,
  payload: AnswerDeepAnalysisDecisionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/decisions/${encodeURIComponent(decisionId)}/answer`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function runDeepAnalysisQualityGate(
  missionId: string,
  payload: StartDeepAnalysisMissionRequest,
  signal?: AbortSignal,
) {
  return request<DeepAnalysisMissionDetail>(
    `/deep-analysis/missions/${encodeURIComponent(missionId)}/quality-gate`,
    { method: "POST", body: payload, signal, idempotencyKey: createClientId() },
  );
}

export async function listKnowledgeSpaces(signal?: AbortSignal) {
  return request<KnowledgeSpace[]>("/knowledge/spaces", { signal });
}
export async function createKnowledgeSpace(payload: CreateKnowledgeSpaceRequest, signal?: AbortSignal) {
  return request<KnowledgeSpace>("/knowledge/spaces", { method: "POST", body: payload, signal });
}
export async function updateKnowledgeSpace(spaceId: string, payload: UpdateKnowledgeSpaceRequest, signal?: AbortSignal) {
  return request<KnowledgeSpace>(`/knowledge/spaces/${encodeURIComponent(spaceId)}`, { method: "PATCH", body: payload, signal });
}
export async function listKnowledgeTags(spaceId: string, signal?: AbortSignal) {
  return request<KnowledgeTag[]>("/knowledge/tags", { query: { spaceId }, signal });
}
export async function createKnowledgeTag(payload: CreateKnowledgeTagRequest, signal?: AbortSignal) {
  return request<KnowledgeTag>("/knowledge/tags", { method: "POST", body: payload, signal });
}
export async function updateKnowledgeTag(tagId: string, payload: UpdateKnowledgeTagRequest, signal?: AbortSignal) {
  return request<KnowledgeTag>(`/knowledge/tags/${encodeURIComponent(tagId)}`, { method: "PATCH", body: payload, signal });
}
export async function listKnowledgeDocuments(filters: { spaceId?: string; projectId?: string; query?: string; limit?: number } = {}, signal?: AbortSignal) {
  return request<KnowledgeDocumentSummary[]>("/knowledge/documents", { query: filters, signal });
}
export async function getKnowledgeDocument(documentId: string, signal?: AbortSignal) {
  return request<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(documentId)}`, { signal });
}
export async function deleteKnowledgeDocument(documentId: string, signal?: AbortSignal) {
  return request<void>(`/knowledge/documents/${encodeURIComponent(documentId)}`, { method: "DELETE", signal });
}
export async function saveKnowledgeDocumentFromMessage(messageId: string, signal?: AbortSignal) {
  return request<KnowledgeDocument>(`/knowledge/documents/from-message/${encodeURIComponent(messageId)}`, { method: "POST", signal });
}
export async function batchTagKnowledgeDocuments(payload: { spaceId: string; providerId: string; modelKey: string }, signal?: AbortSignal) {
  return request<{ requestedCount: number; taggedCount: number; failedCount: number; remainingCount: number }>("/knowledge/documents/tag-batch", { method: "POST", body: payload, signal });
}
export async function getKnowledgeGraph(spaceId?: string, signal?: AbortSignal) {
  return request<KnowledgeGraphResponse>("/knowledge/graph", { query: { spaceId }, signal });
}
export async function getWebSourceContent(
  conversationId: string,
  runId: string,
  sourceId: string,
  offset = 0,
  limit = 4_000,
  signal?: AbortSignal,
) {
  return request<WebSourceContentPage>(
    `/conversations/${encodeURIComponent(conversationId)}/runs/${encodeURIComponent(runId)}/sources/${encodeURIComponent(sourceId)}/content`,
    { query: { offset, limit }, signal },
  );
}

export async function getAnnouncementUnreadCount(signal?: AbortSignal) {
  return request<NotificationUnreadCount>("/notifications/announcements/unread-count", { signal });
}

export async function markAnnouncementRead(announcementId: string, signal?: AbortSignal) {
  return request<AnnouncementItem>(`/notifications/announcements/${encodeURIComponent(announcementId)}/read`, {
    method: "POST",
    signal,
  });
}

export async function listSkillCatalog(
  filters: {
    query?: string;
    category?: string;
    tag?: string;
    sort?: "popular" | "runs" | "likes" | "recent" | "name";
    offset?: number;
    limit?: number;
  } = {},
  signal?: AbortSignal,
) {
  return request<SkillCatalogResponse>("/extensions/catalog", {
    query: filters,
    signal,
  });
}

export async function setSkillCatalogLike(
  extensionId: string,
  liked: boolean,
  signal?: AbortSignal,
) {
  return request<SkillCatalogLikeResult>(`/extensions/${encodeURIComponent(extensionId)}/like`, {
    method: liked ? "PUT" : "DELETE",
    signal,
  });
}

export async function syncRepositoryExtensions(signal?: AbortSignal) {
  return request<{ skillsChanged: number; mcpChanged: number; revision: string }>("/extensions/repository-sync", {
    method: "POST",
    signal,
  });
}

export async function getRepositoryExtensionState(signal?: AbortSignal) {
  return request<{ revision: string }>("/extensions/repository-state", { signal });
}

export async function listTrashedExtensions(query?: string, signal?: AbortSignal) {
  return request<SkillExtension[]>("/extensions/trash", { query: { query }, signal });
}

export async function getExtensionVersion(versionId: string, signal?: AbortSignal) {
  return request<SkillVersion>(`/extension-versions/${encodeURIComponent(versionId)}`, { signal });
}

export async function checkoutSkillDraft(extensionId: string, signal?: AbortSignal) {
  return request<SkillDraft>(`/extensions/${encodeURIComponent(extensionId)}/draft`, {
    method: "POST",
    signal,
  });
}

export async function getSkillDraft(extensionId: string, signal?: AbortSignal) {
  return request<SkillDraft>(`/extensions/${encodeURIComponent(extensionId)}/draft`, {
    signal,
  });
}

export async function updateExtensionMetadata(
  extensionId: string,
  payload: { name: string; description: string; tags?: string[] },
  signal?: AbortSignal,
) {
  return request<SkillExtension>(`/extensions/${encodeURIComponent(extensionId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function deleteExtension(extensionId: string, signal?: AbortSignal) {
  await request<void>(`/extensions/${encodeURIComponent(extensionId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function restoreExtension(extensionId: string, signal?: AbortSignal) {
  return request<SkillExtension>(`/extensions/${encodeURIComponent(extensionId)}/restore`, {
    method: "POST",
    signal,
  });
}

export async function createSkill(
  payload: { name: string; description: string; projectId?: string; files: Record<string, string> },
  signal?: AbortSignal,
) {
  return request<SkillExtension>("/extensions", {
    method: "POST",
    body: {
      kind: "skill",
      name: payload.name,
      description: payload.description,
      projectId: payload.projectId,
      package: { files: payload.files },
    },
    signal,
  });
}

export async function updateSkillDraft(
  draft: SkillDraft,
  files: Record<string, string>,
  changeSummary: string,
  signal?: AbortSignal,
) {
  return request<SkillDraft>(`/skill-drafts/${encodeURIComponent(draft.id)}`, {
    method: "PATCH",
    body: {
      expectedRevision: draft.revision,
      expectedDigest: draft.digest,
      package: { files },
      changeSummary,
    },
    signal,
  });
}

export async function saveSkillVersion(draft: SkillDraft, signal?: AbortSignal) {
  return request<SkillVersion>(`/skill-drafts/${encodeURIComponent(draft.id)}/save-version`, {
    method: "POST",
    body: {
      expectedRevision: draft.revision,
      expectedDigest: draft.digest,
      baseVersionId: draft.baseVersionId,
      manifest: {},
    },
    signal,
  });
}

export async function addSkillOwnership(
  skillId: string,
  userId: string,
  role: "owner" | "maintainer" = "owner",
  signal?: AbortSignal,
) {
  return request<SkillExtension>(`/skills/${encodeURIComponent(skillId)}/ownerships`, {
    method: "POST",
    body: { userId, role },
    signal,
  });
}

export async function removeSkillOwnership(
  skillId: string,
  ownershipId: string,
  signal?: AbortSignal,
) {
  await request<void>(
    `/skills/${encodeURIComponent(skillId)}/ownerships/${encodeURIComponent(ownershipId)}`,
    { method: "DELETE", signal },
  );
}

export async function listExtensionInstallations(projectId?: string, signal?: AbortSignal) {
  return request<ExtensionInstallation[]>("/extension-installations", {
    query: { project_id: projectId },
    signal,
  });
}

export async function installExtensionVersion(
  versionId: string,
  signal?: AbortSignal,
) {
  return request<ExtensionInstallation>("/extension-installations", {
    method: "POST",
    body: { versionId, scopeType: "user", enabled: true, settings: {} },
    signal,
  });
}

export async function uninstallExtension(installationId: string, signal?: AbortSignal) {
  await request<void>(`/extension-installations/${encodeURIComponent(installationId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function listMcpCatalog(signal?: AbortSignal) {
  return request<McpDefinition[]>("/mcp/catalog", { signal });
}

export async function listMcpInstallations(projectId?: string, signal?: AbortSignal) {
  return request<McpInstallation[]>("/mcp/installations", {
    query: { project_id: projectId },
    signal,
  });
}

export async function installMcp(
  definitionId: string,
  configurationRevisionId: string,
  scopeType: "user" | "project",
  scopeId: string | undefined,
  toolAllowlist: string[],
  signal?: AbortSignal,
) {
  return request<McpInstallation>("/mcp/installations", {
    method: "POST",
    body: {
      definitionId,
      configurationRevisionId,
      scopeType,
      scopeId,
      enabled: true,
      toolAllowlist,
    },
    signal,
  });
}

export async function setMcpInstallationEnabled(
  installationId: string,
  enabled: boolean,
  signal?: AbortSignal,
) {
  return request<McpInstallation>(`/mcp/installations/${encodeURIComponent(installationId)}`, {
    method: "PATCH",
    body: { enabled },
    signal,
  });
}

export async function updateExtensionInstallationProjects(
  installationId: string,
  projectIds: string[] | null,
  signal?: AbortSignal,
) {
  return request<ExtensionInstallation>(`/extension-installations/${encodeURIComponent(installationId)}`, {
    method: "PATCH",
    body: { projectIds },
    signal,
  });
}

export async function setExtensionInstallationEnabled(
  installationId: string,
  enabled: boolean,
  signal?: AbortSignal,
) {
  return request<ExtensionInstallation>(`/extension-installations/${encodeURIComponent(installationId)}`, {
    method: "PATCH",
    body: { enabled },
    signal,
  });
}

export async function updateMcpInstallationProjects(
  installationId: string,
  projectIds: string[] | null,
  signal?: AbortSignal,
) {
  return request<McpInstallation>(`/mcp/installations/${encodeURIComponent(installationId)}`, {
    method: "PATCH",
    body: { projectIds },
    signal,
  });
}

export async function verifyMcpInstallation(
  installationId: string,
  signal?: AbortSignal,
) {
  return request<McpInstallation>(
    `/mcp/installations/${encodeURIComponent(installationId)}/verify`,
    { method: "POST", body: {}, signal },
  );
}

export async function testMcpInstallationAnswer(
  installationId: string,
  projectId: string,
  prompt: string,
  signal?: AbortSignal,
) {
  return request<McpAnswerTestResult>(
    `/mcp/installations/${encodeURIComponent(installationId)}/answer-test`,
    { method: "POST", body: { projectId, prompt }, signal },
  );
}

export async function uninstallMcp(installationId: string, signal?: AbortSignal) {
  await request<void>(`/mcp/installations/${encodeURIComponent(installationId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function bindMcpSecret(
  installationId: string,
  secretName: string,
  secretRef: string,
  signal?: AbortSignal,
) {
  return request<McpInstallation>(
    `/mcp/installations/${encodeURIComponent(installationId)}/secrets/${encodeURIComponent(secretName)}`,
    { method: "PUT", body: { secretRef }, signal },
  );
}

export async function unbindMcpSecret(
  installationId: string,
  secretName: string,
  signal?: AbortSignal,
) {
  await request<void>(
    `/mcp/installations/${encodeURIComponent(installationId)}/secrets/${encodeURIComponent(secretName)}`,
    { method: "DELETE", signal },
  );
}

export async function listAdminMcpDefinitions(signal?: AbortSignal) {
  return request<McpDefinition[]>("/admin/mcp-definitions", { signal });
}

export async function createAdminMcpDefinition(
  payload: McpDefinitionCreateRequest,
  signal?: AbortSignal,
) {
  return request<McpDefinition>("/admin/mcp-definitions", {
    method: "POST",
    body: payload,
    signal,
  });
}

export async function createAdminMcpRevision(
  definitionId: string,
  configuration: McpConfiguration,
  signal?: AbortSignal,
) {
  return request<McpDefinition>(
    `/admin/mcp-definitions/${encodeURIComponent(definitionId)}/revisions`,
    { method: "POST", body: { configuration }, signal },
  );
}

export async function approveAdminMcpRevision(
  definitionId: string,
  configurationRevisionId: string,
  signal?: AbortSignal,
) {
  return request<McpDefinition>(
    `/admin/mcp-definitions/${encodeURIComponent(definitionId)}/approve`,
    { method: "POST", body: { configurationRevisionId }, signal },
  );
}

export async function setAdminMcpDefinitionStatus(
  definitionId: string,
  status: "disabled" | "revoked",
  reason: string,
  signal?: AbortSignal,
) {
  return request<McpDefinition>(
    `/admin/mcp-definitions/${encodeURIComponent(definitionId)}/status`,
    { method: "PATCH", body: { status, reason }, signal },
  );
}

export async function listScheduledTasks(projectId?: string, signal?: AbortSignal) {
  return request<ScheduledTask[]>("/scheduled-tasks", { query: { project_id: projectId }, signal });
}

export async function createScheduledTask(
  payload: {
    projectId: string;
    name: string;
    instructions: string;
    scheduleKind: ScheduleKind;
    scheduleConfig: Record<string, number>;
    execution: CurrentSettings["execution"];
  },
  signal?: AbortSignal,
) {
  return request<ScheduledTask>("/scheduled-tasks", {
    method: "POST",
    body: {
      ...payload,
      timezone: "Asia/Seoul",
      contextMode: "new_session_per_run",
      extensionSnapshotPolicy: "pinned",
      deliveryPolicy: {},
      enabled: true,
      maxAttempts: 1,
      timeoutSeconds: 900,
    },
    signal,
  });
}

export async function updateScheduledTask(
  taskId: string,
  payload: {
    projectId: string;
    name: string;
    instructions: string;
    scheduleKind: ScheduleKind;
    scheduleConfig: Record<string, number>;
    execution: CurrentSettings["execution"];
  },
  signal?: AbortSignal,
) {
  return request<ScheduledTask>(`/scheduled-tasks/${encodeURIComponent(taskId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function setScheduledTaskEnabled(taskId: string, enabled: boolean, signal?: AbortSignal) {
  return request<ScheduledTask>(`/scheduled-tasks/${encodeURIComponent(taskId)}/${enabled ? "enable" : "disable"}`, {
    method: "POST",
    signal,
  });
}

export async function deleteScheduledTask(taskId: string, signal?: AbortSignal) {
  return request<void>(`/scheduled-tasks/${encodeURIComponent(taskId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function runScheduledTaskNow(taskId: string, signal?: AbortSignal) {
  return request<ScheduledRun>(`/scheduled-tasks/${encodeURIComponent(taskId)}/run-now`, {
    method: "POST",
    idempotencyKey: createClientId(),
    signal,
  });
}

export async function listScheduledRuns(taskId: string, signal?: AbortSignal) {
  return request<ScheduledRun[]>(`/scheduled-tasks/${encodeURIComponent(taskId)}/runs`, {
    query: { limit: 50 },
    signal,
  });
}

export async function listHelpItems(signal?: AbortSignal) {
  return request<HelpItemList>("/help/items", { signal });
}

export async function createHelpItem(
  payload: { kind: HelpItemKind; title: string; parentId: string | null; markdownContent?: string },
  signal?: AbortSignal,
) {
  return request<HelpItem>("/help/items", { method: "POST", body: payload, signal });
}

export async function updateHelpItem(
  itemId: string,
  payload: { title: string; markdownContent: string; expectedRevision: number; parentId?: string | null },
  signal?: AbortSignal,
) {
  return request<HelpItem>(`/help/items/${encodeURIComponent(itemId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function deleteHelpItem(itemId: string, signal?: AbortSignal) {
  return request<void>(`/help/items/${encodeURIComponent(itemId)}`, { method: "DELETE", signal });
}

export async function listAdminUsers(
  filters: { query?: string; role?: string; status?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
) {
  return request<AdminUserList>("/admin/users", { query: filters, signal });
}

export async function listAdminAnnouncements(query = "", signal?: AbortSignal) {
  return request<AnnouncementList>("/admin/announcements", {
    query: { query, limit: 200 },
    signal,
  });
}

export async function createAdminAnnouncement(payload: AnnouncementMutationRequest, signal?: AbortSignal) {
  return request<AnnouncementItem>("/admin/announcements", {
    method: "POST",
    body: payload,
    signal,
  });
}

export async function updateAdminAnnouncement(
  announcementId: string,
  payload: AnnouncementMutationRequest,
  signal?: AbortSignal,
) {
  return request<AnnouncementItem>(`/admin/announcements/${encodeURIComponent(announcementId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function deleteAdminAnnouncement(announcementId: string, signal?: AbortSignal) {
  return request<void>(`/admin/announcements/${encodeURIComponent(announcementId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function getAdminUsageStatistics(days: 0 | 30 | 90 = 30, signal?: AbortSignal) {
  return request<AdminUsageStatistics>("/admin/usage-statistics", { query: { days }, signal });
}

export async function getAdminRunSafetySettings(signal?: AbortSignal) {
  return request<AdminRunSafetySettings>("/admin/run-safety", { signal });
}

export async function updateAdminRunSafetySettings(payload: AdminRunSafetySettings, signal?: AbortSignal) {
  return request<AdminRunSafetySettings>("/admin/run-safety", {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function emergencyStopAllAdminRuns(signal?: AbortSignal) {
  return request<AdminEmergencyStopResult>("/admin/run-safety/emergency-stop", {
    method: "POST",
    body: { reason: "관리자 비상 중단" },
    signal,
  });
}

export async function createAdminUser(payload: CreateAdminUserRequest, signal?: AbortSignal) {
  return request<AdminUser>("/admin/users", { method: "POST", body: payload, signal });
}

export async function updateAdminUser(userId: string, payload: UpdateAdminUserRequest, signal?: AbortSignal) {
  return request<AdminUser>(`/admin/users/${encodeURIComponent(userId)}`, {
    method: "PATCH",
    body: payload,
    signal,
  });
}

export async function resetAdminUserPassword(
  userId: string,
  newPassword: string,
  mustChangePassword: boolean,
  signal?: AbortSignal,
) {
  return request<{ user: AdminUser; revokedSessionCount: number }>(
    `/admin/users/${encodeURIComponent(userId)}/reset-password`,
    { method: "POST", body: { newPassword, mustChangePassword }, signal },
  );
}

export async function listAdminConversations(
  filters: { query?: string; ownerLoginId?: string; projectId?: string; status?: string; feedbackOnly?: boolean; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
) {
  return request<AdminConversationList>("/admin/conversations", {
    query: {
      query: filters.query,
      owner_login_id: filters.ownerLoginId,
      project_id: filters.projectId,
      status: filters.status,
      feedback_only: filters.feedbackOnly || undefined,
      limit: filters.limit,
      offset: filters.offset,
    },
    signal,
  });
}

export async function getAdminConversation(conversationId: string, signal?: AbortSignal) {
  return request<AdminConversationDetail>(`/admin/conversations/${encodeURIComponent(conversationId)}`, { signal });
}

export async function exportAdminConversations(
  filters: { query?: string; feedbackOnly?: boolean; limit?: number } = {},
  signal?: AbortSignal,
): Promise<ArtifactDownload> {
  const response = await fetchApi("/admin/conversations/export.xlsx", {
    query: {
      query: filters.query,
      feedback_only: filters.feedbackOnly || undefined,
      limit: filters.limit,
    },
    signal,
  });
  return {
    blob: await response.blob(),
    fileName: downloadFileName(response, "lumina_conversations.xlsx"),
  };
}

export async function listAdminAuditEvents(
  filters: { action?: string; actorUserId?: string; targetType?: string; targetId?: string; limit?: number; offset?: number } = {},
  signal?: AbortSignal,
) {
  return request<AdminAuditList>("/admin/audit-events", {
    query: {
      action: filters.action,
      actor_user_id: filters.actorUserId,
      target_type: filters.targetType,
      target_id: filters.targetId,
      limit: filters.limit,
      offset: filters.offset,
    },
    signal,
  });
}

export async function getAdminAuditTraffic(minutes = 60, signal?: AbortSignal) {
  return request<AdminAuditTraffic>("/admin/audit-traffic", {
    query: { minutes },
    signal,
  });
}

export async function listMemories(
  query?: string,
  status: "active" | "pending" | "dismissed" | "superseded" = "active",
  signal?: AbortSignal,
) {
  return request<UserMemory[]>("/memories", { query: { query, status }, signal });
}

export async function updateMemory(
  memoryId: string,
  changes: {
    category?: string;
    fact?: string;
    displayText?: string;
    status?: "active" | "dismissed";
  },
  signal?: AbortSignal,
) {
  return request<UserMemory>(`/memories/${encodeURIComponent(memoryId)}`, {
    method: "PATCH",
    body: changes,
    signal,
  });
}

export async function deleteMemory(memoryId: string, signal?: AbortSignal) {
  await request<void>(`/memories/${encodeURIComponent(memoryId)}`, {
    method: "DELETE",
    signal,
  });
}

export async function getMemorySettings(signal?: AbortSignal) {
  return request<MemorySettings>("/memory-settings", { signal });
}

export async function updateMemorySettings(mode: MemoryLearningMode, signal?: AbortSignal) {
  return request<MemorySettings>("/memory-settings", {
    method: "PATCH",
    body: { mode },
    signal,
  });
}

export async function optimizeMemories(signal?: AbortSignal) {
  return request<MemoryOptimizationResult>("/memories/optimize", {
    method: "POST",
    signal,
  });
}

export async function listProjectMemories(
  projectId: string,
  includeHistory = false,
  signal?: AbortSignal,
) {
  return request<ProjectMemory[]>(`/projects/${encodeURIComponent(projectId)}/memories`, {
    query: { includeHistory },
    signal,
  });
}

export async function getProjectMemoryHistory(
  projectId: string,
  memoryKey: string,
  signal?: AbortSignal,
) {
  return request<ProjectMemoryHistory>(
    `/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryKey)}`,
    { signal },
  );
}

export async function listProjectLearningProposals(
  projectId: string,
  status?: ProjectLearningProposalStatus,
  signal?: AbortSignal,
) {
  return request<ProjectLearningProposal[]>(
    `/projects/${encodeURIComponent(projectId)}/learning-proposals`,
    { query: { status }, signal },
  );
}

export async function createProjectLearningProposal(
  projectId: string,
  payload: CreateProjectLearningProposalRequest,
  signal?: AbortSignal,
) {
  return request<ProjectLearningProposal>(
    `/projects/${encodeURIComponent(projectId)}/learning-proposals`,
    { method: "POST", body: payload, signal },
  );
}

export async function reviewProjectLearningProposal(
  projectId: string,
  proposalId: string,
  action: "approve" | "reject",
  note = "",
  signal?: AbortSignal,
) {
  return request<ProjectLearningProposal>(
    `/projects/${encodeURIComponent(projectId)}/learning-proposals/${encodeURIComponent(proposalId)}/${action}`,
    { method: "POST", body: { note }, signal },
  );
}

export async function applyProjectLearningProposal(
  projectId: string,
  proposalId: string,
  signal?: AbortSignal,
) {
  return request<ProjectLearningMutationResult>(
    `/projects/${encodeURIComponent(projectId)}/learning-proposals/${encodeURIComponent(proposalId)}/apply`,
    { method: "POST", signal },
  );
}

export async function rollbackProjectLearningProposal(
  projectId: string,
  proposalId: string,
  signal?: AbortSignal,
) {
  return request<ProjectLearningMutationResult>(
    `/projects/${encodeURIComponent(projectId)}/learning-proposals/${encodeURIComponent(proposalId)}/rollback`,
    { method: "POST", signal },
  );
}

export const api = {
  auth: { getSession: getAuthSession, login, logout },
  finance: { getUsdKrwExchangeRate },
  notifications: {
    list: listNotifications,
    listAnnouncements,
    getUnreadCount: getNotificationUnreadCount,
    getAnnouncementUnreadCount,
    markRead: markNotificationRead,
    markAnnouncementRead,
    markAllRead: markAllNotificationsRead,
    delete: deleteNotification,
    deleteAll: deleteAllNotifications,
  },
  projects: { list: listProjects, create: createProject, update: updateProject, archive: archiveProject },
  instructions: {
    getPersonal: getPersonalInstructions,
    updatePersonal: updatePersonalInstructions,
    getProject: getProjectInstructions,
    updateProject: updateProjectInstructions,
    getOrganization: getOrganizationInstructions,
    updateOrganization: updateOrganizationInstructions,
    listRuntimePrompts,
    updateRuntimePrompt,
    getOrganizationRevision: getOrganizationInstructionRevision,
    updateOrganizationRevision: updateOrganizationInstructionRevision,
    updateOrganizationRevisionLabel: updateOrganizationInstructionRevisionLabel,
  },
  settings: { getCurrent: getCurrentSettings, updateCurrent: updateCurrentSettings },
  providers: { list: listProviders, listModels: listProviderModels, getCatalog: getProviderCatalog },
  adminProviders: {
    list: listAdminProviders,
    listModels: listAdminProviderModels,
    getInitialExecution: getAdminInitialExecution,
    updateInitialExecution: updateAdminInitialExecution,
    updateAvailability: updateAdminProviderAvailability,
    updateModel: updateAdminProviderModel,
  },
  conversations: {
    list: listConversations,
    searchContent: searchConversationContent,
    create: createConversation,
    update: updateConversation,
    move: moveConversation,
    delete: deleteConversation,
    branch: branchConversation,
    export: exportConversation,
    getTurnSets: getConversationTurnSets,
    getSourceContent: getWebSourceContent,
  },
  runs: { start: startRun, action: sendRunAction, getSnapshot: getRunSnapshot, getSnapshots: getRunSnapshots, openStream: openRunEventStream },
  artifacts: {
    list: listArtifacts,
    get: getArtifact,
    createFromMessage: createMessageMarkdownArtifact,
    getVersion: getArtifactVersion,
    getDraft: getArtifactDraft,
    saveVersion: saveArtifactVersion,
    saveDraft: saveArtifactDraft,
    downloadVersion: downloadArtifactVersion,
  },
  messages: {
    putRating: putMessageRating,
    deleteRating: deleteMessageRating,
    report: reportMessage,
  },
  attachments: { upload: uploadAttachment, uploadPastedText },
  composer: { listSuggestions: listComposerSuggestions },
  sharing: {
    create: createConversationShare,
    get: getSharedConversation,
    downloadArtifact: downloadSharedArtifact,
    downloadAttachment: downloadSharedAttachment,
  },
};
