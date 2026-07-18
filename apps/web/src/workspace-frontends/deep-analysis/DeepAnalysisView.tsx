import {
  AlertTriangle,
  ChevronRight,
  CircleAlert,
  CircleDollarSign,
  Download,
  GitBranch,
  LoaderCircle,
  Menu,
  Pause,
  Play,
  Plus,
  RefreshCw,
  RotateCcw,
  Square,
  Trash2,
  X,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import {
  type FormEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { api, ApiError } from "../../api";
import { SelectMenu } from "../../components/SelectMenu";
import type {
  DeepAnalysisAutonomyMode,
  DeepAnalysisCompletionContract,
  DeepAnalysisMissionCharter,
  DeepAnalysisMissionDetail,
  DeepAnalysisMissionEvent,
  DeepAnalysisMissionCosts,
  DeepAnalysisMissionSummary,
  DeepAnalysisWorkflowNode,
  DeepAnalysisWorkflowRevision,
  DeepAnalysisWorkflowPattern,
  DeepAnalysisWorkflowPatternVersion,
} from "../../api-types";
import "./deep-analysis.css";

interface DeepAnalysisViewProps {
  projectId: string | null;
  canEdit: boolean;
  requestedMissionId: string | null;
  createRequest: number;
  onCreateRequestHandled: () => void;
  onMissionsChange: (missions: DeepAnalysisMissionSummary[]) => void;
  onMissionsLoadingChange: (loading: boolean) => void;
  onSelectedMissionChange: (missionId: string | null) => void;
  onOpenNavigation: () => void;
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
const exportScopeOptions = [
  { value: "latest", label: "최신 생성 파일 전체" },
  { value: "report_evidence", label: "최종 보고서와 근거" },
  { value: "audit", label: "과거 version 포함 감사본" },
] as const;

function statusLabel(status: string) {
  return statusLabels[status] ?? status;
}

function formatCost(microusd: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  }).format(microusd / 1_000_000);
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) return error.message;
  return "심층분석 정보를 불러오지 못했습니다.";
}

function selectedMissionStorageKey(projectId: string) {
  return `lumina:deep-analysis:selected:${projectId}`;
}

