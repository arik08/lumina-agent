import {
  AlertTriangle,
  AlignLeft,
  AtSign,
  Check,
  ChevronDown,
  CircleAlert,
  CircleDollarSign,
  FolderDown,
  FileText,
  GitBranch,
  History,
  LoaderCircle,
  Menu,
  Pause,
  Paperclip,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Search,
  Square,
  Target,
  Trash2,
  Undo2,
  WandSparkles,
  Waypoints,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  type CSSProperties,
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { api as coreApi, ApiError, projectFilePreviewUrl } from "../../api";
import { deepAnalysisApi, projectFilesApi } from "../../feature-api";
import { copyText } from "../../clipboard";
import {
  analysisDepthOptions,
  answerLengthOptions,
  ArtifactLengthSlider,
  ComposerPicker,
  type ComposerPickerOption,
} from "../../components/ComposerControls";
import { ArtifactHtmlPreview } from "../../components/ArtifactHtmlPreview";
import { ArtifactPreviewActions } from "../../components/ArtifactPreviewActions";
import { MarkdownResponse } from "../../components/ConversationTurn";
import { SelectMenu } from "../../components/SelectMenu";
import { useCachedViewState } from "../../view-data-cache";
import { useSharedNow } from "../../shared-clock";
import { useFixedVirtualList } from "../../use-fixed-virtual-list";
import {
  appendMissionEvent,
  setMissionEvents,
  useMissionEventCount,
  useMissionEvents,
} from "./mission-event-store";
import type {
  DeepAnalysisMissionDetail,
  DeepAnalysisMissionEvent,
  DeepAnalysisMissionCosts,
  DeepAnalysisRefreshPreview,
  DeepAnalysisResearchInspector,
  DeepAnalysisMissionSummary,
  DeepAnalysisOutputFormat,
  DeepAnalysisWorkflowNode,
  DeepAnalysisWorkflowRevision,
  ComposerSuggestion,
  EffortOption,
  ExecutionSelection,
  OutputMode,
  PromptReference,
} from "../../api-types";
import "./deep-analysis.css";

const api = { ...coreApi, deepAnalysis: deepAnalysisApi, projectFiles: projectFilesApi };
const workflowNodeTypeOptions = [
  { value: "scope", label: "범위 설계" },
  { value: "research", label: "자료 조사" },
  { value: "data_check", label: "자료 검증" },
  { value: "analysis", label: "분석" },
  { value: "validation", label: "교차 검증" },
  { value: "synthesis", label: "종합" },
  { value: "report", label: "보고서" },
];

interface DeepAnalysisViewProps {
  projectId: string | null;
  canEdit: boolean;
  requestedMissionId: string | null;
  removedMissionIds: ReadonlySet<string>;
  createRequest: number;
  onCreateRequestHandled: () => void;
  onMissionsChange: (missions: DeepAnalysisMissionSummary[]) => void;
  onMissionsLoadingChange: (loading: boolean) => void;
  onSelectedMissionChange: (missionId: string | null) => void;
  onOpenProjectFile: (fileId: string) => void;
  onOpenNavigation: () => void;
  execution: ExecutionSelection | null;
  executionOptions: DeepAnalysisExecutionOption[];
}

type MissionAnalysisDepth = "auto" | "brief" | "standard" | "deep";
type MissionAnswerLength = "auto" | "brief" | "standard" | "detailed";
type WebSourceMode = "all" | "prioritize" | "restrict";

function isCompleteHtmlDocument(value: string) {
  const normalized = value.trimStart().toLowerCase();
  return normalized.startsWith("<!doctype html")
    && normalized.includes("<html")
    && normalized.includes("<head")
    && normalized.includes("<body");
}

const webSourceModeLabels: Record<WebSourceMode, string> = {
  all: "전체 웹",
  prioritize: "지정 출처 우선",
  restrict: "지정 출처만",
};

function parseDomainList(value: string) {
  return [...new Set(value.split(/[\s,]+/).map((item) => item.trim().toLowerCase()).filter(Boolean))];
}

function ResearchSettingsFields({
  startDate,
  endDate,
  sourceMode,
  domains,
  excludedDomains,
  disabled,
  onStartDateChange,
  onEndDateChange,
  onSourceModeChange,
  onDomainsChange,
  onExcludedDomainsChange,
}: {
  startDate: string;
  endDate: string;
  sourceMode: WebSourceMode;
  domains: string;
  excludedDomains: string;
  disabled: boolean;
  onStartDateChange: (value: string) => void;
  onEndDateChange: (value: string) => void;
  onSourceModeChange: (value: WebSourceMode) => void;
  onDomainsChange: (value: string) => void;
  onExcludedDomainsChange: (value: string) => void;
}) {
  return (
    <details className="deep-analysis-research-settings">
      <summary>연구 범위 · 웹 출처</summary>
      <div className="deep-analysis-research-date-grid">
        <label>시작일<input type="date" value={startDate} disabled={disabled} onChange={(event) => onStartDateChange(event.target.value)} /></label>
        <label>종료일<input type="date" value={endDate} disabled={disabled} onChange={(event) => onEndDateChange(event.target.value)} /></label>
      </div>
      <fieldset>
        <legend>웹 출처 정책</legend>
        {(Object.keys(webSourceModeLabels) as WebSourceMode[]).map((mode) => (
          <button
            key={mode}
            type="button"
            className={sourceMode === mode ? "is-active" : undefined}
            aria-pressed={sourceMode === mode}
            disabled={disabled}
            onClick={() => onSourceModeChange(mode)}
          >{webSourceModeLabels[mode]}</button>
        ))}
      </fieldset>
      {sourceMode !== "all" && (
        <label>
          {sourceMode === "restrict" ? "허용 도메인" : "우선 도메인"}
          <input value={domains} disabled={disabled} placeholder="example.com, data.go.kr" onChange={(event) => onDomainsChange(event.target.value)} />
          <small>쉼표나 공백으로 구분합니다. 하위 도메인도 함께 적용됩니다.</small>
        </label>
      )}
      <label>
        제외 도메인
        <input value={excludedDomains} disabled={disabled} placeholder="blog.example.com" onChange={(event) => onExcludedDomainsChange(event.target.value)} />
      </label>
    </details>
  );
}

const outputFormatOptions = [
  { value: "markdown", label: "Markdown (.md)" },
  { value: "html", label: "HTML (.html)" },
] as const;

function normalizeOutputFormat(value: string) {
  const trimmed = value.trim();
  const normalized = trimmed.toLowerCase();
  if (["markdown", "markdown (.md)", "md", ".md"].includes(normalized)) return "markdown";
  if (["html", "html (.html)", ".html"].includes(normalized)) return "html";
  return trimmed || "markdown";
}

function outputFormatDisplay(value: string) {
  return outputFormatOptions.find((option) => option.value === value)?.label ?? value;
}

function OutputFormatInput({
  value,
  disabled = false,
  onChange,
}: {
  value: string;
  disabled?: boolean;
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !rootRef.current?.contains(event.target)) {
        onChange(normalizeOutputFormat(value));
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    return () => document.removeEventListener("pointerdown", closeOutside);
  }, [onChange, open, value]);

  return (
    <div ref={rootRef} className="deep-analysis-output-format-input">
      <input
        role="combobox"
        aria-label="최종 산출물 형태"
        aria-expanded={open}
        aria-controls="deep-analysis-output-format-options"
        autoComplete="off"
        maxLength={120}
        placeholder="최종 산출물 형태"
        disabled={disabled}
        value={outputFormatDisplay(value)}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        onBlur={(event) => {
          if (event.relatedTarget instanceof Node && rootRef.current?.contains(event.relatedTarget)) return;
          onChange(normalizeOutputFormat(value));
          setOpen(false);
        }}
      />
      <button
        type="button"
        aria-label="최종 산출물 형태 추천 열기"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      ><ChevronDown size={14} /></button>
      {open && (
        <div id="deep-analysis-output-format-options" role="listbox" aria-label="최종 산출물 형태 추천">
          {outputFormatOptions.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={normalizeOutputFormat(value) === option.value}
              onClick={() => {
                onChange(option.value);
                setOpen(false);
              }}
            >{option.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}

interface DeepAnalysisExecutionOption extends ComposerPickerOption {
  providerId: string;
  modelKey: string;
  effortOptions: EffortOption[];
}

interface SelectedMissionReference {
  key: string;
  token: string;
  name: string;
  kind: PromptReference["kind"];
  reference: PromptReference;
}

function selectedReferencesFromMission(mission: DeepAnalysisMissionDetail): SelectedMissionReference[] {
  return mission.promptReferences.map((reference) => {
    const snapshotName = reference.displaySnapshot?.name;
    const name = typeof snapshotName === "string" && snapshotName
      ? snapshotName
      : reference.referenceId;
    const tokenStart = reference.tokenStart ?? -1;
    const tokenEnd = reference.tokenEnd ?? -1;
    const storedToken = tokenStart >= 0 && tokenEnd > tokenStart
      ? mission.objective.slice(tokenStart, tokenEnd)
      : "";
    const token = storedToken || `${reference.kind === "skill" || reference.kind === "mcp" ? "$" : "@"}${name}`;
    return {
      key: `${reference.kind}:${reference.referenceId}:${reference.versionOrDigest ?? ""}`,
      token,
      name,
      kind: reference.kind,
      reference,
    };
  });
}

function promptReferencesForObjective(
  references: SelectedMissionReference[],
  objective: string,
): PromptReference[] {
  return references.flatMap(({ reference, token }) => {
    const tokenStart = objective.indexOf(token);
    return [{
      ...reference,
      tokenStart: tokenStart < 0 ? null : tokenStart,
      tokenEnd: tokenStart < 0 ? null : tokenStart + token.length,
    }];
  });
}

const statusLabels: Record<string, string> = {
  draft: "설계 중",
  ready: "준비됨",
  planned: "예정",
  running: "진행 중",
  completed: "완료",
  failed: "실패",
  blocked: "확인 필요",
  cancelled: "중단됨",
  queued: "대기 중",
  preparing: "준비 중",
  model_streaming: "응답 생성 중",
  tools_running: "도구 실행 중",
  awaiting_approval: "승인 대기",
  awaiting_input: "입력 대기",
  paused: "일시정지",
  limit_reached: "한도 도달",
  interrupted: "복구 중",
};

const minimumCanvasScale = 0.4;
const maximumCanvasScale = 1.8;
const workflowNodeWidth = 176;
const workflowNodeHeight = 86;
const workflowLayerGap = 74;
const workflowMissionRootPosition = { positionX: 272, positionY: 88 } as const;
const workflowLayerTop = workflowMissionRootPosition.positionY + workflowNodeHeight + workflowLayerGap;
const workflowSiblingGap = 36;
const defaultInspectorWidth = 760;
const minimumInspectorWidth = 420;
const maximumInspectorWidthRatio = 0.84;
const inspectorWidthStorageKey = "lumina:deep-analysis:inspector-width:v2";
const workflowPortSides = ["north", "south"] as const;
type WorkflowPortSide = typeof workflowPortSides[number];
type WorkflowNodePosition = Pick<DeepAnalysisWorkflowNode, "positionX" | "positionY">;
function statusLabel(status: string) {
  return statusLabels[status] ?? status;
}

function normalizeUtcDateTime(value: string) {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
}

function formatNodeElapsedTime(startedAt: string, now: number) {
  const startedAtMs = Date.parse(normalizeUtcDateTime(startedAt));
  if (!Number.isFinite(startedAtMs) || !Number.isFinite(now)) return null;
  const totalSeconds = Math.max(0, Math.floor((now - startedAtMs) / 1_000));
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}분 ${totalSeconds % 60}초`;
  return `${Math.floor(totalMinutes / 60)}시간 ${totalMinutes % 60}분 ${totalSeconds % 60}초`;
}

function displayLiveOutput(value: string) {
  return value.replace(/\\r\\n|\\n|\\r/g, "\n");
}

function formatCost(microusd: number, usdKrwRate: number | null) {
  const usd = microusd / 1_000_000;
  if (usdKrwRate !== null) return `₩ ${new Intl.NumberFormat("ko-KR").format(Math.round(usd * usdKrwRate))}`;
  return `$ ${usd.toFixed(2)}`;
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return "심층분석 정보를 불러오지 못했습니다.";
}

function selectedMissionStorageKey(projectId: string) {
  return `lumina:deep-analysis:selected:${projectId}`;
}

function storedInspectorWidth() {
  try {
    const value = Number(window.localStorage.getItem(inspectorWidthStorageKey));
    return Number.isFinite(value) && value > 0 ? value : defaultInspectorWidth;
  } catch {
    return defaultInspectorWidth;
  }
}

function arrangeWorkflowTopDown(
  workflow: DeepAnalysisWorkflowRevision,
  includeIsolatedNodes = false,
) {
  const nodeByKey = new Map(workflow.nodes.map((node) => [node.nodeKey, node]));
  const outgoing = new Map<string, string[]>();
  const incomingCount = new Map(workflow.nodes.map((node) => [node.nodeKey, 0]));
  const connectedNodeKeys = new Set<string>();
  for (const edge of workflow.edges) {
    if (!nodeByKey.has(edge.sourceNodeKey) || !nodeByKey.has(edge.targetNodeKey)) continue;
    connectedNodeKeys.add(edge.sourceNodeKey);
    connectedNodeKeys.add(edge.targetNodeKey);
    outgoing.set(edge.sourceNodeKey, [...(outgoing.get(edge.sourceNodeKey) ?? []), edge.targetNodeKey]);
    incomingCount.set(edge.targetNodeKey, (incomingCount.get(edge.targetNodeKey) ?? 0) + 1);
  }
  const layoutNodeKeys = includeIsolatedNodes
    ? new Set(workflow.nodes.map((node) => node.nodeKey))
    : connectedNodeKeys;

  const compareNodes = (leftKey: string, rightKey: string) => {
    const left = nodeByKey.get(leftKey);
    const right = nodeByKey.get(rightKey);
    return (left?.positionY ?? 0) - (right?.positionY ?? 0)
      || (left?.positionX ?? 0) - (right?.positionX ?? 0)
      || leftKey.localeCompare(rightKey);
  };
  const queue = workflow.nodes
    .filter((node) => layoutNodeKeys.has(node.nodeKey) && (incomingCount.get(node.nodeKey) ?? 0) === 0)
    .map((node) => node.nodeKey)
    .sort(compareNodes);
  const depth = new Map(queue.map((nodeKey) => [nodeKey, 0]));
  const visited = new Set<string>();
  while (queue.length) {
    const sourceNodeKey = queue.shift()!;
    visited.add(sourceNodeKey);
    for (const targetNodeKey of (outgoing.get(sourceNodeKey) ?? []).sort(compareNodes)) {
      depth.set(targetNodeKey, Math.max(
        depth.get(targetNodeKey) ?? 0,
        (depth.get(sourceNodeKey) ?? 0) + 1,
      ));
      const remaining = (incomingCount.get(targetNodeKey) ?? 1) - 1;
      incomingCount.set(targetNodeKey, remaining);
      if (remaining === 0) queue.push(targetNodeKey);
    }
    queue.sort(compareNodes);
  }

  let fallbackDepth = Math.max(0, ...depth.values());
  for (const node of [...workflow.nodes].sort((left, right) => compareNodes(left.nodeKey, right.nodeKey))) {
    if (!layoutNodeKeys.has(node.nodeKey) || visited.has(node.nodeKey)) continue;
    fallbackDepth += 1;
    depth.set(node.nodeKey, fallbackDepth);
  }
  const layers = new Map<number, DeepAnalysisWorkflowNode[]>();
  for (const node of workflow.nodes) {
    if (!layoutNodeKeys.has(node.nodeKey)) continue;
    const nodeDepth = depth.get(node.nodeKey) ?? 0;
    layers.set(nodeDepth, [...(layers.get(nodeDepth) ?? []), node]);
  }
  for (const nodes of layers.values()) {
    nodes.sort((left, right) => compareNodes(left.nodeKey, right.nodeKey));
  }
  return {
    ...workflow,
    nodes: workflow.nodes.map((node) => {
      if (!layoutNodeKeys.has(node.nodeKey)) return node;
      const nodeDepth = depth.get(node.nodeKey) ?? 0;
      const layer = layers.get(nodeDepth) ?? [node];
      const column = layer.findIndex((item) => item.nodeKey === node.nodeKey);
      const layerWidth = layer.length * workflowNodeWidth
        + Math.max(0, layer.length - 1) * workflowSiblingGap;
      return {
        ...node,
        positionX: workflowMissionRootPosition.positionX + (workflowNodeWidth - layerWidth) / 2
          + column * (workflowNodeWidth + workflowSiblingGap),
        positionY: workflowLayerTop + nodeDepth * (workflowNodeHeight + workflowLayerGap),
      };
    }),
  };
}

function workflowPortPoint(node: WorkflowNodePosition, side: WorkflowPortSide) {
  if (side === "north") return { x: node.positionX + workflowNodeWidth / 2, y: node.positionY };
  return { x: node.positionX + workflowNodeWidth / 2, y: node.positionY + workflowNodeHeight };
}

function workflowPortVector(side: WorkflowPortSide) {
  if (side === "north") return { x: 0, y: -1 };
  return { x: 0, y: 1 };
}

function workflowEdgeSides(
  source: WorkflowNodePosition,
  target: WorkflowNodePosition,
): [WorkflowPortSide, WorkflowPortSide] {
  const deltaY = target.positionY - source.positionY;
  return deltaY >= 0 ? ["south", "north"] : ["north", "south"];
}

function workflowEdgeGeometry(
  source: WorkflowNodePosition,
  target: WorkflowNodePosition,
) {
  const [sourceSide, targetSide] = workflowEdgeSides(source, target);
  const sourcePoint = workflowPortPoint(source, sourceSide);
  const targetPoint = workflowPortPoint(target, targetSide);
  const sourceVector = workflowPortVector(sourceSide);
  const targetVector = workflowPortVector(targetSide);
  const stemLength = 12;
  const sourceStem = {
    x: sourcePoint.x + sourceVector.x * stemLength,
    y: sourcePoint.y + sourceVector.y * stemLength,
  };
  const targetStem = {
    x: targetPoint.x + targetVector.x * stemLength,
    y: targetPoint.y + targetVector.y * stemLength,
  };
  const controlOffset = Math.max(
    18,
    Math.abs(targetStem.y - sourceStem.y) * .5,
  );
  return {
    sourcePoint,
    targetPoint,
    path: `M ${sourcePoint.x} ${sourcePoint.y} L ${sourceStem.x} ${sourceStem.y} C ${sourceStem.x + sourceVector.x * controlOffset} ${sourceStem.y + sourceVector.y * controlOffset}, ${targetStem.x + targetVector.x * controlOffset} ${targetStem.y + targetVector.y * controlOffset}, ${targetStem.x} ${targetStem.y} L ${targetPoint.x} ${targetPoint.y}`,
  };
}

function eventDescription(event: DeepAnalysisMissionEvent) {
  const nodeKey = typeof event.payload.nodeKey === "string" ? event.payload.nodeKey : null;
  const characters = typeof event.payload.outputCharacters === "number"
    ? event.payload.outputCharacters.toLocaleString()
    : null;
  const labels: Record<string, string> = {
    mission_created: "Mission이 생성되었습니다.",
    mission_status_changed: "Mission 상태가 변경되었습니다.",
    node_queued: "실행 대기열에 등록되었습니다.",
    node_started: "실행을 시작했습니다.",
    node_output_delta: characters ? `응답 ${characters}자를 생성했습니다.` : "응답을 생성하고 있습니다.",
    node_completed: "출력 문서 저장을 완료했습니다.",
    node_failed: "실행에 실패했습니다.",
    node_cancelled: "실행이 중단되었습니다.",
    workflow_expansion_proposed: "중간 결과에 따라 Workflow 변경을 검토했습니다.",
    workflow_expansion_decided: "Workflow 변경 판단을 기록했습니다.",
    workflow_revision_activated: "새 Workflow revision을 활성화했습니다.",
    decision_requested: "사용자 판단을 요청했습니다.",
    decision_answered: "사용자 판단을 반영했습니다.",
    mission_cost_updated: "누적 비용을 갱신했습니다.",
    mission_file_created: "Mission 파일을 보존했습니다.",
    mission_completed: "Mission을 완료했습니다.",
    mission_restarted: "Mission을 처음부터 다시 시작했습니다.",
  };
  return { nodeKey, label: labels[event.type] ?? event.type.replaceAll("_", " ") };
}

const DETAIL_REFRESH_EVENT_TYPES = new Set([
  "decision_requested",
  "decision_resolved",
  "mission_completed",
  "mission_file_created",
  "mission_restarted",
  "mission_updated",
  "node_completed",
  "node_retried",
  "quality_gate_completed",
  "workflow_draft_created",
  "workflow_draft_updated",
  "workflow_regenerated",
  "workflow_revision_activated",
]);

export function DeepAnalysisView({
  projectId,
  canEdit,
  requestedMissionId,
  removedMissionIds,
  createRequest,
  onCreateRequestHandled,
  onMissionsChange,
  onMissionsLoadingChange,
  onSelectedMissionChange,
  onOpenProjectFile,
  onOpenNavigation,
  execution,
  executionOptions,
}: DeepAnalysisViewProps) {
  const cacheScope = projectId ?? "none";
  const [missions, setMissions] = useCachedViewState<DeepAnalysisMissionSummary[]>(
    `deep-analysis:${cacheScope}:missions`,
    [],
  );
  const [selectedMissionId, setSelectedMissionId] = useCachedViewState<string | null>(
    `deep-analysis:${cacheScope}:selected-mission`,
    requestedMissionId,
  );
  const [mission, setMission, hasCachedMission] = useCachedViewState<DeepAnalysisMissionDetail | null>(
    `deep-analysis:${cacheScope}:mission`,
    null,
  );
  const [selectedNodeKey, setSelectedNodeKey] = useCachedViewState<string | null>(
    `deep-analysis:${cacheScope}:selected-node`,
    null,
  );
  const [missionRootSelected, setMissionRootSelected] = useState(false);
  const [missionTitleDraft, setMissionTitleDraft] = useState("");
  const [missionObjectiveDraft, setMissionObjectiveDraft] = useState("");
  const [savingMissionSettings, setSavingMissionSettings] = useState(false);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMission, setLoadingMission] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createElapsedSeconds, setCreateElapsedSeconds] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [analysisDepth, setAnalysisDepth] = useState<MissionAnalysisDepth>("auto");
  const [answerLength, setAnswerLength] = useState<MissionAnswerLength>("auto");
  const [outputMode, setOutputMode] = useState<OutputMode>("auto");
  const [outputFormat, setOutputFormat] = useState<DeepAnalysisOutputFormat>("markdown");
  const [targetOutputTokens, setTargetOutputTokens] = useState(10_000);
  const [createExecution, setCreateExecution] = useState<ExecutionSelection | null>(execution);
  const [selectedReferences, setSelectedReferences] = useState<SelectedMissionReference[]>([]);
  const [researchStartDate, setResearchStartDate] = useState("");
  const [researchEndDate, setResearchEndDate] = useState("");
  const [webSourceMode, setWebSourceMode] = useState<WebSourceMode>("all");
  const [webSourceDomains, setWebSourceDomains] = useState("");
  const [excludedWebSourceDomains, setExcludedWebSourceDomains] = useState("");
  const [steerInstruction, setSteerInstruction] = useState("");
  const [steerReferences, setSteerReferences] = useState<SelectedMissionReference[]>([]);
  const [steeringMission, setSteeringMission] = useState(false);
  const [uploadingSteerSources, setUploadingSteerSources] = useState(false);
  const [researchInspectorOpen, setResearchInspectorOpen] = useState(false);
  const [researchInspector, setResearchInspector] = useState<DeepAnalysisResearchInspector | null>(null);
  const [loadingResearchInspector, setLoadingResearchInspector] = useState(false);
  const [refreshPreview, setRefreshPreview] = useState<DeepAnalysisRefreshPreview | null>(null);
  const [loadingRefreshPreview, setLoadingRefreshPreview] = useState(false);
  const [refreshArmed, setRefreshArmed] = useState(false);
  const [refreshingMission, setRefreshingMission] = useState(false);
  const [referenceTrigger, setReferenceTrigger] = useState<"@" | "$" | null>(null);
  const [referenceQuery, setReferenceQuery] = useState("");
  const [referenceSuggestions, setReferenceSuggestions] = useState<ComposerSuggestion[]>([]);
  const [loadingReferences, setLoadingReferences] = useState(false);
  const [uploadingSources, setUploadingSources] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [outputSourceNodeId, setOutputSourceNodeId] = useState<string | null>(null);
  const [outputActionStatus, setOutputActionStatus] = useState<string | null>(null);
  const [costModeActive, setCostModeActive] = useState(false);
  const [costDetailsOpen, setCostDetailsOpen] = useState(false);
  const [costDetails, setCostDetails] = useState<DeepAnalysisMissionCosts | null>(null);
  const [usdKrwRate, setUsdKrwRate] = useState<number | null>(null);
  const [loadingCosts, setLoadingCosts] = useState(false);
  const [startingMission, setStartingMission] = useState(false);
  const [cancellingMission, setCancellingMission] = useState(false);
  const [pausingMission, setPausingMission] = useState(false);
  const [retryingNodeKey, setRetryingNodeKey] = useState<string | null>(null);
  const [restartArmed, setRestartArmed] = useState(false);
  const [restartingMission, setRestartingMission] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deletingMission, setDeletingMission] = useState(false);
  const [exportingMission, setExportingMission] = useState(false);
  const [exportedFolderPath, setExportedFolderPath] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useCachedViewState<"workflow" | "log">(
    `deep-analysis:${cacheScope}:active-tab:v2`,
    "workflow",
  );
  const [workflowDraft, setWorkflowDraft] = useState<DeepAnalysisWorkflowRevision | null>(null);
  const [workflowDraftDirty, setWorkflowDraftDirty] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState(false);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [activatingWorkflow, setActivatingWorkflow] = useState(false);
  const [arrangingWorkflow, setArrangingWorkflow] = useState(false);
  const [workflowRegenerateOpen, setWorkflowRegenerateOpen] = useState(false);
  const [workflowRegeneratePrompt, setWorkflowRegeneratePrompt] = useState("");
  const [regeneratingWorkflow, setRegeneratingWorkflow] = useState(false);
  const [workflowRegeneratePosition, setWorkflowRegeneratePosition] = useState({ top: 0, left: 0 });
  const [canvasScale, setCanvasScale] = useState(1);
  const [canvasOffset, setCanvasOffset] = useState({ x: 0, y: 0 });
  const [canvasPanning, setCanvasPanning] = useState(false);
  const [inspectorWidth, setInspectorWidth] = useState(storedInspectorWidth);
  const missionSettingsEditable = canEdit && ![
    "running",
    "paused",
    "awaiting_input",
  ].includes(mission?.status ?? "") && (!editingWorkflow || mission?.startMode === "manual");
  const missionSettingsDirty = mission !== null && (
    missionTitleDraft.trim() !== mission.title
    || missionObjectiveDraft.trim() !== mission.objective
    || analysisDepth !== mission.analysisDepth
    || answerLength !== mission.answerLength
    || outputMode !== mission.outputMode
    || outputFormat !== mission.outputFormat
    || (outputMode === "chat" ? null : targetOutputTokens) !== mission.targetOutputTokens
    || JSON.stringify(createExecution) !== JSON.stringify(mission.execution)
    || JSON.stringify(promptReferencesForObjective(selectedReferences, missionObjectiveDraft)) !== JSON.stringify(mission.promptReferences)
    || researchStartDate !== (mission.researchPeriod.startDate ?? "")
    || researchEndDate !== (mission.researchPeriod.endDate ?? "")
    || webSourceMode !== mission.webSourcePolicy.mode
    || JSON.stringify(parseDomainList(webSourceDomains)) !== JSON.stringify(mission.webSourcePolicy.domains)
    || JSON.stringify(parseDomainList(excludedWebSourceDomains)) !== JSON.stringify(mission.webSourcePolicy.excludedDomains)
  );
  const sourcePolicyValid = webSourceMode === "all" || parseDomainList(webSourceDomains).length > 0;
  const [connectionDraft, setConnectionDraft] = useState<{
    sourceNodeKey: string;
    sourceSide: WorkflowPortSide;
    pointerX: number;
    pointerY: number;
  } | null>(null);
  const [suppressedConnectionPortNodeKey, setSuppressedConnectionPortNodeKey] = useState<string | null>(null);
  const canvasViewportRef = useRef<HTMLDivElement>(null);
  const canvasControlsRef = useRef<HTMLDivElement>(null);
  const workflowLayoutRef = useRef<HTMLDivElement>(null);
  const createTitleRef = useRef<HTMLInputElement>(null);
  const createToolbarRef = useRef<HTMLDivElement>(null);
  const costDetailsRef = useRef<HTMLDivElement>(null);
  const createFileInputRef = useRef<HTMLInputElement>(null);
  const steerFileInputRef = useRef<HTMLInputElement>(null);
  const workflowRegenerateTriggerRef = useRef<HTMLButtonElement>(null);
  const liveOutputRef = useRef<HTMLPreElement>(null);
  const htmlOutputPreviewRef = useRef<HTMLIFrameElement>(null);
  const workflowRegenerateFontSize = workflowRegenerateTriggerRef.current
    ?.closest<HTMLElement>(".app-shell")
    ?.style.getPropertyValue("--conversation-font-size");
  const selectedExecutionId = createExecution
    ? `${createExecution.providerId}:${createExecution.modelKey}`
    : "";
  const selectedExecutionOption = executionOptions.find((option) => option.id === selectedExecutionId);
  const createEffortOptions = selectedExecutionOption?.effortOptions ?? [];
  const eventCursorRef = useRef(0);
  const handledCreateRequestRef = useRef(0);
  const workflowUndoStackRef = useRef<Array<{
    draft: DeepAnalysisWorkflowRevision;
    dirty: boolean;
    selectedNodeKey: string | null;
    selectedEdgeId: string | null;
  }>>([]);
  const canvasPanRef = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const nodeDragRef = useRef<{
    pointerId: number;
    nodeKey: string;
    clientX: number;
    clientY: number;
    positionX: number;
    positionY: number;
    moved: boolean;
  } | null>(null);
  const pendingNodeDragRef = useRef<{
    nodeKey: string;
    positionX: number;
    positionY: number;
  } | null>(null);
  const nodeDragFrameRef = useRef<number | null>(null);
  const connectionDragRef = useRef<{
    pointerId: number;
    sourceNodeKey: string;
    clientX: number;
    clientY: number;
    moved: boolean;
  } | null>(null);

  useEffect(() => {
    if (!creating) {
      setCreateElapsedSeconds(0);
      return;
    }
    const startedAt = Date.now();
    const updateElapsed = () => setCreateElapsedSeconds(Math.floor((Date.now() - startedAt) / 1_000));
    updateElapsed();
    const intervalId = window.setInterval(updateElapsed, 1_000);
    return () => window.clearInterval(intervalId);
  }, [creating]);

  useEffect(() => {
    setExportedFolderPath(null);
    setWorkflowRegenerateOpen(false);
    setWorkflowRegeneratePrompt("");
    setMissionRootSelected(false);
    setMissionTitleDraft(mission?.title ?? "");
    setMissionObjectiveDraft(mission?.objective ?? "");
    setAnalysisDepth(mission?.analysisDepth ?? "auto");
    setAnswerLength(mission?.answerLength ?? "auto");
    setOutputMode(mission?.outputMode ?? "auto");
    setOutputFormat(mission?.outputFormat ?? "markdown");
    setTargetOutputTokens(mission?.targetOutputTokens ?? 10_000);
    setCreateExecution(mission?.execution ?? execution);
    setSelectedReferences(mission ? selectedReferencesFromMission(mission) : []);
    setResearchStartDate(mission?.researchPeriod.startDate ?? "");
    setResearchEndDate(mission?.researchPeriod.endDate ?? "");
    setWebSourceMode(mission?.webSourcePolicy.mode ?? "all");
    setWebSourceDomains(mission?.webSourcePolicy.domains.join(", ") ?? "");
    setExcludedWebSourceDomains(mission?.webSourcePolicy.excludedDomains.join(", ") ?? "");
    setSteerInstruction("");
    setSteerReferences([]);
    setResearchInspectorOpen(false);
    setResearchInspector(null);
    setRefreshPreview(null);
    setRefreshArmed(false);
  }, [mission?.id]);

  useEffect(() => {
    if (selectedNodeKey) setMissionRootSelected(false);
  }, [selectedNodeKey]);

  useEffect(() => {
    if (!referenceTrigger) return;
    const closeReferenceMenuOutside = (event: PointerEvent) => {
      if (!createToolbarRef.current?.contains(event.target as Node)) {
        setReferenceTrigger(null);
      }
    };
    document.addEventListener("pointerdown", closeReferenceMenuOutside);
    return () => document.removeEventListener("pointerdown", closeReferenceMenuOutside);
  }, [referenceTrigger]);

  useEffect(() => {
    if (!workflowRegenerateOpen) return;
    const updatePosition = () => {
      const trigger = workflowRegenerateTriggerRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const width = Math.min(400, window.innerWidth - 24);
      setWorkflowRegeneratePosition({
        top: rect.bottom + 8,
        left: Math.min(Math.max(12, rect.left), window.innerWidth - width - 12),
      });
    };
    updatePosition();
    window.addEventListener("resize", updatePosition);
    return () => window.removeEventListener("resize", updatePosition);
  }, [workflowRegenerateOpen]);

  useEffect(() => onMissionsChange(missions), [missions, onMissionsChange]);
  useEffect(() => onMissionsLoadingChange(loadingList), [loadingList, onMissionsLoadingChange]);
  useEffect(() => onSelectedMissionChange(selectedMissionId), [onSelectedMissionChange, selectedMissionId]);

  useEffect(() => {
    if (!removedMissionIds.size) return;
    setMissions((current) => current.filter((item) => !removedMissionIds.has(item.id)));
  }, [removedMissionIds]);

  useEffect(() => {
    const fitInspectorToViewport = () => {
      setInspectorWidth((current) => Math.round(Math.min(Math.max(minimumInspectorWidth, current), maximumInspectorWidth())));
    };
    fitInspectorToViewport();
    const observer = new ResizeObserver(fitInspectorToViewport);
    if (workflowLayoutRef.current) observer.observe(workflowLayoutRef.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    setSelectedMissionId(requestedMissionId);
    if (requestedMissionId) setCreateOpen(false);
  }, [requestedMissionId]);

  useEffect(() => {
    if (createRequest <= 0 || createRequest <= handledCreateRequestRef.current) return;
    handledCreateRequestRef.current = createRequest;
    setTitle("");
    setObjective("");
    setAnalysisDepth("auto");
    setAnswerLength("auto");
    setOutputMode("auto");
    setOutputFormat("markdown");
    setTargetOutputTokens(10_000);
    setCreateExecution(execution);
    setSelectedReferences([]);
    setResearchStartDate("");
    setResearchEndDate("");
    setWebSourceMode("all");
    setWebSourceDomains("");
    setExcludedWebSourceDomains("");
    setReferenceTrigger(null);
    setReferenceQuery("");
    setCreateOpen(false);
    onCreateRequestHandled();
    void createManualMission();
  }, [createRequest, onCreateRequestHandled]);

  useEffect(() => {
    if (createOpen) setCreateExecution(execution);
  }, [createOpen, execution]);

  useEffect(() => {
    if (!projectId || !referenceTrigger) {
      setReferenceSuggestions([]);
      setLoadingReferences(false);
      return;
    }
    const controller = new AbortController();
    setLoadingReferences(true);
    const timer = window.setTimeout(() => {
      api.composer.listSuggestions(
        projectId,
        referenceTrigger,
        referenceQuery.trim(),
        controller.signal,
      )
        .then((page) => setReferenceSuggestions(page.items))
        .catch((caught) => {
          if (!controller.signal.aborted) setError(errorMessage(caught));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoadingReferences(false);
        });
    }, 120);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [projectId, referenceQuery, referenceTrigger]);
  useEffect(() => {
    setWorkflowDraft(null);
    setEditingWorkflow(false);
    setCreateOpen(false);
    setError(null);
    if (!projectId) return;

    const controller = new AbortController();
    setLoadingList(true);
    api.deepAnalysis
      .listMissions(projectId, controller.signal)
      .then((items) => {
        setMissions(items);
        const storedId = window.localStorage.getItem(selectedMissionStorageKey(projectId));
        const nextId = items.some((item) => item.id === storedId) ? storedId : items[0]?.id;
        setSelectedMissionId(nextId ?? null);
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          if (loadError instanceof ApiError && loadError.status === 404) {
            setMissions((current) => {
              const remaining = current.filter((item) => item.id !== selectedMissionId);
              setSelectedMissionId(remaining[0]?.id ?? null);
              if (!remaining.length) {
                window.localStorage.removeItem(selectedMissionStorageKey(projectId));
              }
              return remaining;
            });
          } else {
            setError(errorMessage(loadError));
          }
        }
      })
      .finally(() => setLoadingList(false));
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    if (!projectId || !selectedMissionId) {
      setMission(null);
      setSelectedNodeKey(null);
      setWorkflowDraft(null);
      setEditingWorkflow(false);
      return;
    }

    window.localStorage.setItem(
      selectedMissionStorageKey(projectId),
      selectedMissionId,
    );
    const controller = new AbortController();
    setLoadingMission(true);
    setError(null);
    api.deepAnalysis
      .getMission(selectedMissionId, controller.signal)
      .then((detail) => {
        eventCursorRef.current = detail.eventCursor;
        setMissionEvents(detail.id, []);
        const opensManualDraft = canEdit
          && detail.startMode === "manual"
          && detail.status === "draft"
          && detail.workflow.nodes.length === 0;
        setSelectedNodeKey(detail.workflow.nodes[0]?.nodeKey ?? null);
        setCostModeActive(false);
        setCostDetailsOpen(false);
        setRestartArmed(false);
        setDeleteArmed(false);
        setWorkflowDraft(null);
        setWorkflowDraftDirty(false);
        setEditingWorkflow(false);
        setMissionRootSelected(opensManualDraft);
        setMission(detail);
        if (opensManualDraft) {
          void api.deepAnalysis.createDraft(detail.id, detail.revision)
            .then((draft) => {
              setWorkflowDraft(draft);
              setEditingWorkflow(true);
              window.requestAnimationFrame(() => fitCanvasToViewport());
            })
            .catch((draftError) => setError(errorMessage(draftError)));
        }
        void api.deepAnalysis.listEvents(detail.id, 0, controller.signal)
          .then((events) => setMissionEvents(detail.id, events))
          .catch(() => {
            // Snapshot remains usable even if the audit log cannot be loaded.
          });
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(errorMessage(loadError));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingMission(false);
      });
    return () => controller.abort();
  }, [canEdit, projectId, selectedMissionId]);

  useEffect(() => {
    setCanvasScale(1);
    setCanvasOffset({ x: 0, y: 0 });
  }, [selectedMissionId]);

  useEffect(() => {
    eventCursorRef.current = mission?.eventCursor ?? 0;
  }, [mission?.id, mission?.eventCursor]);

  useEffect(() => {
    let active = true;
    void api.finance.getUsdKrwExchangeRate().then((result) => {
      if (active) setUsdKrwRate(result.rate);
    });
    return () => { active = false; };
  }, []);

  useEffect(() => {
    if (!costDetailsOpen || !mission) return;
    const controller = new AbortController();
    setLoadingCosts(true);
    void api.deepAnalysis.getCosts(mission.id, controller.signal)
      .then(setCostDetails)
      .catch((costError) => {
        if (!(costError instanceof DOMException && costError.name === "AbortError")) {
          setError(errorMessage(costError));
        }
      })
      .finally(() => setLoadingCosts(false));
    return () => controller.abort();
  }, [costDetailsOpen, mission?.id, mission?.eventCursor]);

  useEffect(() => {
    if (!costDetailsOpen) return;
    const closeCostDetailsOutside = (event: PointerEvent) => {
      if (costDetailsRef.current?.contains(event.target as Node)) return;
      setCostDetailsOpen(false);
    };
    document.addEventListener("pointerdown", closeCostDetailsOutside);
    return () => document.removeEventListener("pointerdown", closeCostDetailsOutside);
  }, [costDetailsOpen]);

  useEffect(() => {
    if (
      !selectedMissionId
      || !mission
      || mission.id !== selectedMissionId
      || !["running", "paused", "awaiting_input"].includes(mission.status)
    ) return;
    let active = true;
    let detailTimer: number | null = null;
    let projectionTimer: number | null = null;
    let refreshing = false;
    let refreshingProjection = false;
    const refreshDetail = async () => {
      if (refreshing || document.visibilityState !== "visible") return;
      refreshing = true;
      try {
        const detail = await api.deepAnalysis.getMission(selectedMissionId);
        if (!active) return;
        eventCursorRef.current = Math.max(
          eventCursorRef.current,
          detail.eventCursor,
        );
        setMission(detail);
        setMissions((current) =>
          current.map((item) => (item.id === detail.id ? detail : item)),
        );
      } catch {
        // Keep the last durable snapshot while EventSource reconnects.
      } finally {
        refreshing = false;
      }
    };
    const scheduleDetailRefresh = () => {
      if (detailTimer !== null) return;
      detailTimer = window.setTimeout(() => {
        detailTimer = null;
        void refreshDetail();
      }, 100);
    };
    const refreshProjection = async () => {
      if (refreshingProjection || document.visibilityState !== "visible") return;
      refreshingProjection = true;
      try {
        const projection = await api.deepAnalysis.getProjection(selectedMissionId);
        if (!active) return;
        eventCursorRef.current = Math.max(eventCursorRef.current, projection.eventCursor);
        setMission((current) => {
          if (!current || current.id !== projection.missionId) return current;
          const projectedNodes = new Map(projection.nodes.map((node) => [node.id, node]));
          return {
            ...current,
            eventCursor: Math.max(current.eventCursor, projection.eventCursor),
            status: projection.status,
            spentMicrousd: projection.spentMicrousd,
            revision: Math.max(current.revision, projection.revision),
            workflow: {
              ...current.workflow,
              nodes: current.workflow.nodes.map((node) => ({
                ...node,
                ...projectedNodes.get(node.id),
              })),
            },
          };
        });
        setMissions((current) => current.map((item) => (
          item.id === projection.missionId
            ? {
                ...item,
                status: projection.status,
                spentMicrousd: projection.spentMicrousd,
                revision: Math.max(item.revision, projection.revision),
              }
            : item
        )));
      } catch {
        // Event replay remains authoritative; visibility reconciliation retries later.
      } finally {
        refreshingProjection = false;
      }
    };
    const scheduleProjectionRefresh = () => {
      if (projectionTimer !== null) return;
      projectionTimer = window.setTimeout(() => {
        projectionTimer = null;
        void refreshProjection();
      }, 100);
    };
    const closeStream = api.deepAnalysis.openEventStream(
      selectedMissionId,
      eventCursorRef.current,
      {
        onEvent: (event) => {
          if (!active || event.sequence <= eventCursorRef.current) return;
          eventCursorRef.current = event.sequence;
          appendMissionEvent(selectedMissionId, event);
          if (DETAIL_REFRESH_EVENT_TYPES.has(event.type)) scheduleDetailRefresh();
          else scheduleProjectionRefresh();
        },
      },
    );
    const projectionInterval = window.setInterval(() => {
      void refreshProjection();
    }, 500);
    const refreshWhenVisible = () => {
      if (document.visibilityState !== "visible") return;
      void refreshDetail();
      void refreshProjection();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      active = false;
      closeStream();
      window.clearInterval(projectionInterval);
      if (detailTimer !== null) window.clearTimeout(detailTimer);
      if (projectionTimer !== null) window.clearTimeout(projectionTimer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [mission?.id, mission?.status, selectedMissionId]);

  const rawWorkflow = workflowDraft ?? mission?.workflow ?? null;
  const shownWorkflow = useMemo(
    () => rawWorkflow && !editingWorkflow ? arrangeWorkflowTopDown(rawWorkflow) : rawWorkflow,
    [editingWorkflow, rawWorkflow],
  );
  const shownWorkflowNodeByKey = useMemo(
    () => new Map((shownWorkflow?.nodes ?? []).map((node) => [node.nodeKey, node])),
    [shownWorkflow?.nodes],
  );
  const workflowMissionRoot = useMemo(() => {
    const nodes = shownWorkflow?.nodes ?? [];
    if (!shownWorkflow) return null;
    const connectedNodeKeys = new Set(
      shownWorkflow.edges.flatMap((edge) => [edge.sourceNodeKey, edge.targetNodeKey]),
    );
    const targetNodeKeys = new Set((shownWorkflow?.edges ?? []).map((edge) => edge.targetNodeKey));
    const connectedNodes = nodes.filter(
      (node) => connectedNodeKeys.has(node.nodeKey) && !targetNodeKeys.has(node.nodeKey),
    );
    return { connectedNodes, position: workflowMissionRootPosition };
  }, [shownWorkflow]);
  const workflowCanvasSize = useMemo(() => ({
    width: Math.max(
      720,
      ...(shownWorkflow?.nodes ?? []).map((node) => node.positionX + workflowNodeWidth + 48),
      ...(workflowMissionRoot ? [workflowMissionRoot.position.positionX + workflowNodeWidth + 48] : []),
    ),
    height: Math.max(
      540,
      ...(shownWorkflow?.nodes ?? []).map((node) => node.positionY + workflowNodeHeight + 48),
      ...(workflowMissionRoot ? [workflowMissionRoot.position.positionY + workflowNodeHeight + 48] : []),
    ),
  }), [shownWorkflow?.nodes, workflowMissionRoot]);
  const selectedNode = useMemo(
    () => selectedNodeKey ? shownWorkflowNodeByKey.get(selectedNodeKey) ?? null : null,
    [selectedNodeKey, shownWorkflowNodeByKey],
  );
  const selectedNodeShowsSource = selectedNode?.id === outputSourceNodeId;

  useEffect(() => {
    setOutputActionStatus(null);
  }, [selectedNode?.id]);

  async function downloadSelectedNodeOutput() {
    if (!projectId || !selectedNode?.outputProjectFileId) return;
    setOutputActionStatus(null);
    try {
      const download = await api.projectFiles.download(
        projectId,
        selectedNode.outputProjectFileId,
      );
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "산출물을 다운로드하지 못했습니다.");
    }
  }

  async function shareSelectedNodeOutput() {
    if (!selectedNode?.conversationId) return;
    setOutputActionStatus(null);
    try {
      const share = await api.sharing.create(selectedNode.conversationId);
      await copyText(new URL(share.viewerPath, window.location.origin).toString());
      setOutputActionStatus("공유 링크를 복사했습니다.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "공유 링크를 만들지 못했습니다.");
    }
  }

  useEffect(() => {
    if (selectedNode?.status !== "running" || !selectedNode.liveOutput) return;
    const output = liveOutputRef.current;
    if (output) output.scrollTop = output.scrollHeight;
  }, [selectedNode?.liveOutput, selectedNode?.nodeKey, selectedNode?.status]);

  function undoWorkflowChange() {
    const previous = workflowUndoStackRef.current.pop();
    if (!previous) return false;
    setWorkflowDraft(previous.draft);
    setWorkflowDraftDirty(previous.dirty);
    setSelectedNodeKey(previous.selectedNodeKey);
    setSelectedEdgeId(previous.selectedEdgeId);
    setConnectionDraft(null);
    connectionDragRef.current = null;
    return true;
  }

  useEffect(() => {
    if (!editingWorkflow) return undefined;
    const undoNodeChange = (event: KeyboardEvent) => {
      if (
        event.defaultPrevented
        || event.shiftKey
        || !(event.ctrlKey || event.metaKey)
        || event.key.toLowerCase() !== "z"
      ) return;
      const target = event.target;
      if (
        target instanceof HTMLElement
        && (target.isContentEditable || target.matches("input, textarea, select"))
      ) return;
      if (undoWorkflowChange()) event.preventDefault();
    };
    window.addEventListener("keydown", undoNodeChange);
    return () => window.removeEventListener("keydown", undoNodeChange);
  }, [editingWorkflow]);

  useEffect(() => {
    if (!editingWorkflow || !workflowDraft || (!selectedNodeKey && !selectedEdgeId)) return undefined;
    const deleteSelection = (event: KeyboardEvent) => {
      if ((event.key !== "Delete" && event.key !== "Backspace") || event.defaultPrevented) return;
      const target = event.target;
      if (
        target instanceof HTMLElement
        && (target.isContentEditable || target.matches("input, textarea, select"))
      ) return;
      if (selectedEdgeId) {
        event.preventDefault();
        removeDraftEdge(selectedEdgeId);
        return;
      }
      const node = workflowDraft.nodes.find((item) => item.nodeKey === selectedNodeKey);
      if (!node) return;
      event.preventDefault();
      removeDraftNode(node.nodeKey);
    };
    window.addEventListener("keydown", deleteSelection);
    return () => window.removeEventListener("keydown", deleteSelection);
  }, [editingWorkflow, selectedEdgeId, selectedNodeKey, workflowDraft]);

  useEffect(() => {
    if (!connectionDraft) return undefined;
    const cancelConnection = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setConnectionDraft(null);
      connectionDragRef.current = null;
    };
    window.addEventListener("keydown", cancelConnection);
    return () => window.removeEventListener("keydown", cancelConnection);
  }, [connectionDraft]);

  useEffect(() => {
    if (editingWorkflow) return;
    setConnectionDraft(null);
    setSelectedEdgeId(null);
    connectionDragRef.current = null;
  }, [editingWorkflow]);
  const activeNode = useMemo(
    () => mission?.workflow.nodes.find((node) => node.status === "running") ?? null,
    [mission],
  );
  const completedNodeCount = useMemo(
    () => mission?.workflow.nodes.filter((node) => node.status === "completed").length ?? 0,
    [mission],
  );
  const workflowTopology = useMemo(() => {
    const outgoing = new Map<string, number>();
    const incoming = new Map<string, number>();
    for (const edge of shownWorkflow?.edges ?? []) {
      outgoing.set(edge.sourceNodeKey, (outgoing.get(edge.sourceNodeKey) ?? 0) + 1);
      incoming.set(edge.targetNodeKey, (incoming.get(edge.targetNodeKey) ?? 0) + 1);
    }
    const branchNodeKeys = new Set(
      [...outgoing.entries()].filter(([, count]) => count > 1).map(([key]) => key),
    );
    const mergeNodeKeys = new Set(
      [...incoming.entries()].filter(([, count]) => count > 1).map(([key]) => key),
    );
    return {
      branchCount: branchNodeKeys.size,
      mergeCount: mergeNodeKeys.size,
      branchNodeKeys,
      mergeNodeKeys,
    };
  }, [shownWorkflow?.edges]);
  const activeTabSummary = createOpen
    ? "0/1 완료 · 작성 중"
    : !mission
      ? null
      : activeTab === "workflow"
        ? `${completedNodeCount}/${shownWorkflow?.nodes.length ?? 0} 완료 · 분기 ${workflowTopology.branchCount} · 합류 ${workflowTopology.mergeCount} · 입력 자료 ${mission.sourceManifest.length}개 · Revision ${shownWorkflow?.revisionNumber}`
        : null;

  function updateCanvasScale(nextScale: number, originX?: number, originY?: number) {
    const viewport = canvasViewportRef.current;
    const boundedScale = Math.min(maximumCanvasScale, Math.max(minimumCanvasScale, nextScale));
    if (!viewport || boundedScale === canvasScale) return;

    const localX = originX ?? viewport.clientWidth / 2;
    const localY = originY ?? viewport.clientHeight / 2;
    const contentX = (localX - canvasOffset.x) / canvasScale;
    const contentY = (localY - canvasOffset.y) / canvasScale;
    setCanvasScale(boundedScale);
    setCanvasOffset({
      x: localX - contentX * boundedScale,
      y: localY - contentY * boundedScale,
    });
  }

  function handleCanvasWheel(event: ReactWheelEvent<HTMLDivElement>) {
    event.preventDefault();
    const viewport = canvasViewportRef.current;
    if (!viewport) return;
    const rect = viewport.getBoundingClientRect();
    const step = event.deltaY < 0 ? 0.1 : -0.1;
    updateCanvasScale(
      Math.round((canvasScale + step) * 10) / 10,
      event.clientX - rect.left,
      event.clientY - rect.top,
    );
  }

  function fitNodesToViewport(nodes: WorkflowNodePosition[]) {
    const viewport = canvasViewportRef.current;
    if (!viewport || !nodes.length) return;

    const padding = 36;
    const controlsBottom = canvasControlsRef.current
      ? canvasControlsRef.current.getBoundingClientRect().bottom - viewport.getBoundingClientRect().top
      : 0;
    const contentTop = Math.max(padding, controlsBottom + 12);
    const availableHeight = Math.max(1, viewport.clientHeight - contentTop - padding);
    const minX = Math.min(...nodes.map((node) => node.positionX));
    const minY = Math.min(...nodes.map((node) => node.positionY));
    const maxX = Math.max(...nodes.map((node) => node.positionX + workflowNodeWidth));
    const maxY = Math.max(...nodes.map((node) => node.positionY + workflowNodeHeight));
    const contentWidth = Math.max(1, maxX - minX);
    const contentHeight = Math.max(1, maxY - minY);
    const fittedScale = Math.min(
      1,
      Math.max(
        minimumCanvasScale,
        Math.min(
          (viewport.clientWidth - padding * 2) / contentWidth,
          availableHeight / contentHeight,
        ),
      ),
    );
    setCanvasScale(fittedScale);
    setCanvasOffset({
      x: (viewport.clientWidth - contentWidth * fittedScale) / 2 - minX * fittedScale,
      y: contentTop + Math.max(0, (availableHeight - contentHeight * fittedScale) / 2) - minY * fittedScale,
    });
  }

  function fitCanvasToViewport() {
    fitNodesToViewport([
      ...(workflowMissionRoot ? [workflowMissionRoot.position] : []),
      ...(shownWorkflow?.nodes ?? []),
    ]);
  }

  function maximumInspectorWidth() {
    const available = workflowLayoutRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    return Math.max(minimumInspectorWidth, available * maximumInspectorWidthRatio);
  }

  function clampInspectorWidth(value: number) {
    return Math.round(Math.min(Math.max(minimumInspectorWidth, value), maximumInspectorWidth()));
  }

  function rememberInspectorWidth(value: number) {
    try {
      window.localStorage.setItem(inspectorWidthStorageKey, String(value));
    } catch {
      // The current session remains resizable when browser storage is unavailable.
    }
  }

  function beginInspectorResize(event: ReactPointerEvent<HTMLDivElement>) {
    const layout = workflowLayoutRef.current;
    if (!layout) return;
    event.preventDefault();
    const right = layout.getBoundingClientRect().right;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const move = (pointerEvent: PointerEvent) => {
      setInspectorWidth(clampInspectorWidth(right - pointerEvent.clientX));
    };
    const finish = (pointerEvent: PointerEvent) => {
      const nextWidth = clampInspectorWidth(right - pointerEvent.clientX);
      setInspectorWidth(nextWidth);
      rememberInspectorWidth(nextWidth);
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", finish);
      handle.removeEventListener("pointercancel", finish);
      window.requestAnimationFrame(fitCanvasToViewport);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", finish);
    handle.addEventListener("pointercancel", finish);
  }

  function resizeInspectorWithKeyboard(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const nextWidth = clampInspectorWidth(inspectorWidth + (event.key === "ArrowLeft" ? 16 : -16));
    setInspectorWidth(nextWidth);
    rememberInspectorWidth(nextWidth);
    window.requestAnimationFrame(fitCanvasToViewport);
  }

  useEffect(() => {
    if (!shownWorkflow?.graphDigest) return;
    const frame = window.requestAnimationFrame(() => fitCanvasToViewport());
    return () => window.cancelAnimationFrame(frame);
  }, [shownWorkflow?.graphDigest]);

  function beginCanvasPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as Element).closest("button")) return;
    if (connectionDraft) {
      setConnectionDraft(null);
      connectionDragRef.current = null;
      return;
    }
    setSelectedEdgeId(null);
    const viewport = canvasViewportRef.current;
    if (!viewport) return;
    event.preventDefault();
    canvasPanRef.current = {
      pointerId: event.pointerId,
      clientX: event.clientX,
      clientY: event.clientY,
      offsetX: canvasOffset.x,
      offsetY: canvasOffset.y,
    };
    viewport.setPointerCapture(event.pointerId);
    setCanvasPanning(true);
  }

  function moveCanvasPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (connectionDraft && !canvasPanRef.current) {
      const point = canvasPointFromClient(event.clientX, event.clientY);
      if (point) setConnectionDraft({ ...connectionDraft, pointerX: point.x, pointerY: point.y });
      return;
    }
    const pan = canvasPanRef.current;
    const viewport = canvasViewportRef.current;
    if (!pan || !viewport || pan.pointerId !== event.pointerId) return;
    setCanvasOffset({
      x: pan.offsetX + event.clientX - pan.clientX,
      y: pan.offsetY + event.clientY - pan.clientY,
    });
  }

  function endCanvasPan(event: ReactPointerEvent<HTMLDivElement>) {
    const pan = canvasPanRef.current;
    if (pan?.pointerId !== event.pointerId) return;
    canvasPanRef.current = null;
    setCanvasPanning(false);
  }

  async function beginWorkflowEdit() {
    if (!mission || editingWorkflow) return;
    setError(null);
    try {
      const draft = await api.deepAnalysis.createDraft(mission.id, mission.revision);
      const arranged = arrangeWorkflowTopDown(draft);
      workflowUndoStackRef.current = [];
      setWorkflowDraft(arranged);
      setWorkflowDraftDirty(true);
      setEditingWorkflow(true);
      setSelectedNodeKey(arranged.nodes[0]?.nodeKey ?? null);
      window.requestAnimationFrame(() => fitNodesToViewport(arranged.nodes));
    } catch (draftError) {
      setError(errorMessage(draftError));
    }
  }

  async function autoArrangeWorkflow() {
    if (!mission || !shownWorkflow || arrangingWorkflow) return;
    if (!canEdit || (mission.status !== "draft" && mission.status !== "ready")) return;
    setArrangingWorkflow(true);
    setError(null);
    try {
      const draft = workflowDraft ?? await api.deepAnalysis.createDraft(mission.id, mission.revision);
      const arranged = arrangeWorkflowTopDown(draft, true);
      setWorkflowDraft(arranged);
      setWorkflowDraftDirty(true);
      setEditingWorkflow(true);
      setSelectedNodeKey(arranged.nodes[0]?.nodeKey ?? null);
      window.requestAnimationFrame(() => fitNodesToViewport([workflowMissionRootPosition, ...arranged.nodes]));
    } catch (draftError) {
      setError(errorMessage(draftError));
    } finally {
      setArrangingWorkflow(false);
    }
  }

  async function regenerateWorkflow(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = workflowRegeneratePrompt.trim();
    if (!mission || !prompt || regeneratingWorkflow) return;
    if (["running", "paused", "awaiting_input"].includes(mission.status)) return;
    setRegeneratingWorkflow(true);
    setError(null);
    try {
      const regenerated = await api.deepAnalysis.regenerateWorkflow(mission.id, {
        expectedRevision: mission.revision,
        prompt,
      });
      setMission(regenerated);
      setMissions((current) => current.map((item) => item.id === regenerated.id ? regenerated : item));
      setWorkflowDraft(null);
      setWorkflowDraftDirty(false);
      setEditingWorkflow(false);
      workflowUndoStackRef.current = [];
      setSelectedEdgeId(null);
      setSelectedNodeKey(regenerated.workflow.nodes[0]?.nodeKey ?? null);
      setWorkflowRegeneratePrompt("");
      setWorkflowRegenerateOpen(false);
      window.requestAnimationFrame(() => fitNodesToViewport(regenerated.workflow.nodes));
    } catch (regenerateError) {
      setError(errorMessage(regenerateError));
    } finally {
      setRegeneratingWorkflow(false);
    }
  }

  function draftPayload(draft: DeepAnalysisWorkflowRevision) {
    return {
      expectedRevision: mission?.revision ?? 0,
      nodes: draft.nodes.map((node) => ({
        nodeKey: node.nodeKey,
        nodeType: node.nodeType,
        title: node.title,
        purpose: node.purpose,
        positionX: Math.round(node.positionX),
        positionY: Math.round(node.positionY),
        config: node.config,
      })),
      edges: draft.edges.map((edge) => ({
        sourceNodeKey: edge.sourceNodeKey,
        targetNodeKey: edge.targetNodeKey,
      })),
    };
  }

  async function saveWorkflowDraft() {
    if (!mission || !workflowDraft || savingWorkflow) return null;
    setSavingWorkflow(true);
    setError(null);
    try {
      const saved = await api.deepAnalysis.updateDraft(
        mission.id,
        draftPayload(workflowDraft),
      );
      setWorkflowDraft(saved);
      setWorkflowDraftDirty(false);
      return saved;
    } catch (draftError) {
      setError(errorMessage(draftError));
      return null;
    } finally {
      setSavingWorkflow(false);
    }
  }

  async function activateWorkflowDraft() {
    if (!mission || !workflowDraft || activatingWorkflow) return null;
    setActivatingWorkflow(true);
    try {
      const saved = workflowDraftDirty ? await saveWorkflowDraft() : workflowDraft;
      if (!saved) return null;
      const activated = await api.deepAnalysis.activateDraft(mission.id, mission.revision);
      setMission(activated);
      setMissions((current) => current.map((item) => item.id === activated.id ? activated : item));
      setWorkflowDraft(null);
      setWorkflowDraftDirty(false);
      setEditingWorkflow(false);
      setSelectedNodeKey(activated.workflow.nodes[0]?.nodeKey ?? null);
      return activated;
    } catch (draftError) {
      setError(errorMessage(draftError));
      return null;
    } finally {
      setActivatingWorkflow(false);
    }
  }

  function beginNodeDrag(event: ReactPointerEvent<HTMLButtonElement>, node: DeepAnalysisWorkflowNode) {
    if (!editingWorkflow || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    nodeDragRef.current = {
      pointerId: event.pointerId,
      nodeKey: node.nodeKey,
      clientX: event.clientX,
      clientY: event.clientY,
      positionX: node.positionX,
      positionY: node.positionY,
      moved: false,
    };
    pendingNodeDragRef.current = null;
    if (nodeDragFrameRef.current !== null) window.cancelAnimationFrame(nodeDragFrameRef.current);
    nodeDragFrameRef.current = null;
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function applyPendingNodeDrag() {
    nodeDragFrameRef.current = null;
    const pending = pendingNodeDragRef.current;
    pendingNodeDragRef.current = null;
    if (!pending) return;
    setWorkflowDraft((current) => current ? {
      ...current,
      nodes: current.nodes.map((node) => node.nodeKey === pending.nodeKey
        ? { ...node, positionX: pending.positionX, positionY: pending.positionY }
        : node),
    } : current);
    setWorkflowDraftDirty(true);
  }

  function moveNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !workflowDraft) return;
    const dx = (event.clientX - drag.clientX) / canvasScale;
    const dy = (event.clientY - drag.clientY) / canvasScale;
    drag.moved = drag.moved || Math.hypot(dx, dy) > 3;
    pendingNodeDragRef.current = {
      nodeKey: drag.nodeKey,
      positionX: drag.positionX + dx,
      positionY: drag.positionY + dy,
    };
    if (nodeDragFrameRef.current === null) {
      nodeDragFrameRef.current = window.requestAnimationFrame(applyPendingNodeDrag);
    }
  }

  function endNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (nodeDragFrameRef.current !== null) window.cancelAnimationFrame(nodeDragFrameRef.current);
    applyPendingNodeDrag();
    nodeDragRef.current = null;
    if (drag.moved) setSuppressedConnectionPortNodeKey(drag.nodeKey);
    setSelectedNodeKey(drag.nodeKey);
  }

  useEffect(() => () => {
    if (nodeDragFrameRef.current !== null) window.cancelAnimationFrame(nodeDragFrameRef.current);
  }, []);

  function canvasPointFromClient(clientX: number, clientY: number) {
    const viewport = canvasViewportRef.current;
    if (!viewport) return null;
    const rect = viewport.getBoundingClientRect();
    return {
      x: (clientX - rect.left - canvasOffset.x) / canvasScale,
      y: (clientY - rect.top - canvasOffset.y) / canvasScale,
    };
  }

  function beginConnection(
    sourceNodeKey: string,
    sourceSide: WorkflowPortSide,
    clientX?: number,
    clientY?: number,
  ) {
    if (!editingWorkflow || !workflowDraft) return;
    const source = workflowDraft.nodes.find((node) => node.nodeKey === sourceNodeKey);
    if (!source) return;
    const sourcePoint = workflowPortPoint(source, sourceSide);
    const sourceVector = workflowPortVector(sourceSide);
    const point = clientX === undefined || clientY === undefined
      ? {
          x: sourcePoint.x + sourceVector.x * 40,
          y: sourcePoint.y + sourceVector.y * 40,
        }
      : canvasPointFromClient(clientX, clientY);
    if (!point) return;
    setConnectionDraft({ sourceNodeKey, sourceSide, pointerX: point.x, pointerY: point.y });
  }

  function completeConnection(targetNodeKey: string) {
    if (!workflowDraft || !connectionDraft || connectionDraft.sourceNodeKey === targetNodeKey) return;
    const sourceNodeKey = connectionDraft.sourceNodeKey;
    const exists = workflowDraft.edges.some(
      (edge) => edge.sourceNodeKey === sourceNodeKey && edge.targetNodeKey === targetNodeKey,
    );
    if (!exists) {
      setWorkflowDraft({
        ...workflowDraft,
        edges: [
          ...workflowDraft.edges,
          { id: `draft:${sourceNodeKey}:${targetNodeKey}`, sourceNodeKey, targetNodeKey, edgeType: "sequence" },
        ],
      });
      setWorkflowDraftDirty(true);
    }
    setSelectedEdgeId(exists ? null : `draft:${sourceNodeKey}:${targetNodeKey}`);
    setConnectionDraft(null);
    connectionDragRef.current = null;
  }

  function beginConnectionDrag(
    event: ReactPointerEvent<HTMLButtonElement>,
    sourceNodeKey: string,
    sourceSide: WorkflowPortSide,
  ) {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    beginConnection(sourceNodeKey, sourceSide, event.clientX, event.clientY);
    connectionDragRef.current = {
      pointerId: event.pointerId,
      sourceNodeKey,
      clientX: event.clientX,
      clientY: event.clientY,
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveConnectionDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = connectionDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    drag.moved = drag.moved || Math.hypot(event.clientX - drag.clientX, event.clientY - drag.clientY) > 3;
    const point = canvasPointFromClient(event.clientX, event.clientY);
    if (point) setConnectionDraft((current) => current ? { ...current, pointerX: point.x, pointerY: point.y } : current);
  }

  function endConnectionDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = connectionDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (drag.moved) {
      const target = document
        .elementFromPoint(event.clientX, event.clientY)
        ?.closest<HTMLElement>("[data-connection-input]")
        ?.dataset.connectionInput;
      if (target && target !== drag.sourceNodeKey) completeConnection(target);
      else setConnectionDraft(null);
      connectionDragRef.current = null;
    }
  }

  function handleNodeKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    node: DeepAnalysisWorkflowNode,
  ) {
    if (!editingWorkflow || !workflowDraft) return;
    const direction = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    }[event.key];
    if (!direction) return;
    event.preventDefault();
    const distance = event.shiftKey ? 40 : 10;
    setWorkflowDraft({
      ...workflowDraft,
      nodes: workflowDraft.nodes.map((item) => item.nodeKey === node.nodeKey
        ? {
            ...item,
            positionX: Math.max(0, item.positionX + direction[0] * distance),
            positionY: Math.max(0, item.positionY + direction[1] * distance),
          }
        : item),
    });
    setWorkflowDraftDirty(true);
  }

  function addDraftNode() {
    if (!workflowDraft) return;
    const viewport = canvasViewportRef.current;
    if (!viewport) return;
    const used = new Set(workflowDraft.nodes.map((node) => node.nodeKey));
    let number = 10;
    while (used.has(`N${String(number).padStart(3, "0")}`)) number += 1;
    const nodeKey = `N${String(number).padStart(3, "0")}`;
    const verticalPlacementStep = 118;
    const centeredPositionX = (viewport.clientWidth / 2 - canvasOffset.x) / canvasScale - workflowNodeWidth / 2;
    const centeredPositionY = (viewport.clientHeight / 2 - canvasOffset.y) / canvasScale - 43;
    const minimumPositionX = centeredPositionX;
    const cascadeOffset = 32;
    const lastAddedNode = [...workflowDraft.nodes].reverse().find((node) => node.id.startsWith("draft:"));
    let positionX = Math.max(lastAddedNode ? lastAddedNode.positionX + cascadeOffset : centeredPositionX, minimumPositionX);
    let positionY = lastAddedNode ? lastAddedNode.positionY + cascadeOffset : centeredPositionY;
    const occupiedPositions = [...workflowDraft.nodes, workflowMissionRootPosition];
    while (occupiedPositions.some(
      (node) => Math.abs(node.positionX - positionX) < workflowNodeWidth + 24
        && Math.abs(node.positionY - positionY) < workflowNodeHeight + 24,
    )) {
      positionY += verticalPlacementStep;
    }
    const node: DeepAnalysisWorkflowNode = {
      id: `draft:${nodeKey}`,
      nodeKey,
      nodeType: "research",
      title: "새 분석 단계",
      purpose: "이 단계에서 확인할 질문과 산출물을 정의해 주세요.",
      status: "planned",
      sequence: workflowDraft.nodes.length + 1,
      positionX,
      positionY,
      config: {}, conversationId: null, runId: null, outputProjectFileId: null, outputLogicalPath: null,
      outputSummary: "", outputMarkdown: "", generatedFiles: [], runHistory: [],
      runStatus: null, executionPrompt: null, contextManifest: null, liveOutput: "", errorMessage: null, actualCostMicrousd: 0,
      startedAt: null, finishedAt: null,
    };
    workflowUndoStackRef.current.push({
      draft: workflowDraft,
      dirty: workflowDraftDirty,
      selectedNodeKey,
      selectedEdgeId,
    });
    setWorkflowDraft({ ...workflowDraft, nodes: [...workflowDraft.nodes, node] });
    setWorkflowDraftDirty(true);
    setSelectedNodeKey(nodeKey);
  }

  function removeDraftEdge(edgeId: string) {
    if (!workflowDraft) return;
    setWorkflowDraft({
      ...workflowDraft,
      edges: workflowDraft.edges.filter((edge) => edge.id !== edgeId),
    });
    setWorkflowDraftDirty(true);
    setSelectedEdgeId(null);
  }

  function removeDraftNode(nodeKey: string) {
    if (!workflowDraft) return;
    const node = workflowDraft.nodes.find((item) => item.nodeKey === nodeKey);
    if (!node || workflowDraft.nodes.length === 1) return;
    const remainingNodes = workflowDraft.nodes.filter((item) => item.nodeKey !== nodeKey);
    workflowUndoStackRef.current.push({
      draft: workflowDraft,
      dirty: workflowDraftDirty,
      selectedNodeKey,
      selectedEdgeId,
    });
    setWorkflowDraft({
      ...workflowDraft,
      nodes: remainingNodes,
      edges: workflowDraft.edges.filter((edge) => edge.sourceNodeKey !== nodeKey && edge.targetNodeKey !== nodeKey),
    });
    setWorkflowDraftDirty(true);
    setSelectedNodeKey(remainingNodes[0]?.nodeKey ?? null);
  }

  async function startMission() {
    if (!mission || startingMission) return;
    setStartingMission(true);
    setError(null);
    try {
      const missionToStart = editingWorkflow ? await activateWorkflowDraft() : mission;
      if (!missionToStart) return;
      const started = await api.deepAnalysis.startMission(missionToStart.id, {
        expectedRevision: missionToStart.revision,
      });
      setMission(started);
      setMissions((current) => current.map((item) => item.id === started.id ? started : item));
      setSelectedNodeKey(started.workflow.nodes[0]?.nodeKey ?? null);
    } catch (startError) {
      setError(errorMessage(startError));
    } finally {
      setStartingMission(false);
    }
  }

  async function createManualMission() {
    if (!projectId || creating) return;
    setCreating(true);
    setActiveTab("workflow");
    setSelectedMissionId(null);
    setMission(null);
    setSelectedNodeKey(null);
    setMissionRootSelected(false);
    setWorkflowDraft(null);
    setEditingWorkflow(false);
    setError(null);
    try {
      const created = await api.deepAnalysis.createMission(projectId, {
        title: "새 분석",
        objective: "",
        workflowStartMode: "manual",
        autonomyMode: "balanced",
        analysisDepth: "auto",
        answerLength: "auto",
        outputMode: "auto",
        outputFormat: "markdown",
        targetOutputTokens: 10_000,
        execution: execution ?? undefined,
        promptReferences: [],
        researchPeriod: { startDate: null, endDate: null },
        webSourcePolicy: { mode: "all", domains: [], excludedDomains: [] },
      });
      setMissions((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setMission(created);
      setMissionRootSelected(true);
      setSelectedMissionId(created.id);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setCreating(false);
    }
  }

  async function cancelMission() {
    if (!mission || cancellingMission) return;
    setCancellingMission(true);
    setError(null);
    try {
      const cancelled = await api.deepAnalysis.cancelMission(mission.id, {
        expectedRevision: mission.revision,
      });
      setMission(cancelled);
      setMissions((current) => current.map((item) => item.id === cancelled.id ? cancelled : item));
    } catch (cancelError) {
      setError(errorMessage(cancelError));
    } finally {
      setCancellingMission(false);
    }
  }

  async function toggleMissionPause() {
    if (!mission || pausingMission) return;
    setPausingMission(true);
    setError(null);
    try {
      const updated = mission.status === "paused"
        ? await api.deepAnalysis.resumeMission(mission.id, { expectedRevision: mission.revision })
        : await api.deepAnalysis.pauseMission(mission.id, { expectedRevision: mission.revision });
      eventCursorRef.current = updated.eventCursor;
      setMission(updated);
      setMissions((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (pauseError) {
      setError(errorMessage(pauseError));
    } finally {
      setPausingMission(false);
    }
  }

  async function exportMission() {
    if (!mission || exportingMission) return;
    const exportStartedAt = Date.now();
    setExportingMission(true);
    setExportedFolderPath(null);
    setError(null);
    try {
      const operation = await api.deepAnalysis.createExport(mission.id);
      const folderPath = operation.manifest.folderPath;
      setExportedFolderPath(typeof folderPath === "string" ? folderPath : operation.filename);
    } catch (exportError) {
      setError(errorMessage(exportError));
    } finally {
      const cooldownRemainingMs = Math.max(0, 1_000 - (Date.now() - exportStartedAt));
      if (cooldownRemainingMs > 0) {
        await new Promise<void>((resolve) => window.setTimeout(resolve, cooldownRemainingMs));
      }
      setExportingMission(false);
    }
  }

  async function retryNode(node: DeepAnalysisWorkflowNode) {
    if (!mission || retryingNodeKey) return;
    setRetryingNodeKey(node.nodeKey);
    setError(null);
    try {
      const retried = await api.deepAnalysis.retryMission(mission.id, {
        expectedRevision: mission.revision,
        nodeKey: node.nodeKey,
      });
      setMission(retried);
      setMissions((current) => current.map((item) => item.id === retried.id ? retried : item));
      setSelectedNodeKey(node.nodeKey);
    } catch (retryError) {
      setError(errorMessage(retryError));
    } finally {
      setRetryingNodeKey(null);
    }
  }

  async function restartMission() {
    if (!mission || restartingMission) return;
    if (!restartArmed) {
      setRestartArmed(true);
      return;
    }
    setRestartingMission(true);
    setError(null);
    try {
      const restarted = await api.deepAnalysis.restartMission(mission.id, {
        expectedRevision: mission.revision,
      });
      setMission(restarted);
      setMissions((current) => current.map((item) => item.id === restarted.id ? restarted : item));
      setMissionRootSelected(false);
      setSelectedNodeKey(restarted.workflow.nodes.find((node) => node.status === "running")?.nodeKey ?? null);
      setRestartArmed(false);
    } catch (restartError) {
      setError(errorMessage(restartError));
      setRestartArmed(false);
    } finally {
      setRestartingMission(false);
    }
  }

  async function uploadSteerSources(files: File[]) {
    if (!projectId || !files.length || uploadingSteerSources) return;
    setUploadingSteerSources(true);
    setError(null);
    try {
      const uploadedReferences: SelectedMissionReference[] = [];
      for (const file of files) {
        const uploaded = await api.projectFiles.upload(
          projectId,
          file,
          file.name,
          "심층분석 실행 중 추가 자료",
        );
        uploadedReferences.push({
          key: `file:${uploaded.id}:${uploaded.contentHash}`,
          token: `@${uploaded.displayName}`,
          name: uploaded.displayName,
          kind: "file",
          reference: {
            kind: "file",
            referenceId: uploaded.id,
            versionOrDigest: uploaded.contentHash,
            displaySnapshot: {
              name: uploaded.displayName,
              targetType: "project_file",
              logicalPath: uploaded.logicalPath,
              mimeType: uploaded.mimeType,
              version: uploaded.currentVersion,
              contentHash: uploaded.contentHash,
            },
          },
        });
      }
      setSteerReferences((current) => [
        ...current,
        ...uploadedReferences.filter((item) => !current.some((existing) => existing.key === item.key)),
      ]);
    } catch (uploadError) {
      setError(errorMessage(uploadError));
    } finally {
      setUploadingSteerSources(false);
    }
  }

  async function steerActiveMission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!mission || !steerInstruction.trim() || steeringMission) return;
    setSteeringMission(true);
    setError(null);
    try {
      const updated = await api.deepAnalysis.steerMission(mission.id, {
        expectedRevision: mission.revision,
        instruction: steerInstruction.trim(),
        promptReferences: steerReferences.map((item) => item.reference),
      });
      setMission(updated);
      setMissions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setSelectedReferences(selectedReferencesFromMission(updated));
      setSteerInstruction("");
      setSteerReferences([]);
    } catch (steerError) {
      setError(errorMessage(steerError));
    } finally {
      setSteeringMission(false);
    }
  }

  async function toggleResearchInspector() {
    if (!mission) return;
    if (researchInspectorOpen) {
      setResearchInspectorOpen(false);
      return;
    }
    setResearchInspectorOpen(true);
    setLoadingResearchInspector(true);
    try {
      setResearchInspector(await api.deepAnalysis.getResearchInspector(mission.id));
    } catch (inspectorError) {
      setError(errorMessage(inspectorError));
    } finally {
      setLoadingResearchInspector(false);
    }
  }

  async function inspectSourceChanges() {
    if (!mission || loadingRefreshPreview) return;
    setLoadingRefreshPreview(true);
    setRefreshArmed(false);
    setError(null);
    try {
      setRefreshPreview(await api.deepAnalysis.getRefreshPreview(mission.id));
    } catch (previewError) {
      setError(errorMessage(previewError));
    } finally {
      setLoadingRefreshPreview(false);
    }
  }

  async function refreshMissionSources() {
    if (!mission || !refreshPreview?.canRefresh || refreshingMission) return;
    if (!refreshArmed) {
      setRefreshArmed(true);
      return;
    }
    setRefreshingMission(true);
    setError(null);
    try {
      const refreshed = await api.deepAnalysis.refreshMission(mission.id, {
        expectedRevision: mission.revision,
      });
      setMission(refreshed);
      setMissions((current) => current.map((item) => item.id === refreshed.id ? refreshed : item));
      setSelectedReferences(selectedReferencesFromMission(refreshed));
      setRefreshPreview(null);
      setRefreshArmed(false);
      setMissionRootSelected(false);
      setSelectedNodeKey(refreshed.workflow.nodes.find((node) => node.status === "running")?.nodeKey ?? null);
    } catch (refreshError) {
      setError(errorMessage(refreshError));
      setRefreshArmed(false);
    } finally {
      setRefreshingMission(false);
    }
  }

  async function saveMissionSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextTitle = missionTitleDraft.trim();
    const nextObjective = missionObjectiveDraft.trim();
    const nextOutputFormat = normalizeOutputFormat(outputFormat);
    if (!mission || !missionSettingsEditable || !missionSettingsDirty || !nextTitle || !outputFormat.trim() || savingMissionSettings) return;
    setSavingMissionSettings(true);
    setError(null);
    try {
      const updated = await api.deepAnalysis.updateMission(mission.id, {
        expectedRevision: mission.revision,
        title: nextTitle,
        objective: nextObjective,
        analysisDepth,
        answerLength,
        outputMode,
        outputFormat: nextOutputFormat,
        targetOutputTokens: outputMode === "chat" ? null : targetOutputTokens,
        execution: createExecution ?? undefined,
        promptReferences: promptReferencesForObjective(selectedReferences, nextObjective),
        researchPeriod: {
          startDate: researchStartDate || null,
          endDate: researchEndDate || null,
        },
        webSourcePolicy: {
          mode: webSourceMode,
          domains: parseDomainList(webSourceDomains),
          excludedDomains: parseDomainList(excludedWebSourceDomains),
        },
      });
      setMission(updated);
      setMissions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setMissionTitleDraft(updated.title);
      setMissionObjectiveDraft(updated.objective);
      setAnalysisDepth(updated.analysisDepth);
      setAnswerLength(updated.answerLength);
      setOutputMode(updated.outputMode);
      setOutputFormat(updated.outputFormat);
      setTargetOutputTokens(updated.targetOutputTokens ?? 10_000);
      setCreateExecution(updated.execution);
      setSelectedReferences(selectedReferencesFromMission(updated));
      setResearchStartDate(updated.researchPeriod.startDate ?? "");
      setResearchEndDate(updated.researchPeriod.endDate ?? "");
      setWebSourceMode(updated.webSourcePolicy.mode);
      setWebSourceDomains(updated.webSourcePolicy.domains.join(", "));
      setExcludedWebSourceDomains(updated.webSourcePolicy.excludedDomains.join(", "));
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setSavingMissionSettings(false);
    }
  }

  async function deleteMission() {
    if (!mission || deletingMission) return;
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    setDeletingMission(true);
    setError(null);
    try {
      await api.deepAnalysis.deleteMission(mission.id, mission.revision);
      const remaining = missions.filter((item) => item.id !== mission.id);
      setMissions(remaining);
      setMission(null);
      setSelectedNodeKey(null);
      setSelectedMissionId(remaining[0]?.id ?? null);
      if (!remaining.length && projectId) {
        window.localStorage.removeItem(selectedMissionStorageKey(projectId));
      }
    } catch (deleteError) {
      setError(errorMessage(deleteError));
      setDeleteArmed(false);
    } finally {
      setDeletingMission(false);
    }
  }

  function addMissionReference(
    suggestion: Pick<ComposerSuggestion, "id" | "referenceId" | "kind" | "name" | "insertText" | "versionOrDigest" | "displaySnapshot">,
  ) {
    const referenceId = suggestion.referenceId ?? suggestion.id;
    const key = `${suggestion.kind}:${referenceId}:${suggestion.versionOrDigest ?? ""}`;
    if (selectedReferences.some((item) => item.key === key)) {
      setReferenceTrigger(null);
      return;
    }
    const token = suggestion.insertText ?? `${suggestion.kind === "skill" || suggestion.kind === "mcp" ? "$" : "@"}${suggestion.name}`;
    const appendToken = (current: string) => `${current.trimEnd()}${current.trim() ? " " : ""}${token} `;
    if (createOpen) setObjective(appendToken);
    else setMissionObjectiveDraft(appendToken);
    setSelectedReferences((current) => [
      ...current,
      {
        key,
        token,
        name: suggestion.name,
        kind: suggestion.kind,
        reference: {
          kind: suggestion.kind,
          referenceId,
          versionOrDigest: suggestion.versionOrDigest,
          displaySnapshot: suggestion.displaySnapshot,
        },
      },
    ]);
    setReferenceTrigger(null);
    setReferenceQuery("");
  }

  function removeMissionReference(key: string) {
    const selected = selectedReferences.find((item) => item.key === key);
    if (!selected) return;
    setSelectedReferences((current) => current.filter((item) => item.key !== key));
    const removeToken = (current: string) => current.replace(selected.token, "").replace(/ {2,}/g, " ");
    if (createOpen) setObjective(removeToken);
    else setMissionObjectiveDraft(removeToken);
  }

  async function uploadMissionSources(files: File[]) {
    if (!projectId || !files.length || uploadingSources) return;
    setUploadingSources(true);
    setError(null);
    try {
      for (const file of files) {
        const uploaded = await api.projectFiles.upload(
          projectId,
          file,
          file.name,
          "심층분석 초기 자료 첨부",
        );
        addMissionReference({
          id: uploaded.id,
          kind: "file",
          name: uploaded.displayName,
          insertText: `@${uploaded.displayName}`,
          versionOrDigest: uploaded.contentHash,
          displaySnapshot: {
            name: uploaded.displayName,
            targetType: "project_file",
            logicalPath: uploaded.logicalPath,
            mimeType: uploaded.mimeType,
            version: uploaded.currentVersion,
            contentHash: uploaded.contentHash,
          },
        });
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setUploadingSources(false);
    }
  }

  async function createMission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || !title.trim() || !outputFormat.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const created = await api.deepAnalysis.createMission(projectId, {
        title: title.trim(),
        objective: objective.trim(),
        autonomyMode: "balanced",
        analysisDepth,
        answerLength,
        outputMode,
        outputFormat: normalizeOutputFormat(outputFormat),
        targetOutputTokens: outputMode === "chat" ? null : targetOutputTokens,
        execution: createExecution ?? undefined,
        promptReferences: promptReferencesForObjective(selectedReferences, objective),
        researchPeriod: {
          startDate: researchStartDate || null,
          endDate: researchEndDate || null,
        },
        webSourcePolicy: {
          mode: webSourceMode,
          domains: parseDomainList(webSourceDomains),
          excludedDomains: parseDomainList(excludedWebSourceDomains),
        },
      });
      setMissions((current) => [created, ...current]);
      setSelectedMissionId(created.id);
      setMission(created);
      setSelectedNodeKey(created.workflow.nodes[0]?.nodeKey ?? null);
      setTitle("");
      setObjective("");
      setAnalysisDepth("auto");
      setAnswerLength("auto");
      setOutputMode("auto");
      setOutputFormat("markdown");
      setTargetOutputTokens(10_000);
      setCreateExecution(execution);
      setSelectedReferences([]);
      setResearchStartDate("");
      setResearchEndDate("");
      setWebSourceMode("all");
      setWebSourceDomains("");
      setExcludedWebSourceDomains("");
      setReferenceTrigger(null);
      setCreateOpen(false);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setCreating(false);
    }
  }

  function retry() {
    if (!projectId) return;
    setError(null);
    setLoadingList(true);
    void api.deepAnalysis
      .listMissions(projectId)
      .then((items) => {
        setMissions(items);
        setSelectedMissionId((current) =>
          items.some((item) => item.id === current) ? current : (items[0]?.id ?? null),
        );
      })
      .catch((loadError) => setError(errorMessage(loadError)))
      .finally(() => setLoadingList(false));
  }

  return (
    <main className="feature-view deep-analysis-view" aria-label="심층분석">
      <header className="feature-header deep-analysis-header">
        <div>
          <button
            className="deep-analysis-mobile-menu"
            type="button"
            aria-label="메뉴 열기"
            onClick={onOpenNavigation}
          >
            <Menu size={17} />
          </button>
          <Waypoints size={17} />
          <h1>심층분석</h1>
          <div className="feature-kind-tabs deep-analysis-view-tabs" role="tablist" aria-label="심층분석 화면">
            <button
              type="button"
              role="tab"
              aria-selected={createOpen || activeTab === "workflow"}
              disabled={!projectId}
              onClick={() => setActiveTab("workflow")}
            >
              <GitBranch size={16} /> Workflow
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!createOpen && activeTab === "log"}
              disabled={!projectId || createOpen || !mission}
              onClick={() => setActiveTab("log")}
            >
              <History size={16} /> 실행 기록
            </button>
          </div>
          <span>여러 단계의 분석을 Workflow 단위로 기록하고 이어갑니다.</span>
        </div>
        {activeTab === "log" && mission && !createOpen
          ? <MissionEventSummary missionId={mission.id} />
          : activeTabSummary && <span className="deep-analysis-header-summary" role="status">{activeTabSummary}</span>}
      </header>

      {error && (
        <div className="deep-analysis-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={retry}><RefreshCw size={14} /> 다시 시도</button>
        </div>
      )}

      {!projectId ? (
        <section className="deep-analysis-empty">
          <GitBranch size={24} />
          <h2>프로젝트를 먼저 선택해 주세요.</h2>
          <p>심층분석 Mission과 자료는 선택한 프로젝트에 귀속됩니다.</p>
        </section>
      ) : (
        <div className="deep-analysis-layout">
          <section
            className="deep-analysis-workspace"
            aria-busy={loadingMission}
            inert={loadingMission ? true : undefined}
          >
            {createOpen ? (
              <>
                <header className="deep-analysis-mission-header is-creating">
                  <div>
                    <h2>{title.trim() || "새 분석"}</h2>
                    <p>{objective.trim() || "Mission 정보를 입력해 새로운 심층분석을 시작합니다."}</p>
                  </div>
                </header>
                <div
                  ref={workflowLayoutRef}
                  className="deep-analysis-workflow-layout has-inspector is-creating"
                  style={{ "--deep-analysis-inspector-width": `${inspectorWidth}px` } as CSSProperties}
                >
                  <div
                    className="deep-analysis-canvas-shell"
                    onPointerDownCapture={() => window.getSelection()?.removeAllRanges()}
                    onPointerUpCapture={() => window.getSelection()?.removeAllRanges()}
                    onDragStart={(event) => event.preventDefault()}
                  >
                    <div className="deep-analysis-canvas-stage" aria-label="새 심층분석 Workflow 초안">
                      <button
                        className="deep-analysis-goal-node deep-analysis-create-mission-node is-selected"
                        type="button"
                        aria-label="MISSION 입력 정보 열기"
                        onClick={() => createTitleRef.current?.focus()}
                      >
                        <span><Target size={14} />Mission</span>
                        <strong>작업 흐름</strong>
                        <small>AI 자동 설계</small>
                      </button>
                    </div>
                  </div>
                  <div
                    className="deep-analysis-inspector-resizer"
                    role="separator"
                    aria-label="우측 입력 패널 폭 조절"
                    aria-orientation="vertical"
                    aria-valuemin={minimumInspectorWidth}
                    aria-valuemax={Math.round(maximumInspectorWidth())}
                    aria-valuenow={inspectorWidth}
                    tabIndex={0}
                    onPointerDown={beginInspectorResize}
                    onKeyDown={resizeInspectorWithKeyboard}
                  />
                  <aside className="deep-analysis-inspector deep-analysis-create-inspector" aria-label="새 분석 정보 입력">
                    <header>
                      <div><span>MISSION</span><button type="button" aria-label="새 분석 닫기" onClick={() => setCreateOpen(false)}><X size={14} /></button></div>
                      <strong>새 분석</strong>
                      <small>목표를 바탕으로 Node와 Edge를 한 번 자동 설계하며, 생성 후 직접 편집할 수 있습니다.</small>
                    </header>
                    <form className="deep-analysis-create" onSubmit={createMission}>
                      <label>
                        분석 이름
                        <input
                          ref={createTitleRef}
                          autoFocus
                          value={title}
                          maxLength={240}
                          placeholder="예: 전사 영업원가 변동 원인 분석"
                          onChange={(event) => setTitle(event.target.value)}
                        />
                      </label>
                      <label>
                        분석 목적
                        <textarea
                          value={objective}
                          rows={10}
                          maxLength={20_000}
                          placeholder="무엇을 설명하거나 결정해야 하는지 적어 주세요."
                          onChange={(event) => setObjective(event.target.value)}
                        />
                      </label>
                      <div className="deep-analysis-select-field">
                        <span>최종 산출물 형태</span>
                        <OutputFormatInput
                          value={outputFormat}
                          onChange={setOutputFormat}
                        />
                        <small>Markdown이 기본입니다. HTML을 고르거나 원하는 형태를 직접 입력할 수 있습니다.</small>
                      </div>
                      <ResearchSettingsFields
                        startDate={researchStartDate}
                        endDate={researchEndDate}
                        sourceMode={webSourceMode}
                        domains={webSourceDomains}
                        excludedDomains={excludedWebSourceDomains}
                        disabled={creating}
                        onStartDateChange={setResearchStartDate}
                        onEndDateChange={setResearchEndDate}
                        onSourceModeChange={setWebSourceMode}
                        onDomainsChange={setWebSourceDomains}
                        onExcludedDomainsChange={setExcludedWebSourceDomains}
                      />
                      {selectedReferences.length > 0 && (
                        <div className="deep-analysis-create-references" aria-label="선택한 분석 자료와 도구">
                          {selectedReferences.map((item) => (
                            <span key={item.key}>
                              {item.kind === "skill" || item.kind === "mcp"
                                ? <CircleDollarSign size={13} />
                                : <FileText size={13} />}
                              <strong>{item.name}</strong>
                              <button type="button" aria-label={`${item.name} 연결 해제`} onClick={() => removeMissionReference(item.key)}><X size={11} /></button>
                            </span>
                          ))}
                        </div>
                      )}
                      <div
                        ref={createToolbarRef}
                        className="composer-footer deep-analysis-create-toolbar"
                        aria-label="심층분석 초기 설정"
                        onPointerDownCapture={(event) => {
                          if ((event.target as Element).closest(".composer-picker-trigger, .artifact-length-trigger")) {
                            setReferenceTrigger(null);
                          }
                        }}
                      >
                        <input
                          ref={createFileInputRef}
                          className="visually-hidden"
                          type="file"
                          multiple
                          accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.tsv,.png,.jpg,.jpeg,.webp,.gif"
                          onChange={(event) => {
                            const files = Array.from(event.currentTarget.files ?? []);
                            event.currentTarget.value = "";
                            void uploadMissionSources(files);
                          }}
                        />
                        <div>
                          <button
                            className="composer-utility-button tooltip-control"
                            type="button"
                            aria-label="분석 자료 첨부"
                            data-tooltip="첨부"
                            disabled={uploadingSources}
                            onClick={() => createFileInputRef.current?.click()}
                          >
                            {uploadingSources ? <LoaderCircle className="is-running" size={17} /> : <Paperclip size={17} />}
                          </button>
                          <button
                            className={`composer-utility-button tooltip-control ${referenceTrigger === "@" ? "is-active" : ""}`}
                            type="button"
                            aria-label="기존 문서 연결"
                            data-tooltip="참고문서"
                            aria-pressed={referenceTrigger === "@"}
                            onClick={() => setReferenceTrigger((current) => current === "@" ? null : "@")}
                          ><AtSign size={17} /></button>
                          <button
                            className={`composer-utility-button tooltip-control ${referenceTrigger === "$" ? "is-active" : ""}`}
                            type="button"
                            aria-label="Skill 및 MCP 연결"
                            data-tooltip="Skill / MCP"
                            aria-pressed={referenceTrigger === "$"}
                            onClick={() => setReferenceTrigger((current) => current === "$" ? null : "$")}
                          ><CircleDollarSign size={17} /></button>
                          <ComposerPicker
                            options={analysisDepthOptions}
                            value={analysisDepth}
                            onChange={(value) => setAnalysisDepth(value as MissionAnalysisDepth)}
                            ariaLabel="분석 범위 설정"
                            menuLabel="분석 범위"
                            menuDescription="웹 검색과 자료 확인을 포함해 어디까지 분석할지 정합니다."
                            controlClassName={`analysis-depth-control is-${analysisDepth}`}
                            triggerIcon={<Search size={15} aria-hidden="true" />}
                            hideChevron
                          />
                          <ComposerPicker
                            options={answerLengthOptions}
                            value={answerLength}
                            onChange={(value) => setAnswerLength(value as MissionAnswerLength)}
                            ariaLabel="답변 분량 설정"
                            menuLabel="답변 분량"
                            menuDescription="각 Node가 작성할 결과의 기본 분량을 정합니다."
                            controlClassName={`answer-length-control is-${answerLength}`}
                            triggerIcon={<AlignLeft size={15} aria-hidden="true" />}
                            hideChevron
                          />
                          <ArtifactLengthSlider
                            value={targetOutputTokens}
                            onChange={(value) => setTargetOutputTokens(value ?? 10_000)}
                            outputMode={outputMode}
                            onOutputModeChange={setOutputMode}
                          />
                        </div>
                        <div>
                          <ComposerPicker
                            options={executionOptions}
                            value={selectedExecutionId}
                            onChange={(candidateId) => {
                              const candidate = executionOptions.find((option) => option.id === candidateId);
                              if (!candidate) return;
                              const effortId = candidate.effortOptions.find((option) => option.id === "auto")?.id
                                ?? candidate.effortOptions[0]?.id
                                ?? null;
                              setCreateExecution({
                                providerId: candidate.providerId,
                                modelKey: candidate.modelKey,
                                effortId,
                              });
                            }}
                            ariaLabel="모델 선택"
                            menuLabel="Model"
                            controlClassName="model-control"
                            placeholder="재설정 필요"
                          />
                          <ComposerPicker
                            options={createEffortOptions}
                            value={createExecution?.effortId ?? ""}
                            onChange={(effortId) => setCreateExecution((current) => current ? { ...current, effortId: effortId || null } : current)}
                            ariaLabel="추론 노력도 설정"
                            menuLabel="Effort"
                            controlClassName="effort-control"
                          />
                        </div>
                        {referenceTrigger && (
                          <div className="deep-analysis-create-reference-menu">
                            <header>
                              <strong>{referenceTrigger === "@" ? "기존 문서 연결" : "Skill / MCP 연결"}</strong>
                              <button type="button" aria-label="연결 메뉴 닫기" onClick={() => setReferenceTrigger(null)}><X size={13} /></button>
                            </header>
                            <input
                              autoFocus
                              value={referenceQuery}
                              placeholder={referenceTrigger === "@" ? "파일, 폴더, Artifact 검색" : "Skill 또는 MCP 검색"}
                              aria-label={referenceTrigger === "@" ? "기존 문서 검색" : "Skill 및 MCP 검색"}
                              onChange={(event) => setReferenceQuery(event.target.value)}
                            />
                            <div role="listbox">
                              {loadingReferences && <span className="deep-analysis-reference-state"><LoaderCircle className="is-running" size={13} /> 불러오는 중</span>}
                              {!loadingReferences && referenceSuggestions.length === 0 && <span className="deep-analysis-reference-state">사용 가능한 항목이 없습니다.</span>}
                              {!loadingReferences && referenceSuggestions.map((suggestion) => {
                                const referenceId = suggestion.referenceId ?? suggestion.id;
                                const selected = selectedReferences.some((item) => item.key === `${suggestion.kind}:${referenceId}:${suggestion.versionOrDigest ?? ""}`);
                                const disabled = selected || suggestion.status !== undefined && suggestion.status !== "available";
                                return (
                                  <button
                                    type="button"
                                    role="option"
                                    aria-selected={selected}
                                    disabled={disabled}
                                    key={`${suggestion.kind}:${suggestion.id}`}
                                    onClick={() => addMissionReference(suggestion)}
                                  >
                                    <span>{suggestion.kind === "skill" || suggestion.kind === "mcp" ? <CircleDollarSign size={14} /> : <FileText size={14} />}</span>
                                    <span><strong>{suggestion.displayName ?? suggestion.name}</strong><small>{suggestion.subtitle}</small></span>
                                    {selected && <Check size={13} />}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                      <button
                        className="deep-analysis-create-submit"
                        type="submit"
                        aria-busy={creating}
                        disabled={creating || !title.trim() || !outputFormat.trim() || !sourcePolicyValid}
                      >
                        {creating && <LoaderCircle className="is-running" size={14} />}
                        {creating ? `Workflow 설계 중... (${createElapsedSeconds}s)` : "Workflow 자동 만들기"}
                      </button>
                    </form>
                  </aside>
                </div>
              </>
            ) : loadingMission && !hasCachedMission && !mission ? (
              <div className="deep-analysis-empty"><LoaderCircle className="is-running" size={20} /><p>Workflow를 불러오는 중입니다.</p></div>
            ) : mission ? (
              <>
                <header className="deep-analysis-mission-header">
                  <div>
                    <h2>{mission.title}</h2>
                    <p>{mission.objective || "분석 목적이 아직 입력되지 않았습니다."}</p>
                  </div>
                  <div className="deep-analysis-mission-actions">
                    {canEdit && (mission.status === "draft" || mission.status === "ready") && (
                      <button
                        className={`deep-analysis-start ${!mission.executionAvailable ? "is-unavailable" : ""}`}
                        type="button"
                        disabled={startingMission || savingWorkflow || activatingWorkflow || !mission.executionAvailable || shownWorkflow?.nodes.length === 0}
                        data-tooltip={!mission.executionAvailable
                          ? "실제 분석 실행기가 연결된 후 시작할 수 있습니다."
                          : shownWorkflow?.nodes.length === 0
                            ? "실행할 Node를 하나 이상 추가해 주세요."
                            : undefined}
                        onClick={() => void startMission()}
                      >
                        {startingMission ? <LoaderCircle className="is-running" size={15} /> : <Play size={15} />}
                        {startingMission ? "시작 중" : mission.executionAvailable ? "시작" : "실행 엔진 준비 중"}
                      </button>
                    )}
                    {canEdit && (mission.status === "running" || mission.status === "paused") && (
                      <button
                        className="deep-analysis-contract-toggle"
                        type="button"
                        disabled={pausingMission}
                        onClick={() => void toggleMissionPause()}
                      >
                        {pausingMission
                          ? <LoaderCircle className="is-running" size={15} />
                          : mission.status === "paused" ? <Play size={15} /> : <Pause size={15} />}
                        {pausingMission ? "처리 중" : mission.status === "paused" ? "재개" : "일시정지"}
                      </button>
                    )}
                    {canEdit && (mission.status === "running" || mission.status === "paused" || mission.status === "awaiting_input") && (
                      <button
                        className="deep-analysis-cancel"
                        type="button"
                        disabled={cancellingMission}
                        onClick={() => void cancelMission()}
                      >
                        {cancellingMission ? <LoaderCircle className="is-running" size={15} /> : <Square size={14} />}
                        {cancellingMission ? "중단 중" : "중단"}
                      </button>
                    )}
                    <div className="deep-analysis-export-wrap">
                      <button
                        className={`deep-analysis-export tooltip-control ${exportedFolderPath ? "is-complete" : ""}`}
                        type="button"
                        aria-label={exportedFolderPath ? `파일 저장소에 저장됨: ${exportedFolderPath}` : "파일 저장소에 Mission 폴더 저장"}
                        data-tooltip={exportedFolderPath ? "파일 저장소에 저장됨" : "파일 저장소에 내보내기"}
                        disabled={exportingMission}
                        onClick={() => void exportMission()}
                      >
                        {exportingMission ? <LoaderCircle className="is-running" size={15} /> : exportedFolderPath ? <Check size={15} /> : <FolderDown size={15} />}
                      </button>
                    </div>
                    <div ref={costDetailsRef} className="deep-analysis-cost-wrap">
                      <button
                        className={`deep-analysis-cost tooltip-control ${costModeActive ? "is-active" : ""}`}
                        type="button"
                        aria-label={`누적 비용 ${formatCost(mission.spentMicrousd, usdKrwRate)}`}
                        aria-expanded={costDetailsOpen}
                        aria-pressed={costModeActive}
                        data-tooltip={`누적 비용 ${formatCost(mission.spentMicrousd, usdKrwRate)}`}
                        onClick={() => {
                          const nextActive = !costModeActive;
                          setCostModeActive(nextActive);
                          setCostDetailsOpen(nextActive);
                        }}
                      >
                        <CircleDollarSign size={16} />
                      </button>
                      {costDetailsOpen && (
                        <div className="deep-analysis-cost-popover">
                          <strong>비용 상세</strong>
                          <span className="is-budget"><em>누적 비용</em><b>{formatCost(mission.spentMicrousd, usdKrwRate)}</b></span>
                          {mission.budgetMicrousd !== null && <span><em>설정 예산</em><b>{formatCost(mission.budgetMicrousd, usdKrwRate)}</b></span>}
                          {costDetails && <>
                            <span><em>예상 완료 비용</em><b>{formatCost(costDetails.estimatedCompletionMicrousd, usdKrwRate)}</b></span>
                            <span><em>Cache 미적용 상한</em><b>{formatCost(costDetails.noCacheUpperBoundMicrousd, usdKrwRate)}</b></span>
                            <span><em>Cache hit ratio</em><b>{(costDetails.cacheHitRatio * 100).toFixed(1)}%</b></span>
                            <div className="deep-analysis-cost-token-summary">
                              <small>Uncached {costDetails.totals.uncachedInputTokens.toLocaleString()}</small>
                              <small>Cached {costDetails.totals.cachedInputTokens.toLocaleString()}</small>
                              <small>Cache write {costDetails.totals.cacheWriteTokens.toLocaleString()}</small>
                              <small>Output {costDetails.totals.outputTokens.toLocaleString()}</small>
                            </div>
                            <div className="deep-analysis-cost-runs">
                              {costDetails.rows.map((row) => <div key={`${row.runId}:${row.attempt}`}>
                                <span><em>{row.nodeKey} · {row.nodeTitle}{row.isRetry ? ` · 재실행 ${row.attempt}` : ""}</em><small>{row.modelDisplayName} · {row.date}</small><small>{row.pricingVersion ?? "가격표 미확인"}</small></span>
                                <b>{formatCost(row.actualCostMicrousd, usdKrwRate)}</b>
                              </div>)}
                            </div>
                          </>}
                          {loadingCosts && <span><em><LoaderCircle className="is-running" size={13} /> 불러오는 중</em></span>}
                        </div>
                      )}
                    </div>
                    {canEdit && (
                      <button
                        className={`deep-analysis-delete tooltip-control ${deleteArmed ? "is-armed" : ""}`}
                        type="button"
                        aria-label={deleteArmed ? "심층분석 삭제 확인, 한 번 더 누르면 삭제" : "심층분석 삭제"}
                        data-tooltip={mission.status === "running" || mission.status === "paused" || mission.status === "awaiting_input" ? "먼저 실행을 중단해 주세요." : deleteArmed ? "한 번 더 눌러 삭제" : "삭제"}
                        disabled={deletingMission || mission.status === "running" || mission.status === "paused" || mission.status === "awaiting_input"}
                        onClick={() => void deleteMission()}
                      >
                        {deletingMission ? <LoaderCircle className="is-running" size={14} /> : deleteArmed ? <AlertTriangle size={14} /> : <Trash2 size={14} />}
                      </button>
                    )}
                  </div>
                </header>
                {activeTab === "workflow" ? <>
                <div
                  ref={workflowLayoutRef}
                  className={`deep-analysis-workflow-layout ${selectedNode || missionRootSelected ? "has-inspector" : ""}`}
                  style={{ "--deep-analysis-inspector-width": `${inspectorWidth}px` } as CSSProperties}
                >
                  <div className="deep-analysis-workflow-main">
                {mission.status === "running" && (
                  <div className="deep-analysis-run-feedback is-active" role="status">
                    <LoaderCircle className="is-running" size={16} />
                    <div>
                      <strong>{activeNode ? `${activeNode.nodeKey} · ${activeNode.title} 실행 중` : "분석 작업 실행 중"}</strong>
                      <span>{completedNodeCount}/{mission.workflow.nodes.length} Node 완료</span>
                    </div>
                  </div>
                )}
                {mission.status === "paused" && (
                  <div className="deep-analysis-run-feedback is-cancelled" role="status">
                    <Pause size={15} />
                    <div><strong>일시정지됨</strong><span>실행 상태와 중간 출력은 보존되어 있습니다. 재개하면 같은 Run에서 계속 진행합니다.</span></div>
                  </div>
                )}
                {mission.status === "cancelled" && (
                  <div className="deep-analysis-run-feedback is-cancelled" role="status">
                    <Square size={14} />
                    <div><strong>중단됨</strong><span>현재 실행 중인 심층분석 작업이 없습니다.</span></div>
                  </div>
                )}
                {(mission.status === "draft" || mission.status === "ready") && !mission.executionAvailable && (
                  <div className="deep-analysis-run-feedback is-unavailable" role="status">
                    <CircleAlert size={16} />
                    <div><strong>실행 엔진 준비 중</strong><span>Workflow 설계와 검토는 가능하지만 실제 분석 실행은 아직 연결되지 않았습니다.</span></div>
                  </div>
                )}
                {canEdit && ["running", "paused", "awaiting_input"].includes(mission.status) && (
                  <details className="deep-analysis-steer-panel">
                    <summary>
                      <span>새 지침·자료 추가</span>
                      <small>다음에 시작되는 Node부터 적용 · {mission.guidanceCount}건 반영됨</small>
                    </summary>
                    <form onSubmit={steerActiveMission}>
                      <label>
                        추가 지침
                        <textarea
                          rows={3}
                          maxLength={10_000}
                          value={steerInstruction}
                          placeholder="예: 공급망 위험을 별도 절로 비교하고 공식 통계를 우선해 주세요."
                          onChange={(event) => setSteerInstruction(event.target.value)}
                        />
                      </label>
                      {steerReferences.length > 0 && (
                        <div className="deep-analysis-create-references" aria-label="실행 중 추가할 자료">
                          {steerReferences.map((item) => (
                            <span key={item.key}>
                              <FileText size={13} />
                              <strong>{item.name}</strong>
                              <button
                                type="button"
                                aria-label={`${item.name} 추가 취소`}
                                onClick={() => setSteerReferences((current) => current.filter((candidate) => candidate.key !== item.key))}
                              ><X size={11} /></button>
                            </span>
                          ))}
                        </div>
                      )}
                      <input
                        ref={steerFileInputRef}
                        className="visually-hidden"
                        type="file"
                        multiple
                        accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.tsv,.png,.jpg,.jpeg,.webp,.gif"
                        onChange={(event) => {
                          const files = Array.from(event.currentTarget.files ?? []);
                          event.currentTarget.value = "";
                          void uploadSteerSources(files);
                        }}
                      />
                      <div>
                        <button type="button" disabled={uploadingSteerSources} onClick={() => steerFileInputRef.current?.click()}>
                          {uploadingSteerSources ? <LoaderCircle className="is-running" size={14} /> : <Paperclip size={14} />}
                          새 자료 첨부
                        </button>
                        <button type="submit" disabled={!steerInstruction.trim() || steeringMission}>
                          {steeringMission ? <LoaderCircle className="is-running" size={14} /> : <Check size={14} />}
                          {steeringMission ? "반영 중" : "이후 Node에 반영"}
                        </button>
                      </div>
                    </form>
                  </details>
                )}
                  <div
                    className="deep-analysis-canvas-shell"
                    onPointerDownCapture={() => window.getSelection()?.removeAllRanges()}
                    onPointerUpCapture={() => window.getSelection()?.removeAllRanges()}
                    onDragStart={(event) => event.preventDefault()}
                  >
                  <div
                    className={`deep-analysis-canvas-scroll ${canvasPanning ? "is-panning" : ""}`}
                    ref={canvasViewportRef}
                    onPointerDown={beginCanvasPan}
                    onPointerMove={moveCanvasPan}
                    onPointerUp={endCanvasPan}
                    onPointerCancel={endCanvasPan}
                    onDoubleClick={(event) => {
                      if ((event.target as Element).closest("button")) return;
                      fitCanvasToViewport();
                    }}
                    onLostPointerCapture={() => {
                      canvasPanRef.current = null;
                      setCanvasPanning(false);
                    }}
                    onWheel={handleCanvasWheel}
                  >
                    <div
                      className="deep-analysis-canvas-stage"
                      style={{
                        backgroundPosition: `${canvasOffset.x}px ${canvasOffset.y}px`,
                      }}
                    >
                    <div
                      className="deep-analysis-canvas"
                      aria-label="Workflow 캔버스"
                      style={{
                        width: workflowCanvasSize.width,
                        height: workflowCanvasSize.height,
                        transform: `translate3d(${canvasOffset.x}px, ${canvasOffset.y}px, 0) scale(${canvasScale})`,
                      }}
                    >
                      <svg className="deep-analysis-edge-layer" aria-hidden="true">
                        {workflowMissionRoot?.connectedNodes.map((node) => {
                          const geometry = workflowEdgeGeometry(workflowMissionRoot.position, node);
                          return (
                            <path
                              key={`mission:${node.nodeKey}`}
                              className="deep-analysis-edge deep-analysis-mission-edge"
                              d={geometry.path}
                            />
                          );
                        })}
                        {(shownWorkflow?.edges ?? []).map((edge) => {
                          const source = shownWorkflowNodeByKey.get(edge.sourceNodeKey);
                          const target = shownWorkflowNodeByKey.get(edge.targetNodeKey);
                          if (!source || !target) return null;
                          const geometry = workflowEdgeGeometry(source, target);
                          return (
                            <g key={edge.id}>
                              <path
                                className={`deep-analysis-edge ${selectedEdgeId === edge.id ? "is-selected" : ""}`}
                                d={geometry.path}
                              />
                              {editingWorkflow && (
                                <path
                                  className="deep-analysis-edge-hit"
                                  d={geometry.path}
                                  onPointerDown={(event) => event.stopPropagation()}
                                  onClick={() => {
                                    setSelectedEdgeId(edge.id);
                                  }}
                                />
                              )}
                            </g>
                          );
                        })}
                        {connectionDraft && (() => {
                          const source = shownWorkflowNodeByKey.get(connectionDraft.sourceNodeKey);
                          if (!source) return null;
                          const sourcePoint = workflowPortPoint(source, connectionDraft.sourceSide);
                          const sourceVector = workflowPortVector(connectionDraft.sourceSide);
                          const targetVector = { x: -sourceVector.x, y: -sourceVector.y };
                          const controlOffset = Math.max(27, Math.hypot(
                            connectionDraft.pointerX - sourcePoint.x,
                            connectionDraft.pointerY - sourcePoint.y,
                          ) * .35);
                          return (
                            <path
                              className="deep-analysis-connection-preview"
                              d={`M ${sourcePoint.x} ${sourcePoint.y} C ${sourcePoint.x + sourceVector.x * controlOffset} ${sourcePoint.y + sourceVector.y * controlOffset}, ${connectionDraft.pointerX + targetVector.x * controlOffset} ${connectionDraft.pointerY + targetVector.y * controlOffset}, ${connectionDraft.pointerX} ${connectionDraft.pointerY}`}
                            />
                          );
                        })()}
                      </svg>
                      {(shownWorkflow?.nodes ?? []).map((node) => (
                        <WorkflowNodeButton
                          key={node.id}
                          node={node}
                          selected={selectedNodeKey === node.nodeKey}
                          showCost={costModeActive}
                          usdKrwRate={usdKrwRate}
                          onSelect={() => {
                            setSelectedNodeKey(node.nodeKey);
                            setSelectedEdgeId(null);
                            setMissionRootSelected(false);
                          }}
                          editable={editingWorkflow}
                          connectionPortsSuppressed={suppressedConnectionPortNodeKey === node.nodeKey}
                          onPointerLeave={() => setSuppressedConnectionPortNodeKey((current) => current === node.nodeKey ? null : current)}
                          connecting={connectionDraft !== null}
                          connectionSource={connectionDraft?.sourceNodeKey === node.nodeKey}
                          onPointerDown={(event) => beginNodeDrag(event, node)}
                          onPointerMove={moveNodeDrag}
                          onPointerUp={endNodeDrag}
                          onKeyDown={(event) => handleNodeKeyDown(event, node)}
                          onConnectionStart={(event, side) => beginConnectionDrag(event, node.nodeKey, side)}
                          onConnectionMove={moveConnectionDrag}
                          onConnectionEnd={endConnectionDrag}
                          onConnectionKeyStart={(side) => beginConnection(node.nodeKey, side)}
                          onConnectionComplete={() => completeConnection(node.nodeKey)}
                        />
                      ))}
                      {workflowMissionRoot && (
                        <button
                          className={`deep-analysis-goal-node deep-analysis-mission-root-node ${missionRootSelected ? "is-selected" : ""}`}
                          type="button"
                          aria-label="MISSION 작업 흐름"
                          aria-pressed={missionRootSelected}
                          style={{
                            left: workflowMissionRoot.position.positionX,
                            top: workflowMissionRoot.position.positionY,
                          }}
                          onClick={() => {
                            setMissionTitleDraft(mission.title);
                            setMissionObjectiveDraft(mission.objective);
                            setAnalysisDepth(mission.analysisDepth);
                            setAnswerLength(mission.answerLength);
                            setOutputMode(mission.outputMode);
                            setOutputFormat(mission.outputFormat);
                            setTargetOutputTokens(mission.targetOutputTokens ?? 10_000);
                            setCreateExecution(mission.execution);
                            setSelectedReferences(selectedReferencesFromMission(mission));
                            setResearchStartDate(mission.researchPeriod.startDate ?? "");
                            setResearchEndDate(mission.researchPeriod.endDate ?? "");
                            setWebSourceMode(mission.webSourcePolicy.mode);
                            setWebSourceDomains(mission.webSourcePolicy.domains.join(", "));
                            setExcludedWebSourceDomains(mission.webSourcePolicy.excludedDomains.join(", "));
                            setMissionRootSelected(true);
                            setSelectedNodeKey(null);
                            setSelectedEdgeId(null);
                            window.requestAnimationFrame(() => fitCanvasToViewport());
                          }}
                        >
                          <span><Target size={14} />MISSION</span>
                          <strong>작업 흐름</strong>
                          <small>{mission.startMode === "manual" ? "직접 구성" : "AI 자동 설계"}</small>
                        </button>
                      )}
                      {editingWorkflow && selectedEdgeId && (() => {
                        const edge = shownWorkflow?.edges.find((item) => item.id === selectedEdgeId);
                        const source = edge ? shownWorkflowNodeByKey.get(edge.sourceNodeKey) : undefined;
                        const target = edge ? shownWorkflowNodeByKey.get(edge.targetNodeKey) : undefined;
                        if (!edge || !source || !target) return null;
                        const geometry = workflowEdgeGeometry(source, target);
                        return (
                          <button
                            className="deep-analysis-edge-delete"
                            style={{
                              left: (geometry.sourcePoint.x + geometry.targetPoint.x) / 2,
                              top: (geometry.sourcePoint.y + geometry.targetPoint.y) / 2,
                            }}
                            type="button"
                            aria-label={`${source.nodeKey}에서 ${target.nodeKey} 연결 지우기`}
                            onClick={() => removeDraftEdge(edge.id)}
                          >
                            <Trash2 size={12} />
                          </button>
                        );
                      })()}
                      <svg className="deep-analysis-port-layer" aria-hidden="true">
                        {(shownWorkflow?.edges ?? []).map((edge) => {
                          const source = shownWorkflowNodeByKey.get(edge.sourceNodeKey);
                          const target = shownWorkflowNodeByKey.get(edge.targetNodeKey);
                          if (!source || !target) return null;
                          const geometry = workflowEdgeGeometry(source, target);
                          return (
                            <g key={edge.id}>
                              <circle className="deep-analysis-edge-port" cx={geometry.sourcePoint.x} cy={geometry.sourcePoint.y} r="4" />
                              <circle className="deep-analysis-edge-port" cx={geometry.targetPoint.x} cy={geometry.targetPoint.y} r="4" />
                            </g>
                          );
                        })}
                      </svg>
                    </div>
                    </div>
                    </div>
                    <div ref={canvasControlsRef} className="deep-analysis-canvas-controls" aria-label="Workflow 조작">
                      <div className="deep-analysis-workflow-regenerate-control">
                      <button
                        ref={workflowRegenerateTriggerRef}
                        className={workflowRegenerateOpen ? "deep-analysis-workflow-regenerate-trigger is-active" : "deep-analysis-workflow-regenerate-trigger"}
                        type="button"
                        aria-label="workflow 재생성"
                        aria-expanded={workflowRegenerateOpen}
                        data-tooltip="workflow 재생성"
                        disabled={!canEdit
                          || (editingWorkflow && (workflowDraft?.nodes.length ?? 0) > 0)
                          || regeneratingWorkflow
                          || ["running", "paused", "awaiting_input"].includes(mission.status)}
                        onClick={() => setWorkflowRegenerateOpen((open) => !open)}
                      >
                        {regeneratingWorkflow ? <LoaderCircle className="is-running" size={14} /> : <RefreshCw size={14} />}
                      </button>
                      {workflowRegenerateOpen && createPortal((
                        <form
                          className="deep-analysis-workflow-regenerate-popover"
                          aria-label="workflow 재생성 프롬프트"
                          style={{
                            ...workflowRegeneratePosition,
                            ...(workflowRegenerateFontSize ? { "--conversation-font-size": workflowRegenerateFontSize } : {}),
                          } as CSSProperties}
                          onSubmit={regenerateWorkflow}
                          onPointerDown={(event) => event.stopPropagation()}
                        >
                          <div className="deep-analysis-workflow-regenerate-heading">
                            <strong>Workflow 재생성</strong>
                            <button type="button" aria-label="닫기" onClick={() => setWorkflowRegenerateOpen(false)}><X size={14} /></button>
                          </div>
                          <label htmlFor="deep-analysis-workflow-regenerate-prompt">Workflow를 어떻게 다시 그릴지 입력해 주세요.</label>
                          <textarea
                            id="deep-analysis-workflow-regenerate-prompt"
                            autoFocus
                            rows={4}
                            value={workflowRegeneratePrompt}
                            placeholder="예: 자료 수집과 수치 분석을 병렬로 진행하고, 마지막에 결과를 합쳐 주세요."
                            onChange={(event) => setWorkflowRegeneratePrompt(event.target.value)}
                          />
                          <div className="deep-analysis-workflow-regenerate-actions">
                            <button type="button" onClick={() => setWorkflowRegenerateOpen(false)}>취소</button>
                            <button type="submit" disabled={!workflowRegeneratePrompt.trim() || regeneratingWorkflow}>
                              {regeneratingWorkflow ? <><LoaderCircle className="is-running" size={13} /> 재생성 중</> : "재생성"}
                            </button>
                          </div>
                        </form>
                      ), document.body)}
                      </div>
                      <div className="deep-analysis-canvas-edit-controls" aria-label="Node 편집">
                        <button
                          className={editingWorkflow ? "is-active" : undefined}
                          type="button"
                          aria-label={editingWorkflow ? "편집 종료" : "노드 편집"}
                          data-tooltip={editingWorkflow ? "편집 종료" : "노드 편집"}
                          disabled={!canEdit
                            || (mission.status !== "draft" && mission.status !== "ready")
                            || savingWorkflow
                            || activatingWorkflow
                            || (editingWorkflow && workflowDraft?.nodes.length === 0)}
                          onClick={() => void (editingWorkflow ? activateWorkflowDraft() : beginWorkflowEdit())}
                        >
                          {savingWorkflow || activatingWorkflow ? <LoaderCircle className="is-running" size={14} /> : <Pencil size={14} />}
                        </button>
                        <button type="button" aria-label="Node 추가" data-tooltip="Node 추가" disabled={!editingWorkflow || !workflowDraft} onClick={addDraftNode}><Plus size={14} /></button>
                        <button type="button" aria-label="Node 자동 정렬" data-tooltip="Node 자동 정렬" disabled={arrangingWorkflow || !canEdit || (mission.status !== "draft" && mission.status !== "ready")} onClick={() => void autoArrangeWorkflow()}>{arrangingWorkflow ? <LoaderCircle className="is-running" size={14} /> : <WandSparkles size={14} />}</button>
                        <button type="button" aria-label="되돌리기" data-tooltip="되돌리기 (Ctrl+Z)" disabled={!editingWorkflow || workflowUndoStackRef.current.length === 0} onClick={() => undoWorkflowChange()}><Undo2 size={14} /></button>
                        <button type="button" aria-label="Node 지우기" data-tooltip="Node 지우기" disabled={!editingWorkflow || !selectedNode || workflowDraft?.nodes.length === 1} onClick={() => selectedNode && removeDraftNode(selectedNode.nodeKey)}><Trash2 size={14} /></button>
                      </div>
                      <div className="deep-analysis-canvas-zoom-controls" aria-label="확대 및 축소">
                        <button type="button" aria-label="확대" data-tooltip="확대" disabled={canvasScale >= maximumCanvasScale} onClick={() => updateCanvasScale(canvasScale + 0.1)}><ZoomIn size={14} /></button>
                        <button className="deep-analysis-canvas-zoom-value" type="button" aria-label="배율 초기화" onClick={() => updateCanvasScale(1)}>{Math.round(canvasScale * 100)}%</button>
                        <button type="button" aria-label="축소" data-tooltip="축소" disabled={canvasScale <= minimumCanvasScale} onClick={() => updateCanvasScale(canvasScale - 0.1)}><ZoomOut size={14} /></button>
                      </div>
                    </div>
                  </div>
                  </div>
                  {(selectedNode || missionRootSelected) && (
                    <div
                      className="deep-analysis-inspector-resizer"
                      role="separator"
                      aria-label="우측 상세 패널 폭 조절"
                      aria-orientation="vertical"
                      aria-valuemin={minimumInspectorWidth}
                      aria-valuemax={Math.round(maximumInspectorWidth())}
                      aria-valuenow={inspectorWidth}
                      tabIndex={0}
                      onPointerDown={beginInspectorResize}
                      onKeyDown={resizeInspectorWithKeyboard}
                    />
                  )}
                  {missionRootSelected && (
                    <aside className="deep-analysis-inspector deep-analysis-create-inspector" aria-label="Mission 정보">
                      <header>
                        <div>
                          <span>MISSION</span>
                        </div>
                        <strong>분석 정보</strong>
                        <small>{mission.startMode === "manual"
                          ? "Node를 추가하고 연결한 뒤 각 단계의 프롬프트를 설정해 실행합니다."
                          : "목표를 바탕으로 설계된 Node와 Edge를 직접 편집할 수 있습니다."}</small>
                        {shownWorkflow?.reason && (
                          <small className="deep-analysis-node-origin">
                            <GitBranch size={12} /> {shownWorkflow.reason}
                          </small>
                        )}
                      </header>
                      <form className="deep-analysis-create" onSubmit={saveMissionSettings}>
                        <label>
                          분석 이름
                          <input
                            value={missionTitleDraft}
                            maxLength={240}
                            disabled={!missionSettingsEditable || savingMissionSettings}
                            onChange={(event) => setMissionTitleDraft(event.target.value)}
                          />
                        </label>
                        <label>
                          분석 목적
                          <textarea
                            value={missionObjectiveDraft}
                            rows={10}
                            maxLength={20_000}
                            disabled={!missionSettingsEditable || savingMissionSettings}
                            onChange={(event) => setMissionObjectiveDraft(event.target.value)}
                          />
                        </label>
                        <div className="deep-analysis-select-field">
                          <span>최종 산출물 형태</span>
                          <OutputFormatInput
                            value={outputFormat}
                            disabled={!missionSettingsEditable || savingMissionSettings}
                            onChange={setOutputFormat}
                          />
                          <small>Markdown이 기본입니다. HTML을 고르거나 원하는 형태를 직접 입력할 수 있습니다.</small>
                        </div>
                        <ResearchSettingsFields
                          startDate={researchStartDate}
                          endDate={researchEndDate}
                          sourceMode={webSourceMode}
                          domains={webSourceDomains}
                          excludedDomains={excludedWebSourceDomains}
                          disabled={!missionSettingsEditable || savingMissionSettings}
                          onStartDateChange={setResearchStartDate}
                          onEndDateChange={setResearchEndDate}
                          onSourceModeChange={setWebSourceMode}
                          onDomainsChange={setWebSourceDomains}
                          onExcludedDomainsChange={setExcludedWebSourceDomains}
                        />
                        {selectedReferences.length > 0 && (
                          <div className="deep-analysis-create-references" aria-label="선택한 분석 자료와 도구">
                            {selectedReferences.map((item) => (
                              <span key={item.key}>
                                {item.kind === "skill" || item.kind === "mcp"
                                  ? <CircleDollarSign size={13} />
                                  : <FileText size={13} />}
                                <strong>{item.name}</strong>
                                <button
                                  type="button"
                                  aria-label={`${item.name} 연결 해제`}
                                  disabled={!missionSettingsEditable || savingMissionSettings}
                                  onClick={() => removeMissionReference(item.key)}
                                ><X size={11} /></button>
                              </span>
                            ))}
                          </div>
                        )}
                        <div
                          ref={createToolbarRef}
                          className="composer-footer deep-analysis-create-toolbar"
                          aria-label="Mission 실행 설정"
                          onPointerDownCapture={(event) => {
                            if ((event.target as Element).closest(".composer-picker-trigger, .artifact-length-trigger")) {
                              setReferenceTrigger(null);
                            }
                          }}
                        >
                          <input
                            ref={createFileInputRef}
                            className="visually-hidden"
                            type="file"
                            multiple
                            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.csv,.tsv,.png,.jpg,.jpeg,.webp,.gif"
                            onChange={(event) => {
                              const files = Array.from(event.currentTarget.files ?? []);
                              event.currentTarget.value = "";
                              void uploadMissionSources(files);
                            }}
                          />
                          <div>
                            <button
                              className="composer-utility-button tooltip-control"
                              type="button"
                              aria-label="분석 자료 첨부"
                              data-tooltip="첨부"
                              disabled={!missionSettingsEditable || savingMissionSettings || uploadingSources}
                              onClick={() => createFileInputRef.current?.click()}
                            >
                              {uploadingSources ? <LoaderCircle className="is-running" size={17} /> : <Paperclip size={17} />}
                            </button>
                            <button
                              className={`composer-utility-button tooltip-control ${referenceTrigger === "@" ? "is-active" : ""}`}
                              type="button"
                              aria-label="기존 문서 연결"
                              data-tooltip="참고문서"
                              aria-pressed={referenceTrigger === "@"}
                              disabled={!missionSettingsEditable || savingMissionSettings}
                              onClick={() => setReferenceTrigger((current) => current === "@" ? null : "@")}
                            ><AtSign size={17} /></button>
                            <button
                              className={`composer-utility-button tooltip-control ${referenceTrigger === "$" ? "is-active" : ""}`}
                              type="button"
                              aria-label="Skill 및 MCP 연결"
                              data-tooltip="Skill / MCP"
                              aria-pressed={referenceTrigger === "$"}
                              disabled={!missionSettingsEditable || savingMissionSettings}
                              onClick={() => setReferenceTrigger((current) => current === "$" ? null : "$")}
                            ><CircleDollarSign size={17} /></button>
                            <ComposerPicker
                              options={analysisDepthOptions}
                              value={analysisDepth}
                              onChange={(value) => setAnalysisDepth(value as MissionAnalysisDepth)}
                              ariaLabel="분석 범위 설정"
                              menuLabel="분석 범위"
                              menuDescription="웹 검색과 자료 확인을 포함해 어디까지 분석할지 정합니다."
                              controlClassName={`analysis-depth-control is-${analysisDepth}`}
                              triggerIcon={<Search size={15} aria-hidden="true" />}
                              hideChevron
                              disabled={!missionSettingsEditable || savingMissionSettings}
                            />
                            <ComposerPicker
                              options={answerLengthOptions}
                              value={answerLength}
                              onChange={(value) => setAnswerLength(value as MissionAnswerLength)}
                              ariaLabel="답변 분량 설정"
                              menuLabel="답변 분량"
                              menuDescription="각 Node가 작성할 결과의 기본 분량을 정합니다."
                              controlClassName={`answer-length-control is-${answerLength}`}
                              triggerIcon={<AlignLeft size={15} aria-hidden="true" />}
                              hideChevron
                              disabled={!missionSettingsEditable || savingMissionSettings}
                            />
                            <ArtifactLengthSlider
                              value={targetOutputTokens}
                              onChange={(value) => {
                                if (missionSettingsEditable && !savingMissionSettings) setTargetOutputTokens(value ?? 10_000);
                              }}
                              outputMode={outputMode}
                              onOutputModeChange={(value) => {
                                if (missionSettingsEditable && !savingMissionSettings) setOutputMode(value);
                              }}
                            />
                          </div>
                          <div>
                            <ComposerPicker
                              options={executionOptions}
                              value={selectedExecutionId}
                              onChange={(candidateId) => {
                                const candidate = executionOptions.find((option) => option.id === candidateId);
                                if (!candidate) return;
                                const effortId = candidate.effortOptions.find((option) => option.id === "auto")?.id
                                  ?? candidate.effortOptions[0]?.id
                                  ?? null;
                                setCreateExecution({
                                  providerId: candidate.providerId,
                                  modelKey: candidate.modelKey,
                                  effortId,
                                });
                              }}
                              ariaLabel="모델 선택"
                              menuLabel="Model"
                              controlClassName="model-control"
                              placeholder="재설정 필요"
                              disabled={!missionSettingsEditable || savingMissionSettings}
                            />
                            <ComposerPicker
                              options={createEffortOptions}
                              value={createExecution?.effortId ?? ""}
                              onChange={(effortId) => setCreateExecution((current) => current ? { ...current, effortId: effortId || null } : current)}
                              ariaLabel="추론 노력도 설정"
                              menuLabel="Effort"
                              controlClassName="effort-control"
                              disabled={!missionSettingsEditable || savingMissionSettings}
                            />
                          </div>
                          {referenceTrigger && missionSettingsEditable && (
                            <div className="deep-analysis-create-reference-menu">
                              <header>
                                <strong>{referenceTrigger === "@" ? "기존 문서 연결" : "Skill / MCP 연결"}</strong>
                                <button type="button" aria-label="연결 메뉴 닫기" onClick={() => setReferenceTrigger(null)}><X size={13} /></button>
                              </header>
                              <input
                                autoFocus
                                value={referenceQuery}
                                placeholder={referenceTrigger === "@" ? "파일, 폴더, Artifact 검색" : "Skill 또는 MCP 검색"}
                                aria-label={referenceTrigger === "@" ? "기존 문서 검색" : "Skill 및 MCP 검색"}
                                onChange={(event) => setReferenceQuery(event.target.value)}
                              />
                              <div role="listbox">
                                {loadingReferences && <span className="deep-analysis-reference-state"><LoaderCircle className="is-running" size={13} /> 불러오는 중</span>}
                                {!loadingReferences && referenceSuggestions.length === 0 && <span className="deep-analysis-reference-state">사용 가능한 항목이 없습니다.</span>}
                                {!loadingReferences && referenceSuggestions.map((suggestion) => {
                                  const referenceId = suggestion.referenceId ?? suggestion.id;
                                  const selected = selectedReferences.some((item) => item.key === `${suggestion.kind}:${referenceId}:${suggestion.versionOrDigest ?? ""}`);
                                  const disabled = selected || suggestion.status !== undefined && suggestion.status !== "available";
                                  return (
                                    <button
                                      type="button"
                                      role="option"
                                      aria-selected={selected}
                                      disabled={disabled}
                                      key={`${suggestion.kind}:${suggestion.id}`}
                                      onClick={() => addMissionReference(suggestion)}
                                    >
                                      <span>{suggestion.kind === "skill" || suggestion.kind === "mcp" ? <CircleDollarSign size={14} /> : <FileText size={14} />}</span>
                                      <span><strong>{suggestion.displayName ?? suggestion.name}</strong><small>{suggestion.subtitle}</small></span>
                                      {selected && <Check size={13} />}
                                    </button>
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                        <button
                          className="deep-analysis-create-submit"
                          type="submit"
                          aria-busy={savingMissionSettings}
                          disabled={!missionSettingsEditable || !missionSettingsDirty || !missionTitleDraft.trim() || !outputFormat.trim() || !sourcePolicyValid || savingMissionSettings}
                        >
                          {savingMissionSettings && <LoaderCircle className="is-running" size={14} />}
                          {savingMissionSettings ? "저장 중..." : "Mission 정보 저장"}
                        </button>
                      </form>
                      <section className="deep-analysis-research-inspector">
                        <button type="button" aria-expanded={researchInspectorOpen} onClick={() => void toggleResearchInspector()}>
                          {loadingResearchInspector ? <LoaderCircle className="is-running" size={14} /> : <Search size={14} />}
                          <span>출처·인용 검사</span>
                          <ChevronDown size={14} />
                        </button>
                        {researchInspectorOpen && (
                          <div>
                            {loadingResearchInspector && <p>출처와 인용을 확인하고 있습니다.</p>}
                            {!loadingResearchInspector && researchInspector && <>
                              <div className="deep-analysis-research-metrics">
                                <span><strong>{researchInspector.summary.citedSourceCount}</strong> 인용됨</span>
                                <span><strong>{researchInspector.summary.referenceOnlyCount}</strong> 참고만 함</span>
                                <span className={researchInspector.summary.citationReviewNeededCount ? "is-warning" : undefined}>
                                  <strong>{researchInspector.summary.citationReviewNeededCount}</strong> 확인 필요
                                </span>
                              </div>
                              <ul className="deep-analysis-source-list">
                                {researchInspector.sources.map((source) => (
                                  <li key={source.sourceId}>
                                    <span className={`is-${source.citationStatus ?? "reference_only"}`}>
                                      {source.citationStatus === "cited" ? "인용" : "참고"}
                                    </span>
                                    <div>
                                      {source.normalizedUrl
                                        ? <a href={source.normalizedUrl} target="_blank" rel="noreferrer">{source.title || source.normalizedUrl}</a>
                                        : <strong>{source.title || source.logicalPath || source.sourceId}</strong>}
                                      <small>{source.sourceKind === "web" ? "웹" : "Project 자료"} · {source.policyStatus}</small>
                                    </div>
                                  </li>
                                ))}
                              </ul>
                              {researchInspector.citationReviewCandidates.length > 0 && (
                                <details className="deep-analysis-citation-review">
                                  <summary>인용 확인 필요 문장 {researchInspector.citationReviewCandidates.length}개</summary>
                                  <ul>
                                    {researchInspector.citationReviewCandidates.map((candidate) => (
                                      <li key={`${candidate.nodeKey}:${candidate.lineNumber}`}>
                                        <small>{candidate.nodeKey} · {candidate.lineNumber}행</small>
                                        <span>{candidate.text}</span>
                                      </li>
                                    ))}
                                  </ul>
                                </details>
                              )}
                            </>}
                          </div>
                        )}
                      </section>
                      {canEdit && ["completed", "failed", "cancelled", "blocked"].includes(mission.status) && (
                        <section className="deep-analysis-mission-maintenance">
                          <div className="deep-analysis-mission-maintenance-actions">
                            <button type="button" disabled={loadingRefreshPreview || refreshingMission} onClick={() => void inspectSourceChanges()}>
                              {loadingRefreshPreview ? <LoaderCircle className="is-running" size={14} /> : <RefreshCw size={14} />}
                              자료 변경 확인
                            </button>
                            <button
                              className={`deep-analysis-mission-restart ${restartArmed ? "is-confirming" : ""}`}
                              type="button"
                              aria-label={restartArmed ? "MISSION 처음부터 재시작 확인, 한 번 더 누르면 실행" : "MISSION 처음부터 재시작"}
                              disabled={restartingMission || !mission.executionAvailable}
                              onClick={() => void restartMission()}
                            >
                              {restartingMission
                                ? <LoaderCircle className="is-running" size={14} />
                                : restartArmed ? <AlertTriangle size={14} /> : <RefreshCw size={14} />}
                              {restartingMission ? "재시작 중..." : restartArmed ? "한 번 더 눌러 처음부터 재시작" : "MISSION부터 처음부터 재시작"}
                            </button>
                          </div>
                          {refreshPreview && <div className="deep-analysis-refresh-results">
                            <p>
                              {refreshPreview.hasChanges
                                ? `${refreshPreview.changedSources.length}개 자료 변경 · ${refreshPreview.affectedNodeKeys.length}개 Node 영향`
                                : "MISSION 생성 이후 변경된 자료가 없습니다."}
                            </p>
                            {refreshPreview.changedSources.length > 0 && (
                              <ul>
                                {refreshPreview.changedSources.map((source) => (
                                  <li key={source.projectFileId}>
                                    <strong>{source.logicalPath}</strong>
                                    <span>{source.status === "missing" ? "자료 없음" : `v${source.fromVersion} → v${source.toVersion}`}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                            {refreshPreview.reportDiff.available && (
                              <details className="deep-analysis-report-diff">
                                <summary>직전 보고서 차이 +{refreshPreview.reportDiff.addedLines} / -{refreshPreview.reportDiff.removedLines}</summary>
                                <pre>{refreshPreview.reportDiff.lines.join("\n")}</pre>
                              </details>
                            )}
                            {refreshPreview.canRefresh && (
                              <button
                                type="button"
                                className={refreshArmed ? "deep-analysis-refresh-run is-confirming" : "deep-analysis-refresh-run lumina-primary-action"}
                                disabled={refreshingMission || !mission.executionAvailable}
                                onClick={() => void refreshMissionSources()}
                              >
                                {refreshingMission
                                  ? <LoaderCircle className="is-running" size={14} />
                                  : refreshArmed ? <AlertTriangle size={14} /> : <RefreshCw size={14} />}
                                {refreshingMission ? "갱신 중" : refreshArmed ? "한 번 더 눌러 갱신 실행" : "변경 자료로 다시 분석"}
                              </button>
                            )}
                          </div>}
                        </section>
                      )}
                    </aside>
                  )}
                  {selectedNode && (
                    <aside className="deep-analysis-inspector" aria-label={`${selectedNode.title} 상세 정보`}>
                      <header>
                        <div>
                          <span>{selectedNode.nodeKey}</span>
                          <small className={`node-status status-${selectedNode.status}`}>{statusLabel(selectedNode.status)}</small>
                        </div>
                        <strong>{selectedNode.title}</strong>
                      </header>
                      <section>
                        <h3>작업 프롬프트</h3>
                        {editingWorkflow && workflowDraft ? <>
                          <label className="deep-analysis-node-edit-field">Node 유형<SelectMenu
                            value={selectedNode.nodeType}
                            options={workflowNodeTypeOptions}
                            ariaLabel={`${selectedNode.nodeKey} Node 유형`}
                            onChange={(nodeType) => {
                              setWorkflowDraft({
                                ...workflowDraft,
                                nodes: workflowDraft.nodes.map((node) => node.nodeKey === selectedNode.nodeKey
                                  ? { ...node, nodeType }
                                  : node),
                              });
                              setWorkflowDraftDirty(true);
                            }}
                          /></label>
                          <label className="deep-analysis-node-edit-field">이름<input value={selectedNode.title} onChange={(event) => {
                            setWorkflowDraft({ ...workflowDraft, nodes: workflowDraft.nodes.map((node) => node.nodeKey === selectedNode.nodeKey ? { ...node, title: event.target.value } : node) });
                            setWorkflowDraftDirty(true);
                          }} /></label>
                          <label className="deep-analysis-node-edit-field">프롬프트<textarea rows={6} value={selectedNode.purpose} onChange={(event) => {
                            setWorkflowDraft({ ...workflowDraft, nodes: workflowDraft.nodes.map((node) => node.nodeKey === selectedNode.nodeKey ? { ...node, purpose: event.target.value } : node) });
                            setWorkflowDraftDirty(true);
                          }} /></label>
                        </> : <p>{selectedNode.purpose}</p>}
                      </section>
                      <section>
                        <h3>실행 프롬프트</h3>
                        {selectedNode.executionPrompt ? (
                          <details className="deep-analysis-node-prompt">
                            <summary>실제 입력 프롬프트 보기</summary>
                            <pre>{selectedNode.executionPrompt}</pre>
                          </details>
                        ) : (
                          <p>Node 실행 시 실제 입력 프롬프트가 이곳에 표시됩니다.</p>
                        )}
                      </section>
                      <section className={`deep-analysis-output-section ${selectedNode.status === "running" ? "is-streaming" : ""}`}>
                        <div className="deep-analysis-output-heading">
                          <h3>출력</h3>
                          {selectedNode.outputMarkdown && (
                            <nav className="deep-analysis-output-actions" aria-label="산출물 작업">
                              <ArtifactPreviewActions
                                sourceActive={selectedNodeShowsSource}
                                shareDisabled={!selectedNode.conversationId}
                                downloadDisabled={!projectId || !selectedNode.outputProjectFileId}
                                openWindowHref={
                                  projectId
                                  && selectedNode.outputProjectFileId
                                  && (
                                    selectedNode.outputLogicalPath?.toLowerCase().endsWith(".html")
                                    || isCompleteHtmlDocument(selectedNode.outputMarkdown)
                                  )
                                    ? projectFilePreviewUrl(projectId, selectedNode.outputProjectFileId)
                                    : null
                                }
                                onToggleSource={() => setOutputSourceNodeId(
                                  selectedNodeShowsSource ? null : selectedNode.id,
                                )}
                                onShare={() => void shareSelectedNodeOutput()}
                                onDownload={() => void downloadSelectedNodeOutput()}
                              />
                            </nav>
                          )}
                        </div>
                        {outputActionStatus && (
                          <p className="deep-analysis-output-action-status" role="status">
                            {outputActionStatus}
                          </p>
                        )}
                        {selectedNode.outputLogicalPath && selectedNode.outputProjectFileId && (
                          <button
                            className="deep-analysis-output-path"
                            type="button"
                            onClick={() => onOpenProjectFile(selectedNode.outputProjectFileId!)}
                          >
                            <FileText size={13} />
                            <span>{selectedNode.outputLogicalPath}</span>
                            <strong>파일 저장소에서 열기</strong>
                          </button>
                        )}
                        {selectedNode.status === "running" ? (
                          <>
                            <p className="deep-analysis-node-progress"><LoaderCircle className="is-running" size={13} /> 모델 응답을 생성하고 있습니다.</p>
                            {selectedNode.liveOutput && (
                              <pre ref={liveOutputRef} className="deep-analysis-live-output">{displayLiveOutput(selectedNode.liveOutput)}</pre>
                            )}
                          </>
                        ) : selectedNode.errorMessage ? (
                          <p className="deep-analysis-node-error">{selectedNode.errorMessage}</p>
                        ) : selectedNode.outputMarkdown ? (
                          selectedNodeShowsSource ? (
                            <pre className="deep-analysis-output-source">{selectedNode.outputMarkdown}</pre>
                          ) : selectedNode.outputLogicalPath?.toLowerCase().endsWith(".html")
                          || isCompleteHtmlDocument(selectedNode.outputMarkdown) ? (
                            <div className="deep-analysis-output-html">
                              <ArtifactHtmlPreview
                                frameRef={htmlOutputPreviewRef}
                                source={selectedNode.outputMarkdown}
                                previewUrl={null}
                                title={`${selectedNode.title} HTML 미리보기`}
                                autoHeight
                              />
                            </div>
                          ) : (
                            <article className="deep-analysis-output-document conversation-response-typography">
                              <MarkdownResponse text={selectedNode.outputMarkdown} />
                            </article>
                          )
                        ) : (
                          <p>{selectedNode.outputSummary || "아직 생성된 출력이 없습니다."}</p>
                        )}
                        {selectedNode.generatedFiles.length > 0 && (
                          <div className="deep-analysis-generated-files">
                            <strong>계산 산출물</strong>
                            {selectedNode.generatedFiles.map((file) => (
                              <span key={`${file.projectFileId}:${file.version}`}>
                                <em>{file.kind.toUpperCase()}</em>{file.path}
                              </span>
                            ))}
                          </div>
                        )}
                        {canEdit && (selectedNode.status === "failed" || selectedNode.status === "cancelled") && (
                          <button
                            className="deep-analysis-retry-node"
                            type="button"
                            disabled={retryingNodeKey !== null}
                            onClick={() => void retryNode(selectedNode)}
                          >
                            {retryingNodeKey === selectedNode.nodeKey
                              ? <LoaderCircle className="is-running" size={14} />
                              : <RefreshCw size={14} />}
                            이 Node부터 다시 실행
                          </button>
                        )}
                      </section>
                      {selectedNode.runHistory.length > 0 && (
                        <section>
                          <h3>이전 실행</h3>
                          <div className="deep-analysis-run-history">
                            {selectedNode.runHistory.map((attempt) => (
                              <span key={attempt.runId}>
                                <em>시도 {attempt.attempt} · {statusLabel(attempt.status)}</em>
                                <b>{formatCost(attempt.costMicrousd, usdKrwRate)}</b>
                              </span>
                            ))}
                          </div>
                        </section>
                      )}
                    </aside>
                  )}
                </div>
                </> : (
                  <ExecutionLog missionId={mission.id} />
                )}
              </>
            ) : (
              <div className="deep-analysis-empty">
                <GitBranch size={24} />
                <h2>Mission을 선택해 주세요.</h2>
                <p>작업 세션을 Node로 연결해 순서대로 실행할 수 있습니다.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function MissionEventSummary({ missionId }: { missionId: string }) {
  const eventCount = useMissionEventCount(missionId);
  return <span className="deep-analysis-header-summary" role="status">{eventCount ? `기록 ${eventCount}개` : "기록 대기"}</span>;
}

function ExecutionLog({ missionId }: { missionId: string }) {
  const visibleEvents = useMissionEvents(missionId);
  const newestEvents = useMemo(() => visibleEvents.slice().reverse(), [visibleEvents]);
  const virtualList = useFixedVirtualList(newestEvents.length, 31, { threshold: 100, overscan: 10 });
  const renderedEvents = newestEvents.slice(virtualList.start, virtualList.end);
  return (
    <section className="deep-analysis-log-view" aria-label="실행 기록">
      <header>
        <div><strong>실행 기록</strong><span>Mission과 Node의 실행 기록을 최신순으로 확인합니다.</span></div>
      </header>
      <div className="deep-analysis-log-rows" ref={virtualList.containerRef} role="log" aria-live="polite" onScroll={(event) => virtualList.onScroll(event.currentTarget)}>
        {visibleEvents.length ? <div
          className={`deep-analysis-log-virtual-space ${virtualList.virtualized ? "is-virtualized" : ""}`}
          style={virtualList.virtualized ? { height: `${virtualList.totalHeight}px` } : undefined}
        >{renderedEvents.map((event, renderedIndex) => {
          const description = eventDescription(event);
          const isError = event.type.includes("failed") || event.type.includes("error");
          return (
            <div
              key={event.sequence}
              className={`deep-analysis-log-row is-${event.type}${isError ? " is-error" : ""}`}
              style={virtualList.virtualized ? { top: `${(virtualList.start + renderedIndex) * 31}px` } : undefined}
            >
              <time dateTime={event.createdAt}>{new Date(event.createdAt).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              <i aria-hidden="true" />
              <span>{description.nodeKey && <b>{description.nodeKey}</b>}{description.label}</span>
            </div>
          );
        })}</div> : (
          <div className="deep-analysis-log-empty"><strong>아직 실행 기록이 없습니다.</strong><span>Mission을 실행하면 Node 대기·시작·출력·완료 기록이 여기에 표시됩니다.</span></div>
        )}
      </div>
    </section>
  );
}

function WorkflowNodeButton({
  node,
  selected,
  showCost,
  usdKrwRate,
  onSelect,
  editable,
  connectionPortsSuppressed,
  onPointerLeave,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onKeyDown,
  connecting,
  connectionSource,
  onConnectionStart,
  onConnectionMove,
  onConnectionEnd,
  onConnectionKeyStart,
  onConnectionComplete,
}: {
  node: DeepAnalysisWorkflowNode;
  selected: boolean;
  showCost: boolean;
  usdKrwRate: number | null;
  onSelect: () => void;
  editable: boolean;
  connectionPortsSuppressed: boolean;
  onPointerLeave: () => void;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>) => void;
  connecting: boolean;
  connectionSource: boolean;
  onConnectionStart: (event: ReactPointerEvent<HTMLButtonElement>, side: WorkflowPortSide) => void;
  onConnectionMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onConnectionEnd: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onConnectionKeyStart: (side: WorkflowPortSide) => void;
  onConnectionComplete: () => void;
}) {
  const clockNow = useSharedNow(node.status === "running" && Boolean(node.startedAt));
  const normalizedStartedAt = node.startedAt ? normalizeUtcDateTime(node.startedAt) : null;
  const completedAt = node.status === "completed" && node.finishedAt
    ? Date.parse(normalizeUtcDateTime(node.finishedAt))
    : null;
  const elapsedTime = node.startedAt
    ? formatNodeElapsedTime(node.startedAt, node.status === "running" ? clockNow : completedAt ?? Number.NaN)
    : null;

  return (
    <div
      className={`deep-analysis-node-shell ${editable ? "is-editable" : ""} ${connectionPortsSuppressed ? "is-port-suppressed" : ""} ${connecting ? "is-connecting" : ""} ${connectionSource ? "is-connection-source" : ""}`}
      style={{ left: node.positionX, top: node.positionY }}
      onPointerLeave={onPointerLeave}
    >
      <button
        className={`deep-analysis-node ${selected ? "is-selected" : ""} ${editable ? "is-editable" : ""}`}
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onKeyDown={onKeyDown}
      >
        <div className="deep-analysis-node-meta">
          <span><GitBranch size={14} />{node.nodeKey}</span>
          <small className={`node-status status-${node.status}`}>
            <span>{statusLabel(node.status)}</span>
          </small>
        </div>
        <strong>{node.title}</strong>
        {showCost
          ? <span className="deep-analysis-node-cost">{formatCost(node.actualCostMicrousd, usdKrwRate)}</span>
          : elapsedTime && <time className="deep-analysis-node-elapsed" dateTime={normalizedStartedAt ?? undefined}>{elapsedTime}</time>}
      </button>
      {editable && <>
        {workflowPortSides.map((side) => (
          <button
            key={`output:${side}`}
            className={`deep-analysis-connection-port is-output port-${side}`}
            type="button"
            tabIndex={connecting ? -1 : 0}
            aria-label={`${node.nodeKey} ${side} 방향에서 연결 시작`}
            onPointerDown={(event) => onConnectionStart(event, side)}
            onPointerMove={onConnectionMove}
            onPointerUp={onConnectionEnd}
            onPointerCancel={onConnectionEnd}
            onClick={(event) => {
              if (event.detail === 0) onConnectionKeyStart(side);
            }}
          />
        ))}
        {workflowPortSides.map((side) => (
          <button
            key={`input:${side}`}
            className={`deep-analysis-connection-port is-input port-${side}`}
            type="button"
            tabIndex={connecting && !connectionSource ? 0 : -1}
            disabled={connectionSource}
            aria-label={`${node.nodeKey} ${side} 방향 입력에 연결`}
            data-connection-input={node.nodeKey}
            data-connection-side={side}
            onClick={onConnectionComplete}
          />
        ))}
      </>}
    </div>
  );
}
