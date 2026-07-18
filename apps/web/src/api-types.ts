export type UUID = string;
export type IsoDateTime = string;

export interface CursorPage<T> {
  items: T[];
  nextCursor: string | null;
  hasMore: boolean;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  requestId?: string;
  field?: string;
  details?: unknown;
}

export type UserRole = "user" | "admin";
export type UserStatus = "invited" | "active" | "locked" | "disabled";

export interface UserAccount {
  id: UUID;
  organizationId: UUID;
  loginName: string;
  loginDomain: string;
  email: string;
  displayName: string | null;
  affiliation: string | null;
  role: UserRole;
  status: UserStatus;
}

export interface AuthSession {
  user: UserAccount;
  expiresAt: IsoDateTime;
  csrfToken: string;
}

export interface NotificationDeepLink {
  target?: "conversation" | "artifact" | "admin";
  projectId?: UUID;
  conversationId?: UUID;
  runId?: UUID;
  artifactId?: UUID;
  scheduledTaskId?: UUID;
  scheduledRunId?: UUID;
  adminUserId?: UUID;
}

export interface RegistrationRequest {
  email: string;
  displayName: string;
  affiliation: string;
  role: UserRole;
  password: string;
}

export interface RegistrationResponse {
  loginId: string;
  status: "invited";
  message: string;
}

export interface NotificationItem {
  id: UUID;
  kind: string;
  title: string;
  body: string;
  deepLink: NotificationDeepLink;
  readAt: IsoDateTime | null;
  createdAt: IsoDateTime;
}

export interface NotificationList {
  items: NotificationItem[];
  unreadCount: number;
  nextOffset: number | null;
  hasMore: boolean;
}

export interface NotificationUnreadCount {
  unreadCount: number;
}

export interface NotificationReadAllResult {
  updatedCount: number;
  readAt: IsoDateTime;
}

export interface LoginRequest {
  loginName: string;
  loginDomain: string;
  password: string;
}

export type ProjectType = "personal" | "shared" | "system";
export type ProjectRole = "owner" | "admin" | "member" | "viewer";
export type ProjectMembershipStatus = "active" | "revoked";