function splitContractLines(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function normalizeMissionCharter(
  charter: Partial<DeepAnalysisMissionCharter> & { question?: string },
  fallbackPurpose: string,
): DeepAnalysisMissionCharter {
  const purpose = charter.purpose ?? charter.question ?? fallbackPurpose;
  return {
    ...charter,
    purpose,
    keyQuestions: Array.isArray(charter.keyQuestions)
      ? charter.keyQuestions
      : purpose ? [purpose] : [],
    deliverables: Array.isArray(charter.deliverables) ? charter.deliverables : [],
    audience: charter.audience ?? "",
    inScope: Array.isArray(charter.inScope) ? charter.inScope : [],
    outOfScope: Array.isArray(charter.outOfScope) ? charter.outOfScope : [],
    comparisonBasis: charter.comparisonBasis ?? "",
    qualityStandards: Array.isArray(charter.qualityStandards) ? charter.qualityStandards : [],
    confirmed: charter.confirmed ?? false,
  };
}

function normalizeCompletionContract(
  contract: Partial<DeepAnalysisCompletionContract>,
): DeepAnalysisCompletionContract {
  return {
    ...contract,
    requiredSections: Array.isArray(contract.requiredSections) ? contract.requiredSections : [],
    requiredNodeTypes: Array.isArray(contract.requiredNodeTypes) ? contract.requiredNodeTypes : ["report"],
    requireReport: contract.requireReport ?? true,
    requireNoFailedNodes: contract.requireNoFailedNodes ?? true,
    requireNoStaleNodes: contract.requireNoStaleNodes ?? true,
    minimumEvidenceCoverage: typeof contract.minimumEvidenceCoverage === "number"
      ? contract.minimumEvidenceCoverage
      : 0,
    maximumOpenIssues: typeof contract.maximumOpenIssues === "number" ? contract.maximumOpenIssues : 0,
    maximumUnexplainedResidualPercent:
      typeof contract.maximumUnexplainedResidualPercent === "number"
        ? contract.maximumUnexplainedResidualPercent
        : null,
    requiresFinalReview: contract.requiresFinalReview ?? false,
    allowWaiver: contract.allowWaiver ?? true,
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
    quality_gate_completed: "Quality Gate 검사를 완료했습니다.",
    mission_completed: "Mission을 완료했습니다.",
  };
  return { nodeKey, label: labels[event.type] ?? event.type.replaceAll("_", " ") };
}

export function DeepAnalysisView({
  projectId,
  canEdit,
  requestedMissionId,
  createRequest,
  onCreateRequestHandled,
  onMissionsChange,
  onMissionsLoadingChange,
  onSelectedMissionChange,
  onOpenNavigation,
}: DeepAnalysisViewProps) {
  const [missions, setMissions] = useState<DeepAnalysisMissionSummary[]>([]);
  const [patterns, setPatterns] = useState<DeepAnalysisWorkflowPattern[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
  const [mission, setMission] = useState<DeepAnalysisMissionDetail | null>(null);
  const [missionEvents, setMissionEvents] = useState<DeepAnalysisMissionEvent[]>([]);
  const [executionLogOpen, setExecutionLogOpen] = useState(true);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMission, setLoadingMission] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [budgetUsd, setBudgetUsd] = useState("");
  const [autonomyMode, setAutonomyMode] =
    useState<DeepAnalysisAutonomyMode>("balanced");
  const [selectedPatternVersionId, setSelectedPatternVersionId] = useState("");
  const [patternPanelOpen, setPatternPanelOpen] = useState(false);
  const [patternTargetId, setPatternTargetId] = useState("");
  const [patternName, setPatternName] = useState("");
  const [patternChangeSummary, setPatternChangeSummary] = useState("");
  const [savingPattern, setSavingPattern] = useState(false);
  const [patternDraftVersion, setPatternDraftVersion] = useState<DeepAnalysisWorkflowPatternVersion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [costDetailsOpen, setCostDetailsOpen] = useState(false);
  const [costDetails, setCostDetails] = useState<DeepAnalysisMissionCosts | null>(null);
  const [loadingCosts, setLoadingCosts] = useState(false);
  const [startingMission, setStartingMission] = useState(false);
  const [cancellingMission, setCancellingMission] = useState(false);
  const [pausingMission, setPausingMission] = useState(false);
  const [retryingNodeKey, setRetryingNodeKey] = useState<string | null>(null);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deletingMission, setDeletingMission] = useState(false);
  const [decisionOptionId, setDecisionOptionId] = useState("");
  const [decisionAnswerText, setDecisionAnswerText] = useState("");
  const [answeringDecision, setAnsweringDecision] = useState(false);
  const [contractOpen, setContractOpen] = useState(false);
  const [savingContract, setSavingContract] = useState(false);
  const [runningQualityGate, setRunningQualityGate] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportingMission, setExportingMission] = useState(false);
  const [exportScope, setExportScope] = useState<"latest" | "report_evidence" | "audit">("latest");
  const [exportIncludeOriginals, setExportIncludeOriginals] = useState(false);
  const [activeTab, setActiveTab] = useState<"workflow" | "evidence">("workflow");
  const [workflowDraft, setWorkflowDraft] = useState<DeepAnalysisWorkflowRevision | null>(null);
  const [workflowDraftDirty, setWorkflowDraftDirty] = useState(false);
  const [editingWorkflow, setEditingWorkflow] = useState(false);
  const [savingWorkflow, setSavingWorkflow] = useState(false);
  const [activatingWorkflow, setActivatingWorkflow] = useState(false);
  const [charterDraft, setCharterDraft] = useState<DeepAnalysisMissionCharter | null>(null);
  const [completionDraft, setCompletionDraft] = useState<DeepAnalysisCompletionContract | null>(null);
  const [canvasScale, setCanvasScale] = useState(1);
  const [canvasOffset, setCanvasOffset] = useState({ x: 0, y: 0 });
  const [canvasPanning, setCanvasPanning] = useState(false);
  const canvasViewportRef = useRef<HTMLDivElement>(null);
  const eventCursorRef = useRef(0);
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
  const publishedPatternOptions = useMemo(
    () => [
      { value: "", label: "제로베이스 · 질문에 맞춰 새로 설계" },
      ...patterns.flatMap((pattern) => pattern.latestPublishedVersion ? [{
        value: pattern.latestPublishedVersion.id,
        label: `${pattern.name} · v${pattern.latestPublishedVersion.versionNumber}`,
      }] : []),
    ],
    [patterns],
  );

  useEffect(() => onMissionsChange(missions), [missions, onMissionsChange]);
  useEffect(() => onMissionsLoadingChange(loadingList), [loadingList, onMissionsLoadingChange]);
  useEffect(() => onSelectedMissionChange(selectedMissionId), [onSelectedMissionChange, selectedMissionId]);

  useEffect(() => {
    if (!requestedMissionId) return;
    setSelectedMissionId(requestedMissionId);
    setCreateOpen(false);
  }, [requestedMissionId]);

  useEffect(() => {
    if (createRequest <= 0) return;
    setCreateOpen(true);
    onCreateRequestHandled();
  }, [createRequest, onCreateRequestHandled]);
  const patternTargetOptions = useMemo(
    () => [
      { value: "", label: "새 Project Pattern" },
      ...patterns.map((pattern) => ({ value: pattern.id, label: `${pattern.name}의 새 version` })),
    ],
    [patterns],
  );

  useEffect(() => {
    setMissions([]);
    setPatterns([]);
    setMission(null);
    setMissionEvents([]);
    setSelectedMissionId(null);
    setSelectedNodeKey(null);
    setWorkflowDraft(null);
    setEditingWorkflow(false);
    setActiveTab("workflow");
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
          setError(errorMessage(loadError));
        }
      })
      .finally(() => setLoadingList(false));
    void api.deepAnalysis.listPatterns(projectId, controller.signal)
      .then(setPatterns)
      .catch(() => {
        // Mission 목록은 Pattern Library의 일시적 실패와 독립적으로 사용할 수 있습니다.
      });
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    setMission(null);
    setMissionEvents([]);
    setSelectedNodeKey(null);
    setCostDetailsOpen(false);
    setDeleteArmed(false);
    setWorkflowDraft(null);
    setWorkflowDraftDirty(false);
    setEditingWorkflow(false);
    setActiveTab("workflow");
    if (!projectId || !selectedMissionId) return;

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
        setMission(detail);
        setSelectedNodeKey(detail.workflow.nodes[0]?.nodeKey ?? null);
        void api.deepAnalysis.listEvents(detail.id, 0, controller.signal)
          .then((events) => setMissionEvents(events.slice(-200)))
          .catch(() => {
            // Snapshot remains usable even if the audit timeline cannot be loaded.
          });
      })
      .catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(errorMessage(loadError));
        }
      })
      .finally(() => setLoadingMission(false));
    return () => controller.abort();
  }, [projectId, selectedMissionId]);

  useEffect(() => {
    setCanvasScale(1);
    setCanvasOffset({ x: 0, y: 0 });
  }, [selectedMissionId]);

  useEffect(() => {
    eventCursorRef.current = mission?.eventCursor ?? 0;
  }, [mission?.id, mission?.eventCursor]);

  useEffect(() => {
    if (mission?.status === "running") {
      setExecutionLogOpen(true);
    } else if (mission && ["completed", "cancelled", "failed"].includes(mission.status)) {
      setExecutionLogOpen(false);
    }
  }, [mission?.id, mission?.status]);

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
    if (
      !selectedMissionId
      || !mission
      || !["running", "paused", "awaiting_input"].includes(mission.status)
    ) return;
    let active = true;
    let snapshotTick = 0;
    const refresh = async () => {
      try {
        const events = await api.deepAnalysis.listEvents(
          selectedMissionId,
          eventCursorRef.current,
        );
        if (!active) return;
        if (events.length) {
          eventCursorRef.current = events.at(-1)?.sequence ?? eventCursorRef.current;
          setMissionEvents((current) => [...current, ...events].slice(-200));
        }
        snapshotTick += 1;
        if (!events.length && mission.status !== "running" && snapshotTick % 4 !== 0) return;
        const detail = await api.deepAnalysis.getMission(selectedMissionId);
        if (!active) return;
        eventCursorRef.current = detail.eventCursor;
        setMission(detail);
        setMissions((current) =>
          current.map((item) => (item.id === detail.id ? detail : item)),
        );
      } catch {
        // A transient polling failure must not hide the last durable snapshot.
      }
    };
    const timer = window.setInterval(() => void refresh(), 1_500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [mission?.status, selectedMissionId]);

  const shownWorkflow = workflowDraft ?? mission?.workflow ?? null;
  const selectedNode = useMemo(
    () => shownWorkflow?.nodes.find((node) => node.nodeKey === selectedNodeKey) ?? null,
    [shownWorkflow, selectedNodeKey],
  );
  const activeNode = useMemo(
    () => mission?.workflow.nodes.find((node) => node.status === "running") ?? null,
    [mission],
  );
  const pendingDecision = useMemo(
    () => mission?.decisions.find((decision) => decision.status === "pending") ?? null,
    [mission],
  );
  const completedNodeCount = useMemo(
    () => mission?.workflow.nodes.filter((node) => node.status === "completed").length ?? 0,
    [mission],
  );
  const latestQualityGate = useMemo(
    () => mission?.qualityGates.at(-1) ?? null,
    [mission?.qualityGates],
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

  useEffect(() => {
    setDecisionOptionId(
      pendingDecision?.recommendationOptionId
      ?? pendingDecision?.options[0]?.id
      ?? "",
    );
    setDecisionAnswerText("");
  }, [pendingDecision?.id]);

  useEffect(() => {
    if (!mission) {
      setCharterDraft(null);
      setCompletionDraft(null);
      return;
    }
    setCharterDraft(normalizeMissionCharter(mission.charter, mission.objective));
    setCompletionDraft(normalizeCompletionContract(mission.completionContract));
  }, [mission?.id, mission?.revision]);

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

  function fitCanvasToViewport() {
    const viewport = canvasViewportRef.current;
    const nodes = shownWorkflow?.nodes ?? [];
    if (!viewport || !nodes.length) return;

    const padding = 36;
    const minX = Math.min(...nodes.map((node) => node.positionX));
    const minY = Math.min(...nodes.map((node) => node.positionY));
    const maxX = Math.max(...nodes.map((node) => node.positionX + 176));
    const maxY = Math.max(...nodes.map((node) => node.positionY + 86));
    const contentWidth = Math.max(1, maxX - minX);
    const contentHeight = Math.max(1, maxY - minY);
    const fittedScale = Math.min(
      1,
      Math.max(
        minimumCanvasScale,
        Math.min(
          (viewport.clientWidth - padding * 2) / contentWidth,
          (viewport.clientHeight - padding * 2) / contentHeight,
        ),
      ),
    );
    setCanvasScale(fittedScale);
    setCanvasOffset({
      x: (viewport.clientWidth - contentWidth * fittedScale) / 2 - minX * fittedScale,
      y: (viewport.clientHeight - contentHeight * fittedScale) / 2 - minY * fittedScale,
    });
  }

  function closeNodeInspectorAndFit() {
    setSelectedNodeKey(null);
    window.requestAnimationFrame(() => window.requestAnimationFrame(fitCanvasToViewport));
  }

  useEffect(() => {
    if (!shownWorkflow?.graphDigest) return;
    const frame = window.requestAnimationFrame(() => fitCanvasToViewport());
    return () => window.cancelAnimationFrame(frame);
  }, [shownWorkflow?.graphDigest]);

  function beginCanvasPan(event: ReactPointerEvent<HTMLDivElement>) {
    if (event.button !== 0 || (event.target as Element).closest("button")) return;
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
    const wasBlankClick = Math.hypot(
      event.clientX - pan.clientX,
      event.clientY - pan.clientY,
    ) <= 4;
    canvasPanRef.current = null;
    setCanvasPanning(false);
    if (wasBlankClick) closeNodeInspectorAndFit();
  }

  async function beginWorkflowEdit() {
    if (!mission || editingWorkflow) return;
    setError(null);
    try {
      const draft = await api.deepAnalysis.createDraft(mission.id, mission.revision);
      setWorkflowDraft(draft);
      setWorkflowDraftDirty(false);
      setEditingWorkflow(true);
      setSelectedNodeKey(draft.nodes[0]?.nodeKey ?? null);
    } catch (draftError) {
      setError(errorMessage(draftError));
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
        estimatedCostMicrousd: node.estimatedCostMicrousd,
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
    if (!mission || !workflowDraft || activatingWorkflow) return;
    setActivatingWorkflow(true);
    try {
      const saved = workflowDraftDirty ? await saveWorkflowDraft() : workflowDraft;
      if (!saved) return;
      const activated = await api.deepAnalysis.activateDraft(mission.id, mission.revision);
      setMission(activated);
      setMissions((current) => current.map((item) => item.id === activated.id ? activated : item));
      setWorkflowDraft(null);
      setWorkflowDraftDirty(false);
      setEditingWorkflow(false);
      setSelectedNodeKey(activated.workflow.nodes[0]?.nodeKey ?? null);
    } catch (draftError) {
      setError(errorMessage(draftError));
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
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId || !workflowDraft) return;
    const dx = (event.clientX - drag.clientX) / canvasScale;
    const dy = (event.clientY - drag.clientY) / canvasScale;
    drag.moved = drag.moved || Math.hypot(dx, dy) > 3;
    setWorkflowDraft({
      ...workflowDraft,
      nodes: workflowDraft.nodes.map((node) => node.nodeKey === drag.nodeKey
        ? { ...node, positionX: drag.positionX + dx, positionY: drag.positionY + dy }
        : node),
    });
    setWorkflowDraftDirty(true);
  }

  function endNodeDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = nodeDragRef.current;
    if (!drag || drag.pointerId !== event.pointerId) return;
    nodeDragRef.current = null;
    setSelectedNodeKey(drag.nodeKey);
  }

  function toggleDependency(sourceNodeKey: string, targetNodeKey: string) {
    if (!workflowDraft || sourceNodeKey === targetNodeKey) return;
    const exists = workflowDraft.edges.some((edge) => edge.sourceNodeKey === sourceNodeKey && edge.targetNodeKey === targetNodeKey);
    setWorkflowDraft({
      ...workflowDraft,
      edges: exists
        ? workflowDraft.edges.filter((edge) => !(edge.sourceNodeKey === sourceNodeKey && edge.targetNodeKey === targetNodeKey))
        : [...workflowDraft.edges, { id: `draft:${sourceNodeKey}:${targetNodeKey}`, sourceNodeKey, targetNodeKey, edgeType: "sequence" }],
    });
    setWorkflowDraftDirty(true);
  }

  function handleNodeKeyDown(
    event: ReactKeyboardEvent<HTMLButtonElement>,
    node: DeepAnalysisWorkflowNode,
  ) {
    if (!editingWorkflow || !workflowDraft) return;
    if (event.key === "Delete" && node.nodeType !== "report") {
      event.preventDefault();
      removeDraftNode(node.nodeKey);
      return;
    }
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
    const used = new Set(workflowDraft.nodes.map((node) => node.nodeKey));
    let number = 10;
    while (used.has(`N${String(number).padStart(3, "0")}`)) number += 1;
    const nodeKey = `N${String(number).padStart(3, "0")}`;
    const report = workflowDraft.nodes.find((node) => node.nodeType === "report");
    const node: DeepAnalysisWorkflowNode = {
      ...workflowDraft.nodes[0],
      id: `draft:${nodeKey}`,
      nodeKey,
      nodeType: "research",
      title: "새 분석 단계",
      purpose: "이 단계에서 확인할 질문과 산출물을 정의해 주세요.",
      status: "planned",
      sequence: workflowDraft.nodes.length + 1,
      positionX: (report?.positionX ?? 520) - 220,
      positionY: (report?.positionY ?? 220) + 120,
      config: {}, runId: null, outputProjectFileId: null, outputLogicalPath: null,
      outputSummary: "", outputMarkdown: "", generatedFiles: [], runHistory: [],
      runStatus: null, liveOutput: "", errorMessage: null, actualCostMicrousd: 0,
      startedAt: null, finishedAt: null,
    };
    setWorkflowDraft({ ...workflowDraft, nodes: [...workflowDraft.nodes, node] });
    setWorkflowDraftDirty(true);
    setSelectedNodeKey(nodeKey);
  }

  function removeDraftNode(nodeKey: string) {
    if (!workflowDraft) return;
    const node = workflowDraft.nodes.find((item) => item.nodeKey === nodeKey);
    if (!node || node.nodeType === "report") return;
    setWorkflowDraft({
      ...workflowDraft,
      nodes: workflowDraft.nodes.filter((item) => item.nodeKey !== nodeKey),
      edges: workflowDraft.edges.filter((edge) => edge.sourceNodeKey !== nodeKey && edge.targetNodeKey !== nodeKey),
    });
    setWorkflowDraftDirty(true);
    setSelectedNodeKey(null);
  }

  async function startMission() {
    if (!mission || startingMission) return;
    setStartingMission(true);
    setError(null);
    try {
      const started = await api.deepAnalysis.startMission(mission.id, {
        expectedRevision: mission.revision,
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

  async function submitDecisionAnswer() {
    if (!mission || !pendingDecision || !decisionOptionId || answeringDecision) return;
    setAnsweringDecision(true);
    setError(null);
    try {
      const resumed = await api.deepAnalysis.answerDecision(
        mission.id,
        pendingDecision.id,
        {
          expectedRevision: mission.revision,
          selectedOptionId: decisionOptionId,
          answerText: decisionAnswerText.trim(),
        },
      );
      setMission(resumed);
      setMissions((current) => current.map((item) => item.id === resumed.id ? resumed : item));
    } catch (answerError) {
      setError(errorMessage(answerError));
    } finally {
      setAnsweringDecision(false);
    }
  }

  async function saveMissionContract() {
    if (!mission || !charterDraft || !completionDraft || savingContract) return;
    setSavingContract(true);
    setError(null);
    try {
      const updated = await api.deepAnalysis.updateMission(mission.id, {
        expectedRevision: mission.revision,
        charter: {
          purpose: charterDraft.purpose,
          keyQuestions: charterDraft.keyQuestions,
          deliverables: charterDraft.deliverables,
          audience: charterDraft.audience,
          inScope: charterDraft.inScope,
          outOfScope: charterDraft.outOfScope,
          comparisonBasis: charterDraft.comparisonBasis,
          qualityStandards: charterDraft.qualityStandards,
        },
        completionContract: {
          requiredSections: completionDraft.requiredSections,
          requiredNodeTypes: completionDraft.requiredNodeTypes,
          requireReport: completionDraft.requireReport,
          requireNoFailedNodes: completionDraft.requireNoFailedNodes,
          requireNoStaleNodes: completionDraft.requireNoStaleNodes,
          minimumEvidenceCoverage: completionDraft.minimumEvidenceCoverage,
          maximumOpenIssues: completionDraft.maximumOpenIssues,
          maximumUnexplainedResidualPercent: completionDraft.maximumUnexplainedResidualPercent,
          requiresFinalReview: completionDraft.requiresFinalReview,
          allowWaiver: completionDraft.allowWaiver,
        },
      });
      setMission(updated);
      setMissions((current) => current.map((item) => item.id === updated.id ? updated : item));
      setContractOpen(false);
    } catch (contractError) {
      setError(errorMessage(contractError));
    } finally {
      setSavingContract(false);
    }
  }

  function toggleGoalCompletionPanel() {
    const nextOpen = !contractOpen;
    setContractOpen(nextOpen);
    if (nextOpen) setExecutionLogOpen(false);
  }

  function toggleExecutionLog() {
    const nextOpen = !executionLogOpen;
    setExecutionLogOpen(nextOpen);
    if (nextOpen) setContractOpen(false);
  }

  async function rerunQualityGate() {
    if (!mission || runningQualityGate) return;
    setRunningQualityGate(true);
    setError(null);
    try {
      const updated = await api.deepAnalysis.runQualityGate(mission.id, {
        expectedRevision: mission.revision,
      });
      setMission(updated);
      setMissions((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (qualityError) {
      setError(errorMessage(qualityError));
    } finally {
      setRunningQualityGate(false);
    }
  }

  async function exportMission() {
    if (!mission || exportingMission) return;
    setExportingMission(true);
    setError(null);
    try {
      const operation = await api.deepAnalysis.createExport(mission.id, {
        scope: exportScope,
        includeOriginals: exportIncludeOriginals,
      });
      const download = await api.deepAnalysis.downloadExport(mission.id, operation.id);
      const url = URL.createObjectURL(download.blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = download.fileName;
      anchor.click();
      URL.revokeObjectURL(url);
      setExportOpen(false);
    } catch (exportError) {
      setError(errorMessage(exportError));
    } finally {
      setExportingMission(false);
    }
  }

  async function savePatternDraft() {
    if (!mission || !projectId || savingPattern) return;
    if (!patternTargetId && !patternName.trim()) {
      setError("새 Pattern 이름을 입력해 주세요.");
      return;
    }
    setSavingPattern(true);
    setError(null);
    try {
      const draft = patternTargetId
        ? await api.deepAnalysis.createPatternVersion(patternTargetId, {
            missionId: mission.id,
            changeSummary: patternChangeSummary.trim(),
          })
        : await api.deepAnalysis.createPattern(projectId, {
            missionId: mission.id,
            name: patternName.trim(),
            description: patternChangeSummary.trim(),
          });
      setPatternDraftVersion(draft);
    } catch (patternError) {
      setError(errorMessage(patternError));
    } finally {
      setSavingPattern(false);
    }
  }

  async function publishPatternDraft() {
    if (!projectId || !patternDraftVersion || savingPattern) return;
    setSavingPattern(true);
    setError(null);
    try {
      await api.deepAnalysis.publishPatternVersion(
        patternDraftVersion.patternId,
        patternDraftVersion.id,
      );
      setPatterns(await api.deepAnalysis.listPatterns(projectId));
      setPatternPanelOpen(false);
      setPatternDraftVersion(null);
      setPatternTargetId("");
      setPatternName("");
      setPatternChangeSummary("");
    } catch (patternError) {
      setError(errorMessage(patternError));
    } finally {
      setSavingPattern(false);
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

  async function createMission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || !title.trim()) return;
    const parsedBudget = budgetUsd.trim() ? Number(budgetUsd) : null;
    if (parsedBudget !== null && (!Number.isFinite(parsedBudget) || parsedBudget < 0)) {
      setError("최대 비용은 0 이상의 숫자로 입력해 주세요.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const created = await api.deepAnalysis.createMission(projectId, {
        title: title.trim(),
        objective: objective.trim(),
        autonomyMode,
        budgetMicrousd: parsedBudget !== null
          ? Math.round(parsedBudget * 1_000_000)
          : null,
        patternVersionId: selectedPatternVersionId || null,
      });
      setMissions((current) => [created, ...current]);
      setSelectedMissionId(created.id);
      setMission(created);
      setSelectedNodeKey(created.workflow.nodes[0]?.nodeKey ?? null);
      setTitle("");
      setObjective("");
      setAutonomyMode("balanced");
      setBudgetUsd("");
      setSelectedPatternVersionId("");
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
          <GitBranch size={17} />
          <h1>심층분석</h1>
          <span>장기 분석을 Workflow 단위로 기록하고 이어갑니다.</span>
        </div>
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
          <section className={`deep-analysis-workspace ${contractOpen ? "is-contract-open" : ""}`}>
            {createOpen ? (
              <div className="deep-analysis-create-shell">
                <header>
                  <div><GitBranch size={18} /><span><strong>새 분석</strong><small>현재 프로젝트에 새로운 심층분석 Mission을 만듭니다.</small></span></div>
                  <button type="button" aria-label="새 분석 닫기" onClick={() => setCreateOpen(false)}><X size={16} /></button>
                </header>
                <form className="deep-analysis-create" onSubmit={createMission}>
                  <label>
                    분석 이름
                    <input
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
                      rows={4}
                      maxLength={20_000}
                      placeholder="무엇을 설명하거나 결정해야 하는지 적어 주세요."
                      onChange={(event) => setObjective(event.target.value)}
                    />
                  </label>
                  <fieldset>
                    <legend>진행 방식</legend>
                    {(
                      [
                        ["guided", "단계별 확인"],
                        ["balanced", "균형 있게"],
                        ["autonomous", "자율 진행"],
                      ] as const
                    ).map(([value, label]) => (
                      <button
                        className={autonomyMode === value ? "is-active" : ""}
                        type="button"
                        key={value}
                        aria-pressed={autonomyMode === value}
                        onClick={() => setAutonomyMode(value)}
                      >
                        {label}
                      </button>
                    ))}
                  </fieldset>
                  <div className="deep-analysis-select-field">
                    Workflow 시작 방식
                    <SelectMenu
                      value={selectedPatternVersionId}
                      options={publishedPatternOptions}
                      ariaLabel="Workflow 시작 방식"
                      onChange={setSelectedPatternVersionId}
                    />
                    <small>{selectedPatternVersionId ? "선택한 Pattern은 초기 뼈대이며 Mission 질문과 중간 결과에 따라 달라질 수 있습니다." : "Pattern 없이도 동일한 실행·기록·복구 기능을 사용합니다."}</small>
                  </div>
                  <label>
                    최대 비용 (US$, 선택)
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      inputMode="decimal"
                      value={budgetUsd}
                      placeholder="예: 1.00"
                      onChange={(event) => setBudgetUsd(event.target.value)}
                    />
                  </label>
                  <button className="deep-analysis-create-submit" type="submit" disabled={creating || !title.trim()}>
                    {creating && <LoaderCircle className="is-running" size={14} />}
                    Mission 만들기
                  </button>
                </form>
              </div>
            ) : loadingMission ? (
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
                        disabled={startingMission || !mission.executionAvailable || editingWorkflow}
                        data-tooltip={editingWorkflow ? "Workflow Draft를 활성화한 뒤 시작해 주세요." : !mission.executionAvailable ? "실제 분석 실행기가 연결된 후 시작할 수 있습니다." : undefined}
                        onClick={() => void startMission()}
                      >
                        {startingMission ? <LoaderCircle className="is-running" size={15} /> : <Play size={15} />}
                        {startingMission ? "시작 중" : mission.executionAvailable ? "Workflow 시작" : "실행 엔진 준비 중"}
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
                    <button
                      className={`deep-analysis-contract-toggle ${contractOpen ? "is-active" : ""}`}
                      type="button"
                      aria-expanded={contractOpen}
                      aria-controls="deep-analysis-goal-completion"
                      onClick={toggleGoalCompletionPanel}
                    >
                      목표·완료 기준
                    </button>
                    <div className="deep-analysis-pattern-wrap">
                      <button className="deep-analysis-contract-toggle" type="button" aria-expanded={patternPanelOpen} onClick={() => setPatternPanelOpen((open) => !open)}>Pattern</button>
                      {patternPanelOpen && (
                        <div className="deep-analysis-pattern-popover">
                          <strong>Workflow Pattern</strong>
                          {!patternDraftVersion ? <>
                            <div className="deep-analysis-select-field">저장 위치<SelectMenu value={patternTargetId} options={patternTargetOptions} ariaLabel="Pattern 저장 위치" size="small" onChange={setPatternTargetId} /></div>
                            {!patternTargetId && <label>Pattern 이름<input value={patternName} maxLength={240} placeholder="예: 손익 변동 원인 분석" onChange={(event) => setPatternName(event.target.value)} /></label>}
                            <label>{patternTargetId ? "변경 요약" : "설명"}<textarea rows={2} value={patternChangeSummary} onChange={(event) => setPatternChangeSummary(event.target.value)} /></label>
                            <small>파일 ID·수치·답변·출력은 제외하고 구조와 semantic input role만 Draft에 저장합니다.</small>
                            <button type="button" disabled={savingPattern} onClick={() => void savePatternDraft()}>{savingPattern ? <LoaderCircle className="is-running" size={13} /> : null}{savingPattern ? "생성 중" : "검토용 Draft 만들기"}</button>
                          </> : <>
                            <div className="deep-analysis-pattern-review"><span>Version {patternDraftVersion.versionNumber} · Draft</span><code>{patternDraftVersion.definitionDigest.slice(0, 16)}…</code><small>Node {patternDraftVersion.definition.nodes.length}개 · Edge {patternDraftVersion.definition.edges.length}개</small></div>
                            <small>Publish하면 이 version은 immutable하며 이후 Mission이 명시적으로 선택할 수 있습니다.</small>
                            <button type="button" disabled={savingPattern} onClick={() => void publishPatternDraft()}>{savingPattern ? <LoaderCircle className="is-running" size={13} /> : null}{savingPattern ? "게시 중" : "검토 완료 · Publish"}</button>
                          </>}
                        </div>
                      )}
                    </div>
                    {canEdit && (mission.status === "draft" || mission.status === "ready") && (editingWorkflow ? <>
                      <button className="deep-analysis-workflow-action" type="button" onClick={addDraftNode}><Plus size={13} /> Node 추가</button>
                      <button className="deep-analysis-workflow-action" type="button" disabled={!workflowDraftDirty || savingWorkflow} onClick={() => void saveWorkflowDraft()}>{savingWorkflow ? <LoaderCircle className="is-running" size={13} /> : null}{savingWorkflow ? "저장 중" : "Draft 저장"}</button>
                      <button className="deep-analysis-workflow-action is-primary" type="button" disabled={savingWorkflow || activatingWorkflow} onClick={() => void activateWorkflowDraft()}>{activatingWorkflow ? <LoaderCircle className="is-running" size={13} /> : null}{activatingWorkflow ? "활성화 중" : "Draft 활성화"}</button>
                    </> : (
                      <button className="deep-analysis-workflow-action is-primary" type="button" onClick={() => void beginWorkflowEdit()}>편집 시작</button>
                    ))}
                    <div className="deep-analysis-export-wrap">
                      <button className="deep-analysis-export tooltip-control" type="button" aria-label="Mission 내보내기" aria-expanded={exportOpen} data-tooltip="내보내기" onClick={() => setExportOpen((open) => !open)}>
                        <Download size={15} />
                      </button>
                      {exportOpen && (
                        <div className="deep-analysis-export-popover">
                          <strong>Mission 내보내기</strong>
                          <div className="deep-analysis-select-field">범위<SelectMenu value={exportScope} options={exportScopeOptions} ariaLabel="Mission 내보내기 범위" size="small" onChange={(value) => setExportScope(value as typeof exportScope)} /></div>
                          <label className="deep-analysis-export-check"><input type="checkbox" checked={exportIncludeOriginals} onChange={(event) => setExportIncludeOriginals(event.target.checked)} /> Project 원본 자료 포함</label>
                          <small>원본 자료를 포함하면 현재 권한과 exact frozen version을 다시 확인합니다.</small>
                          <button type="button" disabled={exportingMission} onClick={() => void exportMission()}>{exportingMission ? <LoaderCircle className="is-running" size={13} /> : <Download size={13} />}{exportingMission ? "준비 중" : "ZIP 다운로드"}</button>
                        </div>
                      )}
                    </div>
                    <div className="deep-analysis-cost-wrap">
                      <button
                        className="deep-analysis-cost tooltip-control"
                        type="button"
                        aria-label={`누적 비용 ${formatCost(mission.spentMicrousd)}`}
                        aria-expanded={costDetailsOpen}
                        data-tooltip={`누적 비용 ${formatCost(mission.spentMicrousd)}`}
                        onClick={() => setCostDetailsOpen((open) => !open)}
                      >
                        <CircleDollarSign size={16} />
                      </button>
                      {costDetailsOpen && (
                        <div className="deep-analysis-cost-popover">
                          <strong>비용 상세</strong>
                          <span className="is-budget"><em>누적 비용</em><b>{formatCost(mission.spentMicrousd)}</b></span>
                          {mission.budgetMicrousd !== null && <span><em>설정 예산</em><b>{formatCost(mission.budgetMicrousd)}</b></span>}
                          {costDetails && <>
                            <span><em>예상 완료 비용</em><b>{formatCost(costDetails.estimatedCompletionMicrousd)}</b></span>
                            <span><em>Cache 미적용 상한</em><b>{formatCost(costDetails.noCacheUpperBoundMicrousd)}</b></span>
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
                                <b>{formatCost(row.actualCostMicrousd)}</b>
                              </div>)}
                            </div>
                          </>}
                          {loadingCosts && <span><em><LoaderCircle className="is-running" size={13} /> 불러오는 중</em></span>}
                        </div>
                      )}
                    </div>
                    {canEdit && (
                      <button
                        className={`deep-analysis-delete ${deleteArmed ? "is-armed" : ""}`}
                        type="button"
                        aria-label={deleteArmed ? "심층분석 삭제 확인, 한 번 더 누르면 삭제" : "심층분석 삭제"}
                        data-tooltip={mission.status === "running" || mission.status === "paused" || mission.status === "awaiting_input" ? "먼저 실행을 중단해 주세요." : deleteArmed ? "한 번 더 눌러 삭제" : "삭제"}
                        disabled={deletingMission || mission.status === "running" || mission.status === "paused" || mission.status === "awaiting_input"}
                        onClick={() => void deleteMission()}
                      >
                        {deletingMission ? <LoaderCircle className="is-running" size={14} /> : deleteArmed ? <AlertTriangle size={14} /> : <Trash2 size={14} />}
                        {deleteArmed ? "한 번 더 눌러 삭제" : "삭제"}
                      </button>
                    )}
                  </div>
                </header>
                <div className="deep-analysis-tabs" role="tablist" aria-label="심층분석 화면">
                  <button className={activeTab === "workflow" ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === "workflow"} onClick={() => setActiveTab("workflow")}>Workflow</button>
                  <button className={activeTab === "evidence" ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === "evidence"} onClick={() => setActiveTab("evidence")}>결론·근거</button>
                  <span>
                    {activeTab === "workflow" ? <>
                      {completedNodeCount}/{shownWorkflow?.nodes.length ?? 0} 완료 · 분기 {workflowTopology.branchCount} · 합류 {workflowTopology.mergeCount} · 입력 자료 {mission.sourceManifest.length}개 · Revision {shownWorkflow?.revisionNumber}
                    </> : <>
                      Claim {mission.claims.length}개 · Evidence {mission.evidence.length}개 · Open Issue {mission.openIssues.filter((item) => item.status === "open").length}개
                    </>}
                  </span>
                </div>
                {contractOpen && charterDraft && completionDraft && (
                  <section id="deep-analysis-goal-completion" className="deep-analysis-contract" aria-label="분석 목표와 완료 기준">
                    <div className="deep-analysis-contract-scroll">
                      <div className="deep-analysis-contract-content">
                        <header className="deep-analysis-contract-heading">
                          <strong>목표·완료 기준</strong>
                          <p>분석이 반드시 답해야 할 내용과 대상 기간, 산출물 형태를 정합니다.</p>
                        </header>
                        <div className="deep-analysis-contract-primary">
                          <label>분석 목표<textarea rows={3} value={charterDraft.purpose} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, purpose: event.target.value })} /></label>
                          <label>핵심 질문<textarea rows={5} value={charterDraft.keyQuestions.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, keyQuestions: splitContractLines(event.target.value) })} /></label>
                          <label>보고서 구성<textarea rows={5} value={completionDraft.requiredSections.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCompletionDraft({ ...completionDraft, requiredSections: splitContractLines(event.target.value) })} /></label>
                          <label>대상 기간<input placeholder="예: 2025년 4분기 대비 2026년 4분기" value={charterDraft.comparisonBasis} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, comparisonBasis: event.target.value })} /></label>
                          <label>산출물 형태<input placeholder="예: 경영진용 Markdown 보고서" value={charterDraft.deliverables.join(", ")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, deliverables: event.target.value.trim() ? [event.target.value] : [] })} /></label>
                        </div>
                      </div>
                    </div>
                    {(mission.status === "draft" || mission.status === "ready") && canEdit && (
                      <div className="deep-analysis-contract-actions">
                        <span>실행을 시작하면 이 계약이 해당 Mission revision에 고정됩니다.</span>
                        <button type="button" disabled={savingContract || !charterDraft.purpose.trim()} onClick={() => void saveMissionContract()}>
                          {savingContract && <LoaderCircle className="is-running" size={14} />}
                          {savingContract ? "저장 중" : "기준 저장"}
                        </button>
                      </div>
                    )}
                  </section>
                )}
                {latestQualityGate && (
                  <section className={`deep-analysis-quality-gate is-${latestQualityGate.result}`} aria-label="최신 Quality Gate 결과">
                    <div>
                      {latestQualityGate.result === "passed" ? <CircleAlert size={16} /> : <AlertTriangle size={16} />}
                      <span>
                        <strong>Quality Gate · {latestQualityGate.result === "passed" ? "통과" : latestQualityGate.result === "waived" ? "예외 승인" : "미충족"}</strong>
                        <small>{latestQualityGate.checks.filter((check) => check.status === "passed").length}/{latestQualityGate.checks.length} 검사 통과 · 결과 {mission.completionOutcome ?? "확정 대기"}</small>
                      </span>
                    </div>
                    <details>
                      <summary>검사 결과 보기</summary>
                      {latestQualityGate.checks.map((check) => (
                        <span className={`is-${check.status}`} key={check.id}><b>{check.status === "passed" ? "통과" : "미충족"}</b><em>{check.message}</em></span>
                      ))}
                    </details>
                    {canEdit && !pendingDecision && (mission.status === "blocked" || mission.status === "completed") && (
                      <button className="deep-analysis-quality-rerun" type="button" disabled={runningQualityGate} onClick={() => void rerunQualityGate()}>
                        {runningQualityGate ? <LoaderCircle className="is-running" size={13} /> : <RefreshCw size={13} />}
                        {runningQualityGate ? "검사 중" : "Quality Gate 다시 검사"}
                      </button>
                    )}
                  </section>
                )}
                {activeTab === "workflow" ? <>
                {pendingDecision && (
                  <section className="deep-analysis-decision" aria-labelledby={`decision-${pendingDecision.id}`}>
                    <div className="deep-analysis-decision-heading">
                      <CircleAlert size={17} />
                      <div>
                        <strong id={`decision-${pendingDecision.id}`}>사용자 판단이 필요합니다</strong>
                        <span>{pendingDecision.requestedByNodeKey ? `${pendingDecision.requestedByNodeKey} 결과에서 요청됨` : "Workflow 진행을 위한 확인"}</span>
                      </div>
                    </div>
                    <p>{pendingDecision.question}</p>
                    <div className="deep-analysis-decision-options" role="radiogroup" aria-label="판단 선택지">
                      {pendingDecision.options.map((option) => {
                        const recommended = option.id === pendingDecision.recommendationOptionId;
                        return (
                          <button
                            type="button"
                            role="radio"
                            aria-checked={decisionOptionId === option.id}
                            className={decisionOptionId === option.id ? "is-selected" : ""}
                            key={option.id}
                            onClick={() => setDecisionOptionId(option.id)}
                            disabled={!canEdit || answeringDecision}
                          >
                            <span><strong>{option.label}</strong>{recommended && <em>AI 권고</em>}</span>
                            {option.description && <small>{option.description}</small>}
                          </button>
                        );
                      })}
                    </div>
                    {pendingDecision.recommendationRationale && (
                      <div className="deep-analysis-decision-recommendation">
                        <strong>권고 근거</strong>
                        <span>{pendingDecision.recommendationRationale}</span>
                      </div>
                    )}
                    {canEdit && (
                      <div className="deep-analysis-decision-answer">
                        <textarea
                          rows={2}
                          maxLength={4000}
                          value={decisionAnswerText}
                          placeholder="추가 지시나 판단 근거가 있으면 적어 주세요. (선택)"
                          onChange={(event) => setDecisionAnswerText(event.target.value)}
                        />
                        <button
                          type="button"
                          disabled={!decisionOptionId || answeringDecision}
                          onClick={() => void submitDecisionAnswer()}
                        >
                          {answeringDecision && <LoaderCircle className="is-running" size={14} />}
                          {answeringDecision ? "적용 중" : "이 결정으로 계속"}
                        </button>
                      </div>
                    )}
                  </section>
                )}
                {mission.status === "running" && (
                  <div className="deep-analysis-run-feedback is-running" role="status">
                    <LoaderCircle className="is-running" size={16} />
                    <div>
                      <strong>{activeNode ? `${activeNode.nodeKey} · ${activeNode.title} 실행 중` : "분석 작업 실행 중"}</strong>
                      <span>{activeNode?.runId
                        ? `실제 Lumina Run ${activeNode.runStatus ? `· ${statusLabel(activeNode.runStatus)}` : ""} · ${completedNodeCount}/${mission.workflow.nodes.length} Node 완료`
                        : "실행 Run을 준비하고 있습니다."} 결과에 따라 남은 Workflow가 확장되거나 축소될 수 있습니다.</span>
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
                <div className={`deep-analysis-workflow-layout ${selectedNode ? "has-inspector" : ""}`}>
                  <div className="deep-analysis-canvas-shell">
                  <div
                    className={`deep-analysis-canvas-scroll ${canvasPanning ? "is-panning" : ""}`}
                    ref={canvasViewportRef}
                    onPointerDown={beginCanvasPan}
                    onPointerMove={moveCanvasPan}
                    onPointerUp={endCanvasPan}
                    onPointerCancel={endCanvasPan}
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
                      style={{ transform: `translate3d(${canvasOffset.x}px, ${canvasOffset.y}px, 0) scale(${canvasScale})` }}
                    >
                      <svg aria-hidden="true">
                        <defs>
                          <marker id="deep-analysis-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
                            <path d="M0,0 L0,7 L7,3.5 z" />
                          </marker>
                        </defs>
                        {(shownWorkflow?.edges ?? []).map((edge) => {
                          const source = shownWorkflow?.nodes.find((node) => node.nodeKey === edge.sourceNodeKey);
                          const target = shownWorkflow?.nodes.find((node) => node.nodeKey === edge.targetNodeKey);
                          if (!source || !target) return null;
                          return (
                            <path
                              key={edge.id}
                              className={`${workflowTopology.branchNodeKeys.has(edge.sourceNodeKey) ? "is-branch" : ""} ${workflowTopology.mergeNodeKeys.has(edge.targetNodeKey) ? "is-merge" : ""}`.trim()}
                              d={`M ${source.positionX + 176} ${source.positionY + 43} C ${source.positionX + 198} ${source.positionY + 43}, ${target.positionX - 22} ${target.positionY + 43}, ${target.positionX} ${target.positionY + 43}`}
                              markerEnd="url(#deep-analysis-arrow)"
                            />
                          );
                        })}
                      </svg>
                      {(shownWorkflow?.nodes ?? []).map((node) => (
                        <WorkflowNodeButton
                          key={node.id}
                          node={node}
                          selected={selectedNodeKey === node.nodeKey}
                          onSelect={() => setSelectedNodeKey(node.nodeKey)}
                          editable={editingWorkflow}
                          onPointerDown={(event) => beginNodeDrag(event, node)}
                          onPointerMove={moveNodeDrag}
                          onPointerUp={endNodeDrag}
                          onKeyDown={(event) => handleNodeKeyDown(event, node)}
                        />
                      ))}
                    </div>
                    </div>
                  </div>
                    <div className="deep-analysis-canvas-controls" aria-label="Workflow 확대 및 축소">
                      <button type="button" aria-label="확대" data-tooltip="확대" disabled={canvasScale >= maximumCanvasScale} onClick={() => updateCanvasScale(canvasScale + 0.1)}><ZoomIn size={14} /></button>
                      <button type="button" aria-label="배율 초기화" onClick={() => updateCanvasScale(1)}>{Math.round(canvasScale * 100)}%</button>
                      <button type="button" aria-label="축소" data-tooltip="축소" disabled={canvasScale <= minimumCanvasScale} onClick={() => updateCanvasScale(canvasScale - 0.1)}><ZoomOut size={14} /></button>
                      <button type="button" aria-label="위치 초기화" onClick={() => {
                        setCanvasScale(1);
                        setCanvasOffset({ x: 0, y: 0 });
                      }}><RotateCcw size={13} /></button>
                    </div>
                  </div>
                  {selectedNode && (
                    <aside className="deep-analysis-inspector" aria-label={`${selectedNode.title} 상세 정보`}>
                      <header>
                        <div><span>{selectedNode.nodeKey}</span><button type="button" aria-label="노드 상세 닫기" onClick={closeNodeInspectorAndFit}><X size={14} /></button></div>
                        <strong>{selectedNode.title}</strong>
                        <small className={`node-status status-${selectedNode.status}`}>{statusLabel(selectedNode.status)}</small>
                      </header>
                      <section>
                        <h3>목적</h3>
                        {editingWorkflow && workflowDraft ? <>
                          <label className="deep-analysis-node-edit-field">이름<input value={selectedNode.title} onChange={(event) => {
                            setWorkflowDraft({ ...workflowDraft, nodes: workflowDraft.nodes.map((node) => node.nodeKey === selectedNode.nodeKey ? { ...node, title: event.target.value } : node) });
                            setWorkflowDraftDirty(true);
                          }} /></label>
                          <label className="deep-analysis-node-edit-field">목적<textarea rows={3} value={selectedNode.purpose} onChange={(event) => {
                            setWorkflowDraft({ ...workflowDraft, nodes: workflowDraft.nodes.map((node) => node.nodeKey === selectedNode.nodeKey ? { ...node, purpose: event.target.value } : node) });
                            setWorkflowDraftDirty(true);
                          }} /></label>
                        </> : <p>{selectedNode.purpose}</p>}
                        {typeof selectedNode.config.reason === "string" && (
                          <small className="deep-analysis-node-origin">
                            <GitBranch size={12} /> {selectedNode.config.reason}
                          </small>
                        )}
                      </section>
                      {editingWorkflow && workflowDraft && (
                        <section className="deep-analysis-node-dependencies">
                          <h3>선행 Node 연결</h3>
                          <p>선택한 Node로 들어오는 연결입니다. 여러 Node를 선택하면 합류가 됩니다.</p>
                          {workflowDraft.nodes.filter((node) => node.nodeKey !== selectedNode.nodeKey).map((node) => {
                            const checked = workflowDraft.edges.some((edge) => edge.sourceNodeKey === node.nodeKey && edge.targetNodeKey === selectedNode.nodeKey);
                            return <label key={node.nodeKey}><input type="checkbox" checked={checked} onChange={() => toggleDependency(node.nodeKey, selectedNode.nodeKey)} /><span><b>{node.nodeKey}</b>{node.title}</span></label>;
                          })}
                          {selectedNode.nodeType !== "report" && <button type="button" onClick={() => removeDraftNode(selectedNode.nodeKey)}><Trash2 size={13} /> 이 Node 삭제</button>}
                        </section>
                      )}
                      <section>
                        <h3>출력</h3>
                        {selectedNode.status === "running" && !selectedNode.outputSummary ? (
                          <>
                            <p className="deep-analysis-node-progress"><LoaderCircle className="is-running" size={13} /> 모델 응답을 생성하고 있습니다.</p>
                            {selectedNode.liveOutput && (
                              <pre className="deep-analysis-live-output">{selectedNode.liveOutput}</pre>
                            )}
                          </>
                        ) : selectedNode.errorMessage ? (
                          <p className="deep-analysis-node-error">{selectedNode.errorMessage}</p>
                        ) : (
                          <p>{selectedNode.outputSummary || "아직 생성된 출력이 없습니다."}</p>
                        )}
                        {selectedNode.outputLogicalPath && (
                          <small className="deep-analysis-output-path">{selectedNode.outputLogicalPath}</small>
                        )}
                        {selectedNode.outputMarkdown && (
                          <details className="deep-analysis-output-document">
                            <summary>문서 전체 보기</summary>
                            <pre>{selectedNode.outputMarkdown}</pre>
                          </details>
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
                                <b>{formatCost(attempt.costMicrousd)}</b>
                              </span>
                            ))}
                          </div>
                        </section>
                      )}
                      {selectedNode.contextManifest && (
                        <section>
                          <h3>Context Manifest</h3>
                          <dl>
                            <div><dt>Exact item</dt><dd>{selectedNode.contextManifest.itemCount}</dd></div>
                            <div><dt>Token 추정</dt><dd>{selectedNode.contextManifest.tokenEstimate.toLocaleString()}</dd></div>
                            <div><dt>Tool profile</dt><dd>{selectedNode.contextManifest.toolProfile}</dd></div>
                          </dl>
                          <small className="deep-analysis-prefix-hash">Prefix {selectedNode.contextManifest.prefixHash.slice(0, 16)}… · Mission context r{selectedNode.contextManifest.missionContextRevision}</small>
                        </section>
                      )}
                      <section>
                        <h3>비용</h3>
                        <dl>
                          <div><dt>예상</dt><dd>{formatCost(selectedNode.estimatedCostMicrousd)}</dd></div>
                          <div><dt>누적</dt><dd>{formatCost(selectedNode.actualCostMicrousd)}</dd></div>
                        </dl>
                      </section>
                    </aside>
                  )}
                </div>
                <section className={`deep-analysis-execution-log ${executionLogOpen ? "is-open" : ""}`} aria-label="실행 과정">
                  <button
                    type="button"
                    aria-expanded={executionLogOpen}
                    onClick={toggleExecutionLog}
                  >
                    <ChevronRight size={14} />
                    <strong>실행 과정</strong>
                    <span>{missionEvents.length ? `Event ${missionEvents.at(-1)?.sequence}` : "기록 대기"}</span>
                    {mission.status === "running" && <LoaderCircle className="is-running" size={13} />}
                  </button>
                  {executionLogOpen && (
                    <div className="deep-analysis-execution-events" role="log" aria-live="polite">
                      {missionEvents.length ? missionEvents.slice(-12).map((event) => {
                        const description = eventDescription(event);
                        return (
                          <div key={event.sequence} className={`is-${event.type}`}>
                            <time dateTime={event.createdAt}>{new Date(event.createdAt).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
                            <i aria-hidden="true" />
                            <span>{description.nodeKey && <b>{description.nodeKey}</b>}{description.label}</span>
                          </div>
                        );
                      }) : (
                        <p>실행을 시작하면 Node 대기·시작·출력·완료 기록이 여기에 순서대로 남습니다.</p>
                      )}
                    </div>
                  )}
                </section>
                </> : (
                  <EvidenceLedger mission={mission} />
                )}
              </>
            ) : (
              <div className="deep-analysis-empty">
                <GitBranch size={24} />
                <h2>Mission을 선택해 주세요.</h2>
                <p>각 단계의 질문, 판단 근거와 산출물이 Workflow에 누적됩니다.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </main>
  );
}