export interface ProjectSummary {
  id: UUID;
  name: string;
  description: string | null;
  projectType: ProjectType;
  role: ProjectRole;
  isDefault: boolean;
  concept: string;
  conceptRevision: number;
  conceptHash: string;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface CreateProjectRequest {
  name: string;
  description?: string;
}

export interface UpdateProjectRequest {
  name?: string;
  description?: string;
  concept?: string;
  archived?: boolean;
}

export type InstructionScope = "personal" | "project" | "organization";

export interface InstructionDocument {
  scope: InstructionScope;
  scopeId: UUID;
  content: string;
  revision: number;
  digest: string;
  editable: boolean;
  appliesToSharedProjects: boolean;
  updatedAt: IsoDateTime;
  revisionLabels?: Record<string, string>;
}

export interface UpdateInstructionRequest {
  content: string;
  expectedRevision: number;
  expectedDigest: string;
}

export interface ProjectFileVersion {
  id: UUID;
  version: number;
  contentHash: string;
  mimeType: string;
  size: number;
  originalFilename: string;
  extractionStatus: string;
  extractionVersion: string | null;
  locatorMap: Record<string, unknown>;
  sourceRunId: UUID | null;
  changeReason: string | null;
  createdByUserId: UUID;
  createdAt: IsoDateTime;
}

export interface ProjectFileSummary {
  id: UUID;
  projectId: UUID;
  logicalPath: string;
  displayName: string;
  status: "active" | "deleted";
  revision: number;
  currentVersion: number;
  contentHash: string;
  mimeType: string;
  size: number;
  extractionStatus: string;
  createdByUserId: UUID;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface ProjectFileDetail extends ProjectFileSummary {
  versions: ProjectFileVersion[];
}

export interface AnnouncementItem {
  id: UUID;
  title: string;
  body: string;
  author: { id: UUID; loginId: string; displayName: string | null } | null;
  readAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface AnnouncementList {
  items: AnnouncementItem[];
  total: number;
  unreadCount: number;
}

export type DeepAnalysisAutonomyMode = "guided" | "balanced" | "autonomous";

export interface DeepAnalysisMissionSummary {
  id: UUID;
  projectId: UUID;
  title: string;
  objective: string;
  status: string;
  startMode: string;
  autonomyMode: DeepAnalysisAutonomyMode;
  budgetMicrousd: number | null;
  spentMicrousd: number;
  revision: number;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface DeepAnalysisWorkflowNode {
  id: UUID;
  nodeKey: string;
  nodeType: string;
  title: string;
  purpose: string;
  status: string;
  sequence: number;
  positionX: number;
  positionY: number;
  config: Record<string, unknown>;
  outputSummary: string;
  estimatedCostMicrousd: number;
  actualCostMicrousd: number;
}

export interface DeepAnalysisWorkflowEdge {
  id: UUID;
  sourceNodeKey: string;
  targetNodeKey: string;
  edgeType: string;
}

export interface DeepAnalysisWorkflowRevision {
  id: UUID;
  revisionNumber: number;
  state: string;
  source: string;
  reason: string;
  graphDigest: string;
  nodes: DeepAnalysisWorkflowNode[];
  edges: DeepAnalysisWorkflowEdge[];
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface DeepAnalysisMissionDetail extends DeepAnalysisMissionSummary {
  charter: Record<string, unknown>;
  completionContract: Record<string, unknown>;
  workflow: DeepAnalysisWorkflowRevision;
}

export interface CreateDeepAnalysisMissionRequest {
  title: string;
  objective?: string;
  autonomyMode?: DeepAnalysisAutonomyMode;
  budgetMicrousd?: number | null;
}

export interface UpdateDeepAnalysisMissionRequest {
  expectedRevision: number;
  title?: string;
  objective?: string;
  autonomyMode?: DeepAnalysisAutonomyMode;
  budgetMicrousd?: number;
}

export type KnowledgeSourceType = "file" | "url" | "conversation" | "text" | "connector";
export type KnowledgeObjectKind = "entity" | "text" | "number" | "date" | "boolean" | "json";

export interface KnowledgeSpace {
  id: UUID;
  organizationId: UUID;
  ownerUserId: UUID | null;
  spaceType: string;
  name: string;
  description: string;
  purpose: string;
  visibility: "private" | "organization";
  status: string;
  settingsRevision: number;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface CreateKnowledgeSpaceRequest {
  name: string;
  description?: string;
  purpose?: string;
}

export interface UpdateKnowledgeSpaceRequest {
  expectedRevision: number;
  name?: string;
  description?: string;
  purpose?: string;
}

export interface KnowledgeAutoCaptureSetting {
  enabled: boolean;
  spaceId: UUID | null;
  mode: "research";
}

export interface UpdateKnowledgeAutoCaptureRequest {
  enabled: boolean;
  spaceId?: UUID | null;
}

export interface KnowledgeEvidenceSegment {
  id: UUID;
  sourceRevisionId: UUID;
  segmentOrdinal: number;
  locator: Record<string, unknown>;
  text: string;
  textDigest: string;
  language: string | null;
  tokenCount: number;
}

export interface KnowledgeSource {
  id: UUID;
  spaceId: UUID;
  sourceType: KnowledgeSourceType;
  title: string;
  canonicalLocator: string | null;
  status: string;
  revision: {
    id: UUID;
    revisionNumber: number;
    contentDigest: string;
    mediaType: string;
    byteSize: number;
    capturedAt: IsoDateTime;
  };
  evidenceSegments: KnowledgeEvidenceSegment[];
}

export type KnowledgeIngestionStatus = "queued" | "running" | "completed" | "failed";

export interface KnowledgeIngestionJob {
  id: UUID;
  spaceId: UUID;
  sourceId: UUID;
  sourceRevisionId: UUID;
  status: KnowledgeIngestionStatus;
  providerId: string;
  modelKey: string;
  extractorVersion: string;
  inputSegmentCount: number;
  inputCharacterCount: number;
  entityCount: number;
  statementCount: number;
  inputTokens: number;
  outputTokens: number;
  errorCode: string | null;
  errorMessage: string | null;
  queuedAt: IsoDateTime;
  startedAt: IsoDateTime | null;
  finishedAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface CreateKnowledgeSourceRequest {
  sourceType: KnowledgeSourceType;
  title: string;
  canonicalLocator?: string | null;
  contentDigest: string;
  mediaType: string;
  byteSize?: number;
  capturedText?: string | null;
  evidenceSegments?: Array<{
    text: string;
    locator?: Record<string, unknown>;
    language?: string | null;
    tokenCount?: number;
  }>;
}

export interface KnowledgeEntity {
  id: UUID;
  spaceId: UUID;
  entityType: string;
  canonicalName: string;
  description: string;
  status: string;
  depth?: number;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface CreateKnowledgeEntityRequest {
  entityType: string;
  canonicalName: string;
  description?: string;
}

export interface KnowledgeStatement {
  id: UUID;
  spaceId: UUID;
  revisionId: UUID;
  revisionNumber: number | null;
  subjectEntityId: UUID;
  predicateKey: string;
  objectKind: KnowledgeObjectKind;
  objectEntityId: UUID | null;
  objectValue: unknown;
  status: "proposed" | "approved" | "rejected";
  rank: "preferred" | "normal" | "deprecated";
  confidence: number | null;
  validFrom: IsoDateTime | null;
  validTo: IsoDateTime | null;
  evidenceSegmentIds: UUID[];
  recordedAt: IsoDateTime;
}

export interface CreateKnowledgeStatementRequest {
  subjectEntityId: UUID;
  predicateKey: string;
  objectKind: KnowledgeObjectKind;
  objectEntityId?: UUID | null;
  objectValue?: unknown;
  evidenceSegmentIds?: UUID[];
  status?: "proposed" | "approved";
  rank?: "preferred" | "normal" | "deprecated";
  confidence?: number | null;
  changeSummary?: string;
}

export interface KnowledgePageRevision {
  id: UUID;
  pageId: UUID;
  revisionNumber: number;
  markdownBody: string;
  generatedMarkdown: string;
  manualMarkdown: string;
  statementIds: UUID[];
  evidenceSegmentIds: UUID[];
  sourceStatementRevisionId: UUID | null;
  generationRunId: UUID | null;
  createdByUserId: UUID;
  createdAt: IsoDateTime;
}

export interface KnowledgePage {
  id: UUID;
  spaceId: UUID;
  entityId: UUID;
  slug: string;
  title: string;
  pageType: string;
  status: string;
  revisionCount: number;
  currentRevision: KnowledgePageRevision;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface UpdateKnowledgePageRequest {
  expectedRevision: number;
  manualMarkdown: string;
}

export interface KnowledgeReviewDecisionRequest {
  decision: "approved" | "rejected";
  reason?: string;
}

export interface KnowledgeNeighborhood {
  rootEntityId: UUID;
  maxDepth: number;
  nodes: KnowledgeEntity[];
  edges: KnowledgeStatement[];
  truncated: boolean;
}

export interface AnnouncementMutationRequest {
  title: string;
  body: string;
}

export interface ProjectFolderSummary {
  id: UUID;
  projectId: UUID;
  logicalPath: string;
  revision: number;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export type HelpItemKind = "folder" | "document";

export interface HelpItem {
  id: UUID;
  parentId: UUID | null;
  kind: HelpItemKind;
  title: string;
  markdownContent: string;
  sortOrder: number;
  revision: number;
  createdByUserId: UUID;
  updatedByUserId: UUID;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface HelpItemList {
  items: HelpItem[];
  canManage: boolean;
}

export type Theme = "light" | "dark";
export type OutputMode = "auto" | "chat" | "file";
export type ClarificationMode = "autonomous" | "balanced" | "confirming";
export type AnalysisDepth = "auto" | "brief" | "standard" | "deep";
export type AnswerLength = "auto" | "brief" | "standard" | "detailed";

export interface ExecutionSelection {
  providerId: string;
  modelKey: string;
  effortId: string | null;
}

export interface AdminInitialExecutionSettings {
  execution: ExecutionSelection;
  source: "organization" | "application";
}

export interface CurrentSettings {
  theme: Theme;
  conversationWidth: number;
  conversationFontSize: number;
  outputMode: OutputMode;
  clarificationMode: ClarificationMode;
  execution: ExecutionSelection;
  modelCandidates: Record<string, string[]>;
  source: {
    theme: "user";
    execution: "user" | "project" | "organization" | "system" | "application";
  };
  revision: string;
  warnings: Array<{
    code: string;
    message: string;
  }>;
}

export interface UpdateCurrentSettingsRequest {
  theme?: Theme;
  conversationWidth?: number;
  conversationFontSize?: number;
  outputMode?: OutputMode;
  clarificationMode?: ClarificationMode;
  execution?: ExecutionSelection;
  modelCandidates?: Record<string, string[]>;
  expectedRevision: string;
}

export type ProviderConnectionStatus = "ready" | "unavailable" | "needs_setup";

export interface ProviderSummary {
  id: string;
  displayName: string;
  enabled: boolean;
  connectionStatus: ProviderConnectionStatus;
  defaultModelKey: string | null;
}

export interface EffortOption {
  id: string;
  label: string;
}

export interface ModelCapabilities {
  toolCalling: boolean;
  structuredOutput: boolean;
  imageInput: boolean;
  imageGeneration: boolean;
  contextWindow: number | null;
  maxInputTokens: number | null;
  effortOptions: EffortOption[];
}

export interface ModelSummary {
  modelKey: string;
  displayName: string;
  enabled: boolean;
  isDefault: boolean;
  catalogRevision: string;
  capabilities: ModelCapabilities;
}

export interface AdminProviderModel {
  providerId: string;
  modelKey: string;
  displayName: string;
  runtimeModelId: string;
  enabled: boolean;
  isDefault: boolean;
  capabilities: Record<string, unknown>;
  defaultContextWindow: number | null;
  contextPolicyLocked: boolean;
  maxInputTokens: number | null;
  defaultMaxInputTokens: number | null;
  maxOutputTokens: number | null;
  defaultMaxOutputTokens: number | null;
  configuredMaxOutputTokens: number | null;
  outputTokenStep: number;
}

export interface AdminProviderSummary {
  id: string;
  displayName: string;
  enabled: boolean;
  enabledModelCount: number;
  modelCount: number;
}

export type RuntimePromptKey = "system" | "agent_default";

export interface RuntimePromptDocument {
  key: RuntimePromptKey;
  name: string;
  description: string;
  content: string;
  defaultContent: string;
  revision: number;
  digest: string;
  overridden: boolean;
  updatedAt: IsoDateTime | null;
}

export interface ProjectMembership {
  id: UUID;
  projectId: UUID;
  userId: UUID;
  loginId: string;
  displayName: string;
  accountStatus: UserStatus;
  role: ProjectRole;
  status: ProjectMembershipStatus;
  isProjectOwner: boolean;
  createdByUserId: UUID;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface CreateProjectMembershipRequest {
  loginId: string;
  role: Exclude<ProjectRole, "owner">;
}

export interface UpdateProjectMembershipRequest {
  role?: ProjectRole;
  status?: ProjectMembershipStatus;
  expectedRole: ProjectRole;
  expectedStatus: ProjectMembershipStatus;
}

export type SidebarRunStatus =
  | "queued"
  | "running"
  | "approval"
  | "input"
  | "completed"
  | "failed"
  | "cancelled";

export interface AgentFrontendReference {
  id: string;
  version: string;
  frontendModule: string;
  frontendContract: string;
  fallback: boolean;
}

export interface ConversationListItem {
  id: UUID;
  projectId: UUID;
  title: string;
  isFavorite: boolean;
  isLiked: boolean;
  lastRunStatus: SidebarRunStatus | null;
  activeRunId: UUID | null;
  lastSequence: number;
  agent: AgentFrontendReference;
  updatedAt: IsoDateTime;
  revision: string;
}

export interface ListConversationsQuery {
  projectId?: UUID;
  cursor?: string;
  limit?: number;
  titleQuery?: string;
}

export interface CreateConversationRequest {
  projectId: UUID;
  title?: string;
}

export interface UpdateConversationRequest {
  title?: string;
  isFavorite?: boolean;
  isLiked?: boolean;
  expectedRevision: string;
}

export type ConversationExportFormat = "json" | "markdown";

export interface ConversationContentMatch {
  messageId: UUID;
  role: MessageRole;
  snippet: string;
  createdAt: IsoDateTime;
}

export interface ConversationSearchResult extends ConversationListItem {
  matches: ConversationContentMatch[];
}

export interface ConversationSearchResponse {
  items: ConversationSearchResult[];
  queryTokens: string[];
}

export type ReferenceKind = "file" | "folder" | "artifact" | "skill" | "mcp";
export type ReferenceValidationStatus = "valid" | "unavailable" | "revoked";

export interface PromptReference {
  kind: ReferenceKind;
  referenceId: UUID;
  versionOrDigest?: string | null;
  displaySnapshot?: Record<string, unknown>;
  tokenStart?: number | null;
  tokenEnd?: number | null;
}

export interface ComposerSuggestion {
  id: UUID;
  referenceId?: UUID;
  kind: ReferenceKind;
  name: string;
  displayName?: string;
  subtitle: string;
  description?: string;
  insertText?: string;
  status?: string;
  versionOrDigest: string | null;
  displaySnapshot: Record<string, unknown>;
}

export interface MessageReference extends PromptReference {
  validationStatus?: ReferenceValidationStatus;
}

export type MessageRole = "user" | "assistant" | "system";
export type MessageStatus = "pending" | "streaming" | "completed" | "interrupted";

export interface ChatMessage {
  id: UUID;
  conversationId: UUID;
  runId: UUID | null;
  role: MessageRole;
  text: string;
  status: MessageStatus;
  references: MessageReference[];
  attachments: AttachmentSummary[];
  metadata?: MessageMetadata;
  createdAt: IsoDateTime;
  completedAt: IsoDateTime | null;
}

export interface SourceEvidence {
  sourceId: string;
  originalUrl: string;
  normalizedUrl: string;
  title: string;
  domain: string;
  verbatimExcerpt: string;
  evidenceKind: "search_snippet" | "fetched_content";
  contentType?: string | null;
  extractionStatus?: "snippet_only" | "complete" | "empty";
  searchBackends?: string[];
  textChars?: number | null;
  llmTextChars?: number | null;
}

export interface WebSourceContentPage {
  sourceId: string;
  content: string;
  offset: number;
  nextOffset: number;
  hasMore: boolean;
  totalChars: number;
  llmTextChars: number;
  llmTextCharsEstimated: boolean;
}

export interface MessageCitation {
  sourceId?: string;
  source_id?: string;
  markerNumber?: number;
  marker_number?: number;
  claimBlockId?: string | null;
  status: "cited" | "resolved" | "reference_only";
}

export interface MessageMetadata {
  usage?: Record<string, unknown>;
  artifactUsage?: {
    tokens: number;
    lines: number;
    estimated?: boolean;
    targetTokens?: number;
    modelOutputTokens?: number;
  };
  sources?: SourceEvidence[];
  citations?: MessageCitation[];
  searchInvocations?: Array<{
    invocationId: string;
    query: string;
    backend: string;
    startedAt: IsoDateTime;
    purpose?: "broad_discovery" | "official_facts" | "latest_update" | "independent_evaluation" | "contradiction_check";
    parentInvocationId?: string;
  }>;
  researchRequirement?: {
    mode: "required" | "optional" | "disabled";
    reasons: string[];
  };
  researchVerification?: "verified" | "unverified" | "not_required" | "disabled";
  [key: string]: unknown;
}

export interface MessageFeedback {
  id: UUID;
  messageId: UUID;
  kind: "rating" | "report";
  value?: "like" | "dislike" | null;
  category?: string | null;
  description?: string | null;
  status: string;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface AdminUser {
  id: UUID;
  loginId: string;
  loginName: string;
  loginDomain: string;
  displayName: string | null;
  affiliation: string | null;
  role: UserRole;
  status: UserStatus;
  mustChangePassword: boolean;
  failedLoginCount: number;
  lockedUntil: IsoDateTime | null;
  lastLoginAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface AdminUserList {
  items: AdminUser[];
  total: number;
  offset: number;
  hasMore: boolean;
}

export interface AdminUsageStatistics {
  generatedAt: IsoDateTime;
  timezone: string;
  periodDays: number;
  summary: {
    dau: number;
    wau: number;
    mau: number;
    stickinessPercent: number;
    newUsers30d: number;
    runs: number;
  };
  trend: Array<{ date: string; activeUsers: number; loginCount: number; runCount: number }>;
  users: Array<{
    userId: UUID;
    loginId: string;
    displayName: string | null;
    affiliation: string | null;
    status: UserStatus;
    lastLoginAt: IsoDateTime | null;
    activeDays: number;
    loginCount: number;
    runCount: number;
    inputTokens: number;
    cachedInputTokens: number;
    cacheHitRatioPercent: number;
    outputTokens: number;
    estimatedCostUsd: number;
    lastActiveDate: string | null;
    inactiveDays: number | null;
  }>;
}

export interface AdminRunSafetySettings {
  maxModelTurns: number;
  maxTotalTokens: number;
  maxElapsedMinutes: number;
  maxCostUsd: number;
}

export interface AdminEmergencyStopResult {
  cancelledRunCount: number;
  cancelledQueuedMessageCount: number;
  cancelledActiveTaskCount: number;
}

export interface CreateAdminUserRequest {
  loginName: string;
  loginDomain: string;
  password: string;
  displayName?: string | null;
  affiliation?: string | null;
  role?: UserRole;
  status?: UserStatus;
  mustChangePassword?: boolean;
}

export interface UpdateAdminUserRequest {
  displayName?: string | null;
  affiliation?: string | null;
  role?: UserRole;
  status?: UserStatus;
}

export interface AdminConversationSummary {
  id: UUID;
  owner: { id: UUID; loginId: string; displayName: string | null };
  projectId: UUID;
  title: string;
  status: string;
  visibility: string;
  runCount: number;
  artifactCount: number;
  shareCount: number;
  feedbackCount: number;
  lastActivityAt: IsoDateTime;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface AdminConversationList {
  items: AdminConversationSummary[];
  total: number;
  offset: number;
  hasMore: boolean;
}

export interface AdminConversationDetail {
  conversation: {
    id: UUID;
    projectId: UUID;
    title: string;
    status: string;
    owner: { id: UUID; loginId: string | null; displayName: string | null };
    createdAt: IsoDateTime;
    updatedAt: IsoDateTime;
  };
  messages: ChatMessage[];
  runs: RunSnapshot[];
  artifacts: Array<{
    id: UUID;
    displayName: string;
    kind: ArtifactKind;
    mimeType: string;
    currentVersion: number;
    createdAt: IsoDateTime;
  }>;
  feedback: Array<{
    id: UUID;
    messageId: UUID;
    kind: "rating" | "report";
    value: "like" | "dislike" | null;
    category: string | null;
    description: string | null;
    status: string;
    author: { id: UUID; loginId: string; displayName: string | null };
    createdAt: IsoDateTime;
    updatedAt: IsoDateTime;
  }>;
}

export interface AdminAuditEvent {
  id: UUID;
  organizationId: UUID;
  actorUserId: UUID | null;
  actorLoginId: string | null;
  action: string;
  targetType: string;
  targetId: UUID | null;
  result: string;
  requestId: string | null;
  reason: string | null;
  metadata: Record<string, unknown>;
  createdAt: IsoDateTime;
}

export interface AdminAuditList {
  items: AdminAuditEvent[];
  total: number;
  offset: number;
  hasMore: boolean;
}

export interface AdminAuditTraffic {
  generatedAt: IsoDateTime;
  timezone: string;
  periodMinutes: number;
  total: number;
  peak: number;
  normalTotal: number;
  normalPeak: number;
  abnormalTotal: number;
  abnormalPeak: number;
  abnormalAuditTotal: number;
  automaticRecoveryTotal: number;
  manualRestartTotal: number;
  buckets: Array<{
    minute: IsoDateTime;
    count: number;
    normalCount: number;
    abnormalCount: number;
    abnormalAuditCount: number;
    automaticRecoveryCount: number;
    manualRestartCount: number;
  }>;
}

export interface AttachmentSummary {
  id: UUID;
  conversationId: UUID;
  projectId: UUID;
  kind: "file" | "image" | "pasted_text";
  fileName: string;
  mimeType: string;
  size: number;
  status: string;
  extractionStatus: string;
  metadata?: { lineCount?: number; [key: string]: unknown };
  createdAt: IsoDateTime;
}

export type RunStatus =
  | "queued"
  | "preparing"
  | "model_streaming"
  | "awaiting_approval"
  | "awaiting_input"
  | "tools_running"
  | "paused"
  | "completed"
  | "failed"
  | "cancelled"
  | "limit_reached"
  | "interrupted";

export type PlanStepStatus =
  | "queued"
  | "running"
  | "blocked"
  | "approval"
  | "completed"
  | "failed"
  | "cancelled";

export interface PlanSubtask {
  id: UUID;
  toolExecutionId: UUID | null;
  toolCallId: string;
  label: string;
  order: number;
  status: ToolExecutionStatus | "approval";
  dependsOn: UUID[];
  inputSnapshot: Record<string, unknown>;
  result: Record<string, unknown>;
  artifactIds: UUID[];
  effect: string;
  attempt: number;
  errorCode: string | null;
  errorMessage: string | null;
  startedAt: IsoDateTime | null;
  completedAt: IsoDateTime | null;
}

export interface PlanStep {
  id: UUID;
  label: string;
  status: PlanStepStatus;
  order: number;
  dependsOn: UUID[];
  startedAt: IsoDateTime | null;
  completedAt: IsoDateTime | null;
  error: string | null;
  subtasks?: PlanSubtask[];
}

export interface RunPlan {
  id: UUID;
  goal: string;
  steps: PlanStep[];
}

export type WorkPlanStepStatus = "pending" | "in_progress" | "completed";

export interface WorkPlanStep {
  id: UUID;
  step: string;
  status: WorkPlanStepStatus;
  order: number;
}

export type ToolExecutionStatus = "queued" | "streaming" | "running" | "completed" | "failed" | "cancelled";

export interface ToolExecution {
  id: UUID;
  callId: string;
  artifactId?: UUID | null;
  toolName: string;
  label: string;
  status: ToolExecutionStatus;
  input?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  inputSummary: string[];
  resultSummary: string[];
  startedAt: IsoDateTime | null;
  completedAt: IsoDateTime | null;
  durationMs: number | null;
  progress?: {
    tokens: number;
    lines: number;
    fileName?: string;
  } | null;
  error: string | null;
}

export type RunCommandType =
  | "steer"
  | "queue_next"
  | "pause"
  | "resume"
  | "cancel"
  | "steer_queued"
  | "cancel_command"
  | "retry_step"
  | "approve"
  | "reject";

export type RunCommandStatus =
  | "received"
  | "waiting_safe_boundary"
  | "applied"
  | "queued"
  | "cancelled"
  | "promoted"
  | "failed";

export interface RunCommand {
  id: UUID;
  type: RunCommandType;
  status: RunCommandStatus;
  messageId: UUID | null;
  messageText: string | null;
  queuePosition: number | null;
  createdAt: IsoDateTime;
}

export type ArtifactKind = "html" | "markdown" | "text" | "image" | "pdf" | "document" | "data" | "code";
export type ArtifactValidationStatus = "pending" | "passed" | "warning" | "failed";

export interface ArtifactSummary {
  id: UUID;
  projectId: UUID;
  conversationId: UUID | null;
  displayName: string;
  kind: ArtifactKind;
  mimeType: string;
  currentVersion: number;
  validationStatus: ArtifactValidationStatus;
  size: number;
  updatedAt: IsoDateTime;
  versions?: number[];
}

export interface ArtifactVersion {
  artifactId: UUID;
  version: number;
  mimeType: string;
  sourceText: string | null;
  previewUrl: string | null;
  contentHash: string;
  size: number;
  validationStatus: ArtifactValidationStatus;
  metadata: {
    requestedProvider?: string;
    requestedModel?: string;
    requestedImageBackendModel?: string;
    actualBackend?: string;
    actualModel?: string;
    actualModelSource?: string;
    size?: string;
    quality?: string;
    actualFormat?: string;
    background?: string;
  } | null;
  etag: string;
  createdAt: IsoDateTime;
}

export interface SaveArtifactVersionRequest {
  baseVersion: number;
  sourceText: string;
  changeSummary: string;
  idempotencyKey: string;
}

export interface ArtifactDownload {
  blob: Blob;
  fileName: string;
}

export interface ArtifactDraft {
  artifactId: UUID;
  baseVersion: number;
  content: string;
  etag: string;
  updatedAt: IsoDateTime;
  stale: boolean;
}

export interface ConversationShareCreated {
  id: UUID;
  conversationId: UUID;
  recipient: { id: UUID; loginId: string; displayName: string } | null;
  scope: string;
  permission: "view";
  anchorMessageId: UUID | null;
  snapshotThroughMessageId: UUID;
  expiresAt: IsoDateTime | null;
  revokedAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  lastAccessedAt: IsoDateTime | null;
  urlToken: string;
  viewerPath: string;
}

export interface SharedConversationSnapshot {
  share: {
    id: UUID;
    readOnly: true;
    scope: string;
    permission: "view";
    anchorMessageId: UUID | null;
    snapshotThroughMessageId: UUID;
    sharedAt: IsoDateTime;
    expiresAt: IsoDateTime | null;
  };
  conversation: {
    id: UUID;
    title: string;
    ownerDisplayName: string | null;
  };
  messages: Array<{
    id: UUID;
    runId: UUID | null;
    role: MessageRole;
    text: string;
    status: MessageStatus;
    references: Array<{
      kind: string;
      referenceId: UUID | null;
      displaySnapshot: Record<string, unknown>;
      status: "available" | "unavailable";
    }>;
    createdAt: IsoDateTime;
    completedAt: IsoDateTime | null;
  }>;
  attachments: Array<{
    id: UUID;
    messageId: UUID | null;
    filename: string;
    mimeType: string;
    size: number;
    contentHash: string;
  }>;
  artifacts: Array<{
    id: UUID;
    displayName: string;
    kind: string;
    mimeType: string;
    version: number;
    contentHash: string;
    size: number;
    validationStatus: ArtifactValidationStatus;
    createdAt: IsoDateTime;
  }>;
}

export interface SkillPackage {
  files: Record<string, string>;
}

export interface SkillDraft {
  id: UUID;
  extensionId: UUID;
  revision: number;
  digest: string;
  baseVersionId: UUID | null;
  baseVersion: number | null;
  dirty: boolean;
  status: string;
  etag: string;
  package: SkillPackage;
  updatedAt: IsoDateTime;
}

export interface SkillVersion {
  id: UUID;
  extensionId: UUID;
  version: number;
  parentVersionId: UUID | null;
  digest: string;
  status: string;
  manifest: Record<string, unknown>;
  package?: SkillPackage;
  createdAt: IsoDateTime;
  publishedAt: IsoDateTime | null;
}

export interface SkillOwnership {
  id: UUID;
  principalType: "user" | "team" | "organization";
  principalId: UUID;
  role: "owner" | "maintainer";
  displayName: string;
  createdAt: IsoDateTime;
}

export interface SkillExtension {
  id: UUID;
  kind: "skill";
  slug: string;
  name: string;
  description: string;
  tags: string[];
  visibility: "private" | "project" | "organization";
  ownerUserId: UUID;
  creatorUserId: UUID;
  currentUserRole: "owner" | "maintainer" | null;
  ownerships: SkillOwnership[];
  canEdit: boolean;
  canEditTags: boolean;
  canCreateDraft: boolean;
  canDelete: boolean;
  latestPublishedVersionId: UUID | null;
  versions: SkillVersion[];
  draft?: SkillDraft;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  archivedAt: IsoDateTime | null;
  purgesAt: IsoDateTime | null;
}

export interface SkillCatalogItem {
  id: UUID;
  name: string;
  description: string;
  category: string;
  tags: string[];
  latestVersionId: UUID | null;
  installed: boolean;
  installationId: UUID | null;
  canInstall: boolean;
  installCount: number;
  runCount: number;
  likeCount: number;
  likedByMe: boolean;
  updatedAt: IsoDateTime;
}

export interface SkillCatalogFacet {
  value: string;
  count: number;
}

export interface SkillCatalogResponse {
  items: SkillCatalogItem[];
  total: number;
  offset: number;
  hasMore: boolean;
  facets: {
    categories: SkillCatalogFacet[];
    tags: SkillCatalogFacet[];
  };
}

export interface SkillCatalogLikeResult {
  liked: boolean;
  likeCount: number;
}

export interface ExtensionInstallation {
  id: UUID;
  extensionId: UUID;
  versionId: UUID;
  scopeType: "user" | "project" | "organization";
  scopeId: UUID;
  enabled: boolean;
  projectIds: UUID[] | null;
  settings: Record<string, unknown>;
  installedAt: IsoDateTime;
}

export type McpTransport = "stdio" | "streamable_http";

export interface McpToolDefinition {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
}

export interface McpConfiguration {
  transport: McpTransport;
  command: string[];
  urlTemplate: string | null;
  allowedHosts: string[];
  allowedIpRanges: string[];
  headerTemplates: Record<string, string>;
  tools: McpToolDefinition[];
  requiredSecretNames: string[];
  timeoutSeconds: number;
}

export interface McpRevision {
  id: UUID;
  revision: number;
  transport: McpTransport;
  digest: string;
  validationStatus: string;
  healthStatus: string;
  schemaStatus: string;
  approvalStatus: string;
  validationSummary: string;
  tools: McpToolDefinition[];
  requiredSecretNames: string[];
  timeoutSeconds: number;
  target?: string | null;
  configuration?: McpConfiguration;
  createdAt: IsoDateTime;
  validatedAt: IsoDateTime | null;
  approvedAt: IsoDateTime | null;
}

export interface McpDefinition {
  id: UUID;
  slug: string;
  name: string;
  description: string;
  status: string;
  skillWrapper?: {
    wrapped: boolean;
    name: string | null;
  };
  currentRevisionId: UUID | null;
  revisions: McpRevision[];
  approvedAt: IsoDateTime | null;
  disabledAt: IsoDateTime | null;
  revokedAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface McpInstallation {
  id: UUID;
  definitionId: UUID;
  name: string;
  slug: string;
  definitionStatus: string;
  configurationRevisionId: UUID;
  configurationRevision: number;
  configurationDigest: string;
  healthStatus: string;
  schemaStatus: string;
  scopeType: "user" | "project";
  scopeId: UUID;
  enabled: boolean;
  projectIds: UUID[] | null;
  toolAllowlist: string[];
  boundSecrets: Array<{
    name: string;
    bound: boolean;
    resolvable: boolean;
    resolverStatus:
      | "ready"
      | "binding_required"
      | "administrator_required"
      | "resolver_unavailable";
    canBind: boolean;
  }>;
  secretResolutionStatus:
    | "not_required"
    | "ready"
    | "binding_required"
    | "administrator_required"
    | "resolver_unavailable";
  supportedSecretSchemes: string[];
  secretBindingRole: "admin";
  ready: boolean;
  connectionErrorCode: string | null;
  installedAt: IsoDateTime;
}

export interface McpAnswerTestResult {
  answer: string;
  providerId: string;
  modelKey: string;
  toolName: string;
}

export interface McpDefinitionCreateRequest {
  name: string;
  slug?: string;
  description: string;
  configuration: McpConfiguration;
}

export type MemoryLearningMode = "auto" | "confirm" | "off";

export interface UserMemory {
  id: UUID;
  category: string;
  normalizedFact: string;
  displayText: string;
  sourceMessageIds: UUID[];
  sourceRunIds: UUID[];
  confidence: number;
  evidenceCount: number;
  status: "active" | "pending" | "dismissed" | "superseded" | "deleted";
  conflictKey: string | null;
  supersedesMemoryId: UUID | null;
  extractorVersion: string;
  expiresAt: IsoDateTime | null;
  firstLearnedAt: IsoDateTime;
  lastConfirmedAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface MemorySettings {
  mode: MemoryLearningMode;
  enabled: boolean;
}

export interface MemoryOptimizationResult {
  mergedIds: UUID[];
  supersededIds: UUID[];
}

export type ProjectMemoryStatus = "active" | "superseded" | "deleted" | "rolled_back";

export interface ProjectMemory {
  id: UUID;
  projectId: UUID;
  memoryKey: UUID;
  revision: number;
  category: string;
  normalizedFact: string;
  displayText: string;
  contentHash: string;
  status: ProjectMemoryStatus;
  parentRevisionId: UUID | null;
  sourceProposalId: UUID;
  sourceRunIds: UUID[];
  createdByUserId: UUID;
  createdAt: IsoDateTime;
}

export interface ProjectMemoryHistory {
  memoryKey: UUID;
  current: ProjectMemory | null;
  revisions: ProjectMemory[];
}

export type ProjectLearningProposalStatus =
  | "proposed"
  | "approved"
  | "rejected"
  | "stale"
  | "applied"
  | "rolled_back";

export type ProjectLearningTargetType = "project_memory" | "project_concept";

export interface ProjectLearningEvidence {
  kind: "message" | "run" | "file" | "artifact";
  referenceId: UUID;
  versionOrDigest?: string | null;
  note?: string;
}

export interface ProjectLearningProposal {
  id: UUID;
  projectId: UUID;
  sourceRunIds: UUID[];
  targetType: ProjectLearningTargetType;
  targetId: UUID | null;
  baseRevision: number;
  baseHash: string;
  proposedPatch: Record<string, unknown>;
  rationale: string;
  reviewNote: string | null;
  evidenceRefs: ProjectLearningEvidence[];
  expectedScope: "project";
  status: ProjectLearningProposalStatus;
  proposedByUserId: UUID;
  reviewedByUserId: UUID | null;
  appliedSnapshot: Record<string, unknown>;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
  reviewedAt: IsoDateTime | null;
  approvedAt: IsoDateTime | null;
  rejectedAt: IsoDateTime | null;
  appliedAt: IsoDateTime | null;
  rolledBackAt: IsoDateTime | null;
}

export interface CreateProjectLearningProposalRequest {
  sourceRunIds: UUID[];
  targetType: ProjectLearningTargetType;
  targetId: UUID | null;
  baseRevision: number;
  baseHash: string;
  proposedPatch: Record<string, unknown>;
  rationale: string;
  evidenceRefs: ProjectLearningEvidence[];
  expectedScope: "project";
}

export interface ProjectLearningMutationResult {
  proposal: ProjectLearningProposal;
  projectMemory: ProjectMemory | null;
}

export type ScheduleKind = "hourly" | "daily" | "weekly" | "weekdays" | "manual";

export interface ScheduledTask {
  id: UUID;
  projectId: UUID;
  name: string;
  instructions: string;
  scheduleKind: ScheduleKind;
  scheduleConfig: Record<string, number>;
  timezone: string;
  contextMode: "continue_session" | "new_session_per_run";
  sourceConversationId: UUID | null;
  execution: ExecutionSelection;
  extensionSnapshotPolicy: "pinned" | "latest_allowed";
  deliveryPolicy: Record<string, unknown>;
  enabled: boolean;
  maxAttempts: number;
  timeoutSeconds: number;
  nextRunAt: IsoDateTime | null;
  lastRunAt: IsoDateTime | null;
  createdAt: IsoDateTime;
  updatedAt: IsoDateTime;
}

export interface ScheduledRun {
  id: UUID;
  scheduledTaskId: UUID;
  triggerType: "manual" | "scheduled";
  scheduledFor: IsoDateTime;
  status: string;
  attempt: number;
  runId: UUID | null;
  inputSnapshot: Record<string, unknown>;
  outputArtifactIds: UUID[];
  error: { code: string; message: string } | null;
  createdAt: IsoDateTime;
  startedAt: IsoDateTime | null;
  finishedAt: IsoDateTime | null;
}

export interface TurnSet {
  id: UUID;
  runId: UUID | null;
  messages: ChatMessage[];
  plan: RunPlan | null;
  toolExecutions: ToolExecution[];
  artifacts: ArtifactSummary[];
  createdAt: IsoDateTime;
  completedAt: IsoDateTime | null;
}

export interface TurnSetPage {
  turnSets: TurnSet[];
  previousCursor: string | null;
  hasMoreBefore: boolean;
  totalQuestionCount?: number;
}

export interface RunSnapshot {
  runId: UUID;
  conversationId: UUID;
  conversationTitle: string | null;
  conversationRevision: number | null;
  agent: AgentFrontendReference;
  status: RunStatus;
  errorCode: string | null;
  errorMessage: string | null;
  lastSequence: number;
  startedAt: IsoDateTime | null;
  finishedAt: IsoDateTime | null;
  assistantDraft: {
    messageId: UUID;
    text: string;
  } | null;
  artifactProgress: {
    tokens: number;
    lines: number;
    estimated?: boolean;
    targetTokens?: number;
    modelOutputTokens?: number;
  } | null;
  artifactUsage?: {
    tokens: number;
    lines: number;
    estimated?: boolean;
    targetTokens?: number;
    modelOutputTokens?: number;
  } | null;
  outputIntent: {
    fileCreationRequested: boolean;
    confidence: number;
    reason: string;
  } | null;
  workPlan: WorkPlanStep[];
  plan: RunPlan | null;
  activities: RunActivity[];
  toolExecutions: ToolExecution[];
  artifacts: ArtifactSummary[];
  pendingCommands: RunCommand[];
  pendingApprovals: ToolApproval[];
  inputRequests: UserInputRequest[];
  execution: ExecutionSelection & {
    runtimeModelId: string;
    catalogRevision: string;
  };
  modelTurnMetrics: ModelTurnMetric[];
  limits: {
    deadline: IsoDateTime;
    tokenLimit: number | null;
    costLimitUsd: number | null;
    costAccounting: "provider_reported";
  };
  usage: Record<string, unknown>;
}

export interface ModelTurnMetric {
  turnIndex: number;
  attempt: number;
  requestedEffort: string | null;
  effectiveEffort: string | null;
  startedAt: IsoDateTime;
  durationMs: number;
  ttftMs: number | null;
  status: "completed" | "failed" | "limited" | "interrupted";
  stopReason: string | null;
  inputTokens: number;
  cachedInputTokens: number;
  uncachedInputTokens: number;
  outputTokens: number;
  reasoningTokens?: number | null;
  cacheHitRatio: number;
}

export type RunActivity = {
  id: UUID;
  type: "progress_summary";
  sequence: number;
  text: string;
  phase: string;
  createdAt: IsoDateTime;
} | {
  id: string;
  type: "skill";
  sequence: number;
  skillId: UUID;
  name: string;
  slug: string;
  versionLabel: string;
  appliedBy: "auto" | "explicit" | "scheduled";
  reason: string;
} | {
  id: string;
  type: "tool";
  sequence: number;
  execution: ToolExecution;
} | {
  id: string;
  type: "input_request";
  sequence: number;
  request: UserInputRequest;
};

export interface ToolApproval {
  id: UUID;
  runId: UUID;
  toolCallId: string;
  toolName: string;
  effect: "read_only" | "workspace_write" | "external_read" | "external_write" | "destructive" | string;
  riskLevel: "low" | "medium" | "high" | string;
  argumentDigest: string;
  summary: {
    argumentCount: number;
    argumentFields: string[];
    sensitiveFieldCount: number;
  };
  status: "pending" | "approved" | "rejected" | "cancelled";
  requestedAt: IsoDateTime;
  resolvedAt: IsoDateTime | null;
}

export interface UserInputOption {
  id: string;
  label: string;
  description?: string;
}

export interface UserInputQuestion {
  id: string;
  prompt: string;
  options: UserInputOption[];
}

export interface UserInputAnswer {
  questionId: string;
  optionId?: string;
  customText?: string;
  useAiJudgment?: boolean;
  kind?: "option" | "custom" | "ai";
  text?: string;
}

export interface UserInputRequest {
  id: UUID;
  runId: UUID;
  toolCallId: string;
  status: "pending" | "submitted" | "cancelled";
  questions: UserInputQuestion[];
  answers: UserInputAnswer[];
  createdAt: IsoDateTime;
  submittedAt?: IsoDateTime;
}

export interface RunMessageInput {
  text: string;
  attachmentIds: UUID[];
  promptReferences: PromptReference[];
  outputMode: OutputMode;
  analysisDepth: AnalysisDepth;
  answerLength: AnswerLength;
  targetOutputTokens?: number;
}

export interface StartRunRequest {
  idempotencyKey: string;
  message: RunMessageInput;
  execution?: ExecutionSelection;
}

export type RunActionRequest =
  | {
      idempotencyKey: string;
      type: "steer" | "queue_next";
      message: RunMessageInput;
    }
  | {
      idempotencyKey: string;
      type: "pause" | "resume" | "cancel";
    }
  | {
      idempotencyKey: string;
      type: "steer_queued" | "cancel_command";
      commandId: UUID;
    }
  | {
      idempotencyKey: string;
      type: "retry_step";
      stepId: UUID;
    }
  | {
      idempotencyKey: string;
      type: "approve" | "reject";
      approvalId: UUID;
      note?: string;
    }
  | {
      idempotencyKey: string;
      type: "submit_user_input";
      inputRequestId: UUID;
      answers: UserInputAnswer[];
    };

export interface RunMutationResponse {
  message: ChatMessage | null;
  command: RunCommand | null;
  run: RunSnapshot;
}

export type RunEventType =
  | "run_started"
  | "run_status_changed"
  | "model_turn_completed"
  | "assistant_text_delta"
  | "progress_summary"
  | "output_intent_classified"
  | "skill_selected"
  | "assistant_turn_completed"
  | "conversation_title_updated"
  | "artifact_progress"
  | "work_plan_updated"
  | "plan_step_changed"
  | "tool_started"
  | "tool_progress"
  | "tool_completed"
  | "approval_requested"
  | "approval_resolved"
  | "approval_checkpoint_consumed"
  | "input_requested"
  | "input_submitted"
  | "input_checkpoint_consumed"
  | "artifact_created"
  | "steer_received"
  | "steer_waiting_safe_boundary"
  | "steer_applied"
  | "steer_cancelled"
  | "queued_message_added"
  | "queued_message_cancelled"
  | "queued_message_promoted_to_run"
  | "provider_failure_classified"
  | "run_completed"
  | "run_failed"
  | "run_limit_reached"
  | "run_cancelled"
  | "run_interrupted";

interface RunEventEnvelope<TType extends RunEventType, TPayload> {
  runId: UUID;
  conversationId: UUID;
  sequence: number;
  type: TType;
  payload: TPayload;
  createdAt: IsoDateTime;
}

export type RunEvent =
  | RunEventEnvelope<"run_started" | "run_status_changed", { status: RunStatus }>
  | RunEventEnvelope<"model_turn_completed", ModelTurnMetric>
  | RunEventEnvelope<"assistant_text_delta", { messageId: UUID; delta: string }>
  | RunEventEnvelope<"progress_summary", { id: UUID; text: string; phase: string }>
  | RunEventEnvelope<"output_intent_classified", NonNullable<RunSnapshot["outputIntent"]>>
  | RunEventEnvelope<"skill_selected", { activity: Extract<RunActivity, { type: "skill" }> }>
  | RunEventEnvelope<"assistant_turn_completed", { message: ChatMessage }>
  | RunEventEnvelope<"conversation_title_updated", { title: string; revision: number; source: "llm" }>
  | RunEventEnvelope<"artifact_progress", { tokens: number; lines: number }>
  | RunEventEnvelope<"work_plan_updated", { steps: WorkPlanStep[] }>
  | RunEventEnvelope<"plan_step_changed", { planId: UUID; step: PlanStep }>
  | RunEventEnvelope<"tool_started" | "tool_progress" | "tool_completed", { execution: ToolExecution }>
  | RunEventEnvelope<"approval_requested", { approval: ToolApproval }>
  | RunEventEnvelope<"approval_resolved", { approval: ToolApproval; decision: ToolApproval["status"]; command?: RunCommand }>
  | RunEventEnvelope<"approval_checkpoint_consumed", { toolCallIds: string[] }>
  | RunEventEnvelope<"input_requested", { request: UserInputRequest }>
  | RunEventEnvelope<"input_submitted", { request: UserInputRequest; command?: RunCommand }>
  | RunEventEnvelope<"input_checkpoint_consumed", { inputRequestId: UUID }>
  | RunEventEnvelope<"artifact_created", { artifact: ArtifactSummary }>
  | RunEventEnvelope<
      | "steer_received"
      | "steer_waiting_safe_boundary"
      | "steer_applied"
      | "steer_cancelled"
      | "queued_message_added"
      | "queued_message_cancelled"
      | "queued_message_promoted_to_run",
      { command?: RunCommand; queuedMessageId?: UUID; runId?: UUID }
    >
  | RunEventEnvelope<
      "provider_failure_classified",
      {
        code: string;
        stage: string;
        statusCode: number | null;
        retryable: boolean;
        attemptCount: number;
        retryAfterSeconds: number | null;
      }
    >
  | RunEventEnvelope<
      "run_completed" | "run_failed" | "run_cancelled" | "run_interrupted",
      { status: RunStatus; finishedAt: IsoDateTime }
    >
  | RunEventEnvelope<
      "run_limit_reached",
      {
        code: "run_deadline_reached" | "run_token_limit" | "run_cost_limit";
        limit: number | string | null;
        observed: number | string | null;
      }
    >;

export interface RunStreamHandlers {
  onOpen?: () => void;
  onEvent: (event: RunEvent) => void;
  onError?: (error: Event | Error) => void;
}