function EvidenceLedger({ mission }: { mission: DeepAnalysisMissionDetail }) {
  const linkedEvidenceIds = new Set(
    mission.claims.flatMap((claim) => claim.evidence.map((item) => item.evidence.id)),
  );
  const orphanEvidence = mission.evidence.filter((item) => !linkedEvidenceIds.has(item.id));
  return (
    <div className="deep-analysis-ledger" aria-label="Claim과 Evidence 원장">
      <section className="deep-analysis-ledger-main">
        <header>
          <div><strong>Claim Ledger</strong><span>결론에서 정확한 근거와 원본 revision까지 역추적합니다.</span></div>
          <small>{mission.claims.filter((claim) => claim.status === "verified").length}개 검증됨</small>
        </header>
        {mission.claims.length ? mission.claims.map((claim) => (
          <article className={`deep-analysis-claim is-${claim.materiality}`} key={claim.id}>
            <div className="deep-analysis-claim-meta">
              <span>{claim.level.replaceAll("_", " ")}</span>
              <b>{claim.status}</b>
              {claim.staleStatus !== "fresh" && <em>재검토 필요</em>}
              <small>{claim.sourceNodeKey ?? "Mission"}{claim.confidence !== null ? ` · 신뢰도 ${Math.round(claim.confidence * 100)}%` : ""}</small>
            </div>
            <p>{claim.statement}</p>
            <code>[Claim:{claim.id}]</code>
            <div className="deep-analysis-evidence-links">
              {claim.evidence.length ? claim.evidence.map(({ evidence, stance, rationale }) => (
                <div className={`is-${stance}`} key={`${claim.id}:${evidence.id}:${stance}`}>
                  <span><b>{stance === "support" ? "지지" : stance === "contradict" ? "상충" : "맥락"}</b><strong>{evidence.title || evidence.stableId}</strong></span>
                  <small>{evidence.sourceType} · {evidence.locator || "위치 미지정"}</small>
                  {evidence.contentDigest && <code>{evidence.contentDigest.slice(0, 16)}…</code>}
                  {rationale && <p>{rationale}</p>}
                </div>
              )) : <span className="deep-analysis-no-evidence">연결된 exact Evidence가 없습니다.</span>}
            </div>
          </article>
        )) : (
          <div className="deep-analysis-ledger-empty"><GitBranch size={20} /><strong>아직 등록된 Claim이 없습니다.</strong><span>Node 실행 결과가 저장되면 근거와 함께 이곳에 누적됩니다.</span></div>
        )}
      </section>
      <aside className="deep-analysis-ledger-aside">
        {mission.files.length > 0 && (
          <section>
            <header><strong>Mission 자료</strong><span>{mission.files.length}</span></header>
            {mission.files.map((file) => <article key={file.id}>
              <div><b>{file.purpose}</b><small>{file.producingNodeKey ?? "원본"} · v{file.version}</small></div>
              <p>{file.logicalPath}</p>
              <code>{file.contentHash.slice(0, 16)}…</code>
              {file.staleStatus !== "fresh" && <em>재검토 필요</em>}
            </article>)}
          </section>
        )}
        <section>
          <header><strong>Open Issue</strong><span>{mission.openIssues.filter((item) => item.status === "open").length}</span></header>
          {mission.openIssues.length ? mission.openIssues.map((issue) => (
            <article key={issue.id}>
              <div><b>{issue.materiality}</b><small>{issue.status} · {issue.sourceNodeKey ?? "Mission"}</small></div>
              <p>{issue.statement}</p>
              {issue.requiredAction && <span>{issue.requiredAction}</span>}
              {issue.residualPercent !== null && <em>잔여 {issue.residualPercent}%</em>}
            </article>
          )) : <p className="deep-analysis-ledger-none">등록된 미해결 항목이 없습니다.</p>}
        </section>
        {orphanEvidence.length > 0 && (
          <section>
            <header><strong>미연결 Evidence</strong><span>{orphanEvidence.length}</span></header>
            {orphanEvidence.map((item) => <article key={item.id}><p>{item.title || item.stableId}</p><small>{item.sourceType} · {item.locator}</small></article>)}
          </section>
        )}
      </aside>
    </div>
  );
}

function WorkflowNodeButton({
  node,
  selected,
  onSelect,
  editable,
  onPointerDown,
  onPointerMove,
  onPointerUp,
  onKeyDown,
}: {
  node: DeepAnalysisWorkflowNode;
  selected: boolean;
  onSelect: () => void;
  editable: boolean;
  onPointerDown: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerMove: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onPointerUp: (event: ReactPointerEvent<HTMLButtonElement>) => void;
  onKeyDown: (event: ReactKeyboardEvent<HTMLButtonElement>) => void;
}) {
  return (
    <button
      className={`deep-analysis-node ${selected ? "is-selected" : ""} ${editable ? "is-editable" : ""}`}
      style={{ left: node.positionX, top: node.positionY }}
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      onKeyDown={onKeyDown}
    >
      <span><GitBranch size={14} />{node.nodeKey}</span>
      <strong>{node.title}</strong>
      <small className={`node-status status-${node.status}`}>{statusLabel(node.status)}</small>
    </button>
  );
}
