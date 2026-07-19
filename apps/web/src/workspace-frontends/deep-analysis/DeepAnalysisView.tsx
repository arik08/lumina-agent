import {
  AlertTriangle,
  Check,
  CircleAlert,
  CircleDollarSign,
  FolderDown,
  GitBranch,
  History,
  LoaderCircle,
  Menu,
  Pause,
  Pencil,
  Play,
  Plus,
  RefreshCw,
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

import { api, ApiError } from "../../api";
import { MarkdownResponse } from "../../components/ConversationTurn";
import { useCachedViewState } from "../../view-data-cache";
import type {
  DeepAnalysisMissionDetail,
  DeepAnalysisMissionEvent,
  DeepAnalysisMissionCosts,
  DeepAnalysisMissionSummary,
  DeepAnalysisWorkflowNode,
  DeepAnalysisWorkflowRevision,
} from "../../api-types";
import "./deep-analysis.css";

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
const workflowNodeWidth = 176;
const workflowNodeHeight = 86;
const workflowLayerTop = 160;
const workflowLayerGap = 74;
const workflowSiblingGap = 36;
const defaultInspectorWidth = 760;
const minimumInspectorWidth = 420;
const maximumInspectorWidth = 1040;
const inspectorWidthStorageKey = "lumina:deep-analysis:inspector-width:v2";
const workflowPortSides = ["north", "east", "south", "west"] as const;
type WorkflowPortSide = typeof workflowPortSides[number];
function statusLabel(status: string) {
  return statusLabels[status] ?? status;
}

function normalizeUtcDateTime(value: string) {
  return /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
}

function formatNodeElapsedTime(startedAt: string, now: number) {
  const startedAtMs = Date.parse(normalizeUtcDateTime(startedAt));
  if (!Number.isFinite(startedAtMs)) return null;
  const totalSeconds = Math.max(0, Math.floor((now - startedAtMs) / 1_000));
  if (totalSeconds < 60) return `${totalSeconds}초째`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) return `${totalMinutes}분 ${totalSeconds % 60}초째`;
  return `${Math.floor(totalMinutes / 60)}시간 ${totalMinutes % 60}분째`;
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

function arrangeWorkflowTopDown(workflow: DeepAnalysisWorkflowRevision) {
  const nodeByKey = new Map(workflow.nodes.map((node) => [node.nodeKey, node]));
  const outgoing = new Map<string, string[]>();
  const incomingCount = new Map(workflow.nodes.map((node) => [node.nodeKey, 0]));
  for (const edge of workflow.edges) {
    if (!nodeByKey.has(edge.sourceNodeKey) || !nodeByKey.has(edge.targetNodeKey)) continue;
    outgoing.set(edge.sourceNodeKey, [...(outgoing.get(edge.sourceNodeKey) ?? []), edge.targetNodeKey]);
    incomingCount.set(edge.targetNodeKey, (incomingCount.get(edge.targetNodeKey) ?? 0) + 1);
  }

  const compareNodes = (leftKey: string, rightKey: string) => {
    const left = nodeByKey.get(leftKey);
    const right = nodeByKey.get(rightKey);
    return (left?.positionY ?? 0) - (right?.positionY ?? 0)
      || (left?.positionX ?? 0) - (right?.positionX ?? 0)
      || leftKey.localeCompare(rightKey);
  };
  const queue = workflow.nodes
    .filter((node) => (incomingCount.get(node.nodeKey) ?? 0) === 0)
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
    if (visited.has(node.nodeKey)) continue;
    fallbackDepth += 1;
    depth.set(node.nodeKey, fallbackDepth);
  }
  const layers = new Map<number, DeepAnalysisWorkflowNode[]>();
  for (const node of workflow.nodes) {
    const nodeDepth = depth.get(node.nodeKey) ?? 0;
    layers.set(nodeDepth, [...(layers.get(nodeDepth) ?? []), node]);
  }
  for (const nodes of layers.values()) {
    nodes.sort((left, right) => compareNodes(left.nodeKey, right.nodeKey));
  }
  const maximumLayerWidth = Math.max(
    workflowNodeWidth,
    ...[...layers.values()].map(
      (nodes) => nodes.length * workflowNodeWidth + Math.max(0, nodes.length - 1) * workflowSiblingGap,
    ),
  );

  return {
    ...workflow,
    nodes: workflow.nodes.map((node) => {
      const nodeDepth = depth.get(node.nodeKey) ?? 0;
      const layer = layers.get(nodeDepth) ?? [node];
      const column = layer.findIndex((item) => item.nodeKey === node.nodeKey);
      const layerWidth = layer.length * workflowNodeWidth
        + Math.max(0, layer.length - 1) * workflowSiblingGap;
      return {
        ...node,
        positionX: 48 + (maximumLayerWidth - layerWidth) / 2
          + column * (workflowNodeWidth + workflowSiblingGap),
        positionY: workflowLayerTop + nodeDepth * (workflowNodeHeight + workflowLayerGap),
      };
    }),
  };
}

function workflowPortPoint(node: DeepAnalysisWorkflowNode, side: WorkflowPortSide) {
  if (side === "north") return { x: node.positionX + workflowNodeWidth / 2, y: node.positionY };
  if (side === "east") return { x: node.positionX + workflowNodeWidth, y: node.positionY + workflowNodeHeight / 2 };
  if (side === "south") return { x: node.positionX + workflowNodeWidth / 2, y: node.positionY + workflowNodeHeight };
  return { x: node.positionX, y: node.positionY + workflowNodeHeight / 2 };
}

function workflowPortVector(side: WorkflowPortSide) {
  if (side === "north") return { x: 0, y: -1 };
  if (side === "east") return { x: 1, y: 0 };
  if (side === "south") return { x: 0, y: 1 };
  return { x: -1, y: 0 };
}

function workflowEdgeSides(
  source: DeepAnalysisWorkflowNode,
  target: DeepAnalysisWorkflowNode,
): [WorkflowPortSide, WorkflowPortSide] {
  const deltaX = target.positionX - source.positionX;
  const deltaY = target.positionY - source.positionY;
  if (Math.abs(deltaX) > Math.abs(deltaY) * 1.8) {
    return deltaX >= 0 ? ["east", "west"] : ["west", "east"];
  }
  return deltaY >= 0 ? ["south", "north"] : ["north", "south"];
}

function workflowEdgeGeometry(
  source: DeepAnalysisWorkflowNode,
  target: DeepAnalysisWorkflowNode,
) {
  const [sourceSide, targetSide] = workflowEdgeSides(source, target);
  const sourcePoint = workflowPortPoint(source, sourceSide);
  const targetPoint = workflowPortPoint(target, targetSide);
  const sourceVector = workflowPortVector(sourceSide);
  const targetVector = workflowPortVector(targetSide);
  const vertical = sourceSide === "north" || sourceSide === "south";
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
    (vertical
      ? Math.abs(targetStem.y - sourceStem.y)
      : Math.abs(targetStem.x - sourceStem.x)) * .5,
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
  };
  return { nodeKey, label: labels[event.type] ?? event.type.replaceAll("_", " ") };
}

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
  onOpenNavigation,
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
  const [missionEvents, setMissionEvents] = useCachedViewState<DeepAnalysisMissionEvent[]>(
    `deep-analysis:${cacheScope}:events`,
    [],
  );
  const [selectedNodeKey, setSelectedNodeKey] = useCachedViewState<string | null>(
    `deep-analysis:${cacheScope}:selected-node`,
    null,
  );
  const [loadingList, setLoadingList] = useState(false);
  const [loadingMission, setLoadingMission] = useState(false);
  const [creating, setCreating] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [objective, setObjective] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [costDetailsOpen, setCostDetailsOpen] = useState(false);
  const [costDetails, setCostDetails] = useState<DeepAnalysisMissionCosts | null>(null);
  const [usdKrwRate, setUsdKrwRate] = useState<number | null>(null);
  const [loadingCosts, setLoadingCosts] = useState(false);
  const [startingMission, setStartingMission] = useState(false);
  const [cancellingMission, setCancellingMission] = useState(false);
  const [pausingMission, setPausingMission] = useState(false);
  const [retryingNodeKey, setRetryingNodeKey] = useState<string | null>(null);
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
  ].includes(mission?.status ?? "");
  const [connectionDraft, setConnectionDraft] = useState<{
    sourceNodeKey: string;
    sourceSide: WorkflowPortSide;
    pointerX: number;
    pointerY: number;
  } | null>(null);
  const [suppressedConnectionPortNodeKey, setSuppressedConnectionPortNodeKey] = useState<string | null>(null);
  const canvasViewportRef = useRef<HTMLDivElement>(null);
  const workflowLayoutRef = useRef<HTMLDivElement>(null);
  const createTitleRef = useRef<HTMLInputElement>(null);
  const workflowRegenerateTriggerRef = useRef<HTMLButtonElement>(null);
  const workflowRegenerateFontSize = workflowRegenerateTriggerRef.current
    ?.closest<HTMLElement>(".app-shell")
    ?.style.getPropertyValue("--conversation-font-size");
  const eventCursorRef = useRef(0);
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
  const connectionDragRef = useRef<{
    pointerId: number;
    sourceNodeKey: string;
    clientX: number;
    clientY: number;
    moved: boolean;
  } | null>(null);
  useEffect(() => {
    setExportedFolderPath(null);
    setWorkflowRegenerateOpen(false);
    setWorkflowRegeneratePrompt("");
  }, [mission?.id]);

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
      const available = workflowLayoutRef.current?.getBoundingClientRect().width ?? window.innerWidth;
      const maximum = Math.min(maximumInspectorWidth, Math.max(minimumInspectorWidth, available * 0.68));
      setInspectorWidth((current) => Math.round(Math.min(Math.max(minimumInspectorWidth, current), maximum)));
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
    if (createRequest <= 0) return;
    setCreateOpen(true);
    onCreateRequestHandled();
  }, [createRequest, onCreateRequestHandled]);
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
      setMissionEvents([]);
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
        setMissionEvents([]);
        setSelectedNodeKey(detail.workflow.nodes[0]?.nodeKey ?? null);
        setCostDetailsOpen(false);
        setDeleteArmed(false);
        setWorkflowDraft(null);
        setWorkflowDraftDirty(false);
        setEditingWorkflow(false);
        setMission(detail);
        void api.deepAnalysis.listEvents(detail.id, 0, controller.signal)
          .then(setMissionEvents)
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
  }, [projectId, selectedMissionId]);

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
    if (
      !selectedMissionId
      || !mission
      || mission.id !== selectedMissionId
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
          setMissionEvents((current) => [...current, ...events]);
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
  }, [mission?.id, mission?.status, selectedMissionId]);

  const rawWorkflow = workflowDraft ?? mission?.workflow ?? null;
  const shownWorkflow = useMemo(
    () => rawWorkflow && !editingWorkflow ? arrangeWorkflowTopDown(rawWorkflow) : rawWorkflow,
    [editingWorkflow, rawWorkflow],
  );
  const workflowCanvasSize = useMemo(() => ({
    width: Math.max(
      720,
      ...(shownWorkflow?.nodes ?? []).map((node) => node.positionX + workflowNodeWidth + 48),
    ),
    height: Math.max(
      540,
      ...(shownWorkflow?.nodes ?? []).map((node) => node.positionY + workflowNodeHeight + 48),
    ),
  }), [shownWorkflow?.nodes]);
  const selectedNode = useMemo(
    () => shownWorkflow?.nodes.find((node) => node.nodeKey === selectedNodeKey) ?? null,
    [shownWorkflow, selectedNodeKey],
  );

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
        : missionEvents.length ? `기록 ${missionEvents.length}개` : "기록 대기";

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

  function fitNodesToViewport(nodes: DeepAnalysisWorkflowNode[]) {
    const viewport = canvasViewportRef.current;
    if (!viewport || !nodes.length) return;
    const availableHeight = viewport.clientHeight;

    const padding = 36;
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
          (availableHeight - padding * 2) / contentHeight,
        ),
      ),
    );
    setCanvasScale(fittedScale);
    setCanvasOffset({
      x: (viewport.clientWidth - contentWidth * fittedScale) / 2 - minX * fittedScale,
      y: (availableHeight - contentHeight * fittedScale) / 2 - minY * fittedScale,
    });
  }

  function fitCanvasToViewport() {
    fitNodesToViewport(shownWorkflow?.nodes ?? []);
  }

  function closeNodeInspectorAndFit() {
    setSelectedNodeKey(null);
    window.requestAnimationFrame(() => window.requestAnimationFrame(fitCanvasToViewport));
  }

  function clampInspectorWidth(value: number) {
    const available = workflowLayoutRef.current?.getBoundingClientRect().width ?? window.innerWidth;
    const maximum = Math.min(maximumInspectorWidth, Math.max(minimumInspectorWidth, available * 0.68));
    return Math.round(Math.min(Math.max(minimumInspectorWidth, value), maximum));
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
      const arranged = arrangeWorkflowTopDown(draft);
      setWorkflowDraft(arranged);
      setWorkflowDraftDirty(true);
      setEditingWorkflow(true);
      setSelectedNodeKey(null);
      window.requestAnimationFrame(() => fitNodesToViewport(arranged.nodes));
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
    if (drag.moved) setSuppressedConnectionPortNodeKey(drag.nodeKey);
    setSelectedNodeKey(drag.nodeKey);
  }

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
    if (!lastAddedNode) {
      while (workflowDraft.nodes.some(
        (node) => Math.abs(node.positionX - positionX) < workflowNodeWidth + 24
          && Math.abs(node.positionY - positionY) < 110,
      )) {
        positionY += verticalPlacementStep;
      }
    }
    setCanvasOffset({
      x: viewport.clientWidth / 2 - (positionX + workflowNodeWidth / 2) * canvasScale,
      y: viewport.clientHeight / 2 - (positionY + 43) * canvasScale,
    });
    const node: DeepAnalysisWorkflowNode = {
      ...workflowDraft.nodes[0],
      id: `draft:${nodeKey}`,
      nodeKey,
      nodeType: "research",
      title: "새 분석 단계",
      purpose: "이 단계에서 확인할 질문과 산출물을 정의해 주세요.",
      status: "planned",
      sequence: workflowDraft.nodes.length + 1,
      positionX,
      positionY,
      config: {}, runId: null, outputProjectFileId: null, outputLogicalPath: null,
      outputSummary: "", outputMarkdown: "", generatedFiles: [], runHistory: [],
      runStatus: null, executionPrompt: null, liveOutput: "", errorMessage: null, actualCostMicrousd: 0,
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
    workflowUndoStackRef.current.push({
      draft: workflowDraft,
      dirty: workflowDraftDirty,
      selectedNodeKey,
      selectedEdgeId,
    });
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
    setCreating(true);
    setError(null);
    try {
      const created = await api.deepAnalysis.createMission(projectId, {
        title: title.trim(),
        objective: objective.trim(),
        autonomyMode: "balanced",
      });
      setMissions((current) => [created, ...current]);
      setSelectedMissionId(created.id);
      setMission(created);
      setSelectedNodeKey(created.workflow.nodes[0]?.nodeKey ?? null);
      setTitle("");
      setObjective("");
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
          <span>장기 분석을 Workflow 단위로 기록하고 이어갑니다.</span>
        </div>
        {activeTabSummary && <span className="deep-analysis-header-summary" role="status">{activeTabSummary}</span>}
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
                <div className="deep-analysis-tabs" role="tablist" aria-label="새 심층분석 화면">
                  <button className="is-active" type="button" role="tab" aria-selected="true"><GitBranch size={14} />Workflow</button>
                  <button type="button" role="tab" aria-selected="false" disabled><History size={14} />실행 기록</button>
                </div>
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
                    aria-valuemax={maximumInspectorWidth}
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
                      <button
                        className="deep-analysis-create-submit"
                        type="submit"
                        aria-busy={creating}
                        disabled={creating || !title.trim()}
                      >
                        {creating && <LoaderCircle className="is-running" size={14} />}
                        {creating ? "Workflow 설계 중..." : "Workflow 자동 만들기"}
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
                        disabled={startingMission || savingWorkflow || activatingWorkflow || !mission.executionAvailable}
                        data-tooltip={!mission.executionAvailable ? "실제 분석 실행기가 연결된 후 시작할 수 있습니다." : undefined}
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
                    <div className="deep-analysis-cost-wrap">
                      <button
                        className="deep-analysis-cost tooltip-control"
                        type="button"
                        aria-label={`누적 비용 ${formatCost(mission.spentMicrousd, usdKrwRate)}`}
                        aria-expanded={costDetailsOpen}
                        data-tooltip={`누적 비용 ${formatCost(mission.spentMicrousd, usdKrwRate)}`}
                        onClick={() => setCostDetailsOpen((open) => !open)}
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
                <div className="deep-analysis-tabs" role="tablist" aria-label="심층분석 화면">
                  <button className={activeTab === "workflow" ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === "workflow"} onClick={() => setActiveTab("workflow")}><GitBranch size={14} />Workflow</button>
                  <button className={activeTab === "log" ? "is-active" : ""} type="button" role="tab" aria-selected={activeTab === "log"} onClick={() => setActiveTab("log")}><History size={14} />실행 기록</button>
                </div>
                {activeTab === "workflow" ? <>
                <div
                  ref={workflowLayoutRef}
                  className={`deep-analysis-workflow-layout ${selectedNode ? "has-inspector" : ""}`}
                  style={{ "--deep-analysis-inspector-width": `${inspectorWidth}px` } as CSSProperties}
                >
                  <div className="deep-analysis-workflow-main">
                {mission.status === "running" && (
                  <div className="deep-analysis-run-feedback is-active" role="status">
                    <LoaderCircle className="is-running" size={16} />
                    <div>
                      <strong>{activeNode ? `${activeNode.nodeKey} · ${activeNode.title} 실행 중` : "분석 작업 실행 중"}</strong>
                      <span>{activeNode?.runId
                        ? `실제 Lumina Run ${activeNode.runStatus ? `· ${statusLabel(activeNode.runStatus)}` : ""} · ${completedNodeCount}/${mission.workflow.nodes.length} Node 완료`
                        : "실행 Run을 준비하고 있습니다."}</span>
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
                      closeNodeInspectorAndFit();
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
                        {(shownWorkflow?.edges ?? []).map((edge) => {
                          const source = shownWorkflow?.nodes.find((node) => node.nodeKey === edge.sourceNodeKey);
                          const target = shownWorkflow?.nodes.find((node) => node.nodeKey === edge.targetNodeKey);
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
                                    setSelectedNodeKey(null);
                                  }}
                                />
                              )}
                            </g>
                          );
                        })}
                        {connectionDraft && (() => {
                          const source = shownWorkflow?.nodes.find((node) => node.nodeKey === connectionDraft.sourceNodeKey);
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
                          onSelect={() => {
                            setSelectedNodeKey(node.nodeKey);
                            setSelectedEdgeId(null);
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
                      {editingWorkflow && selectedEdgeId && (() => {
                        const edge = shownWorkflow?.edges.find((item) => item.id === selectedEdgeId);
                        const source = shownWorkflow?.nodes.find((node) => node.nodeKey === edge?.sourceNodeKey);
                        const target = shownWorkflow?.nodes.find((node) => node.nodeKey === edge?.targetNodeKey);
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
                          const source = shownWorkflow?.nodes.find((node) => node.nodeKey === edge.sourceNodeKey);
                          const target = shownWorkflow?.nodes.find((node) => node.nodeKey === edge.targetNodeKey);
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
                    <div className="deep-analysis-canvas-controls" aria-label="Workflow 조작">
                      <div className="deep-analysis-canvas-edit-controls" aria-label="Node 편집">
                        <button
                          className={editingWorkflow ? "is-active" : undefined}
                          type="button"
                          aria-label={editingWorkflow ? "편집 종료" : "노드 편집"}
                          data-tooltip={editingWorkflow ? "편집 종료" : "노드 편집"}
                          disabled={!canEdit || (mission.status !== "draft" && mission.status !== "ready") || savingWorkflow || activatingWorkflow}
                          onClick={() => void (editingWorkflow ? activateWorkflowDraft() : beginWorkflowEdit())}
                        >
                          {savingWorkflow || activatingWorkflow ? <LoaderCircle className="is-running" size={14} /> : <Pencil size={14} />}
                        </button>
                        <button type="button" aria-label="Node 추가" data-tooltip="Node 추가" disabled={!editingWorkflow || !workflowDraft} onClick={addDraftNode}><Plus size={14} /></button>
                        <button type="button" aria-label="Node 자동 정렬" data-tooltip="Node 자동 정렬" disabled={arrangingWorkflow || !canEdit || (mission.status !== "draft" && mission.status !== "ready")} onClick={() => void autoArrangeWorkflow()}>{arrangingWorkflow ? <LoaderCircle className="is-running" size={14} /> : <WandSparkles size={14} />}</button>
                        <button type="button" aria-label="되돌리기" data-tooltip="되돌리기 (Ctrl+Z)" disabled={!editingWorkflow || workflowUndoStackRef.current.length === 0} onClick={() => undoWorkflowChange()}><Undo2 size={14} /></button>
                        <button type="button" aria-label="Node 지우기" data-tooltip="Node 지우기" disabled={!editingWorkflow || !selectedNode || workflowDraft?.nodes.length === 1} onClick={() => selectedNode && removeDraftNode(selectedNode.nodeKey)}><Trash2 size={14} /></button>
                      </div>
                      <div className="deep-analysis-workflow-regenerate-control">
                      <button
                        ref={workflowRegenerateTriggerRef}
                        className={workflowRegenerateOpen ? "deep-analysis-workflow-regenerate-trigger is-active" : "deep-analysis-workflow-regenerate-trigger"}
                        type="button"
                        aria-label="workflow 재생성"
                        aria-expanded={workflowRegenerateOpen}
                        data-tooltip="workflow 재생성"
                        disabled={!canEdit || editingWorkflow || regeneratingWorkflow || ["running", "paused", "awaiting_input"].includes(mission.status)}
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
                      <div className="deep-analysis-canvas-zoom-controls" aria-label="확대 및 축소">
                        <button type="button" aria-label="확대" data-tooltip="확대" disabled={canvasScale >= maximumCanvasScale} onClick={() => updateCanvasScale(canvasScale + 0.1)}><ZoomIn size={14} /></button>
                        <button type="button" aria-label="배율 초기화" onClick={() => updateCanvasScale(1)}>{Math.round(canvasScale * 100)}%</button>
                        <button type="button" aria-label="축소" data-tooltip="축소" disabled={canvasScale <= minimumCanvasScale} onClick={() => updateCanvasScale(canvasScale - 0.1)}><ZoomOut size={14} /></button>
                      </div>
                    </div>
                  </div>
                  </div>
                  {selectedNode && (
                    <div
                      className="deep-analysis-inspector-resizer"
                      role="separator"
                      aria-label="우측 상세 패널 폭 조절"
                      aria-orientation="vertical"
                      aria-valuemin={minimumInspectorWidth}
                      aria-valuemax={maximumInspectorWidth}
                      aria-valuenow={inspectorWidth}
                      tabIndex={0}
                      onPointerDown={beginInspectorResize}
                      onKeyDown={resizeInspectorWithKeyboard}
                    />
                  )}
                  {selectedNode && (
                    <aside className="deep-analysis-inspector" aria-label={`${selectedNode.title} 상세 정보`}>
                      <header>
                        <div>
                          <span>{selectedNode.nodeKey}</span>
                          <small className={`node-status status-${selectedNode.status}`}>{statusLabel(selectedNode.status)}</small>
                          <button type="button" aria-label="노드 상세 닫기" onClick={closeNodeInspectorAndFit}><X size={14} /></button>
                        </div>
                        <strong>{selectedNode.title}</strong>
                      </header>
                      <section>
                        <h3>작업 프롬프트</h3>
                        {editingWorkflow && workflowDraft ? <>
                          <label className="deep-analysis-node-edit-field">이름<input value={selectedNode.title} onChange={(event) => {
                            setWorkflowDraft({ ...workflowDraft, nodes: workflowDraft.nodes.map((node) => node.nodeKey === selectedNode.nodeKey ? { ...node, title: event.target.value } : node) });
                            setWorkflowDraftDirty(true);
                          }} /></label>
                          <label className="deep-analysis-node-edit-field">프롬프트<textarea rows={6} value={selectedNode.purpose} onChange={(event) => {
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
                      <section>
                        <h3>출력</h3>
                        {selectedNode.outputLogicalPath && (
                          <small className="deep-analysis-output-path">{selectedNode.outputLogicalPath}</small>
                        )}
                        {selectedNode.status === "running" && !selectedNode.outputSummary ? (
                          <>
                            <p className="deep-analysis-node-progress"><LoaderCircle className="is-running" size={13} /> 모델 응답을 생성하고 있습니다.</p>
                            {selectedNode.liveOutput && (
                              <pre className="deep-analysis-live-output">{selectedNode.liveOutput}</pre>
                            )}
                          </>
                        ) : selectedNode.errorMessage ? (
                          <p className="deep-analysis-node-error">{selectedNode.errorMessage}</p>
                        ) : selectedNode.outputMarkdown ? (
                          <article className="deep-analysis-output-document">
                            <MarkdownResponse text={selectedNode.outputMarkdown} />
                          </article>
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
                  <ExecutionLog events={missionEvents} />
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

function ExecutionLog({ events }: { events: DeepAnalysisMissionEvent[] }) {
  return (
    <section className="deep-analysis-log-view" aria-label="실행 기록">
      <header>
        <div><strong>실행 기록</strong><span>Mission과 Node의 실행 기록을 최신순으로 확인합니다.</span></div>
      </header>
      <div className="deep-analysis-log-rows" role="log" aria-live="polite">
        {events.length ? events.slice().reverse().map((event) => {
          const description = eventDescription(event);
          const isError = event.type.includes("failed") || event.type.includes("error");
          return (
            <div key={event.sequence} className={`is-${event.type}${isError ? " is-error" : ""}`}>
              <time dateTime={event.createdAt}>{new Date(event.createdAt).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time>
              <i aria-hidden="true" />
              <span>{description.nodeKey && <b>{description.nodeKey}</b>}{description.label}</span>
            </div>
          );
        }) : (
          <div className="deep-analysis-log-empty"><strong>아직 실행 기록이 없습니다.</strong><span>Mission을 실행하면 Node 대기·시작·출력·완료 기록이 여기에 표시됩니다.</span></div>
        )}
      </div>
    </section>
  );
}

function WorkflowNodeButton({
  node,
  selected,
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
  const [clockNow, setClockNow] = useState(() => Date.now());
  useEffect(() => {
    if (node.status !== "running" || !node.startedAt) return undefined;
    setClockNow(Date.now());
    const timer = window.setInterval(() => setClockNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [node.startedAt, node.status]);
  const normalizedStartedAt = node.startedAt ? normalizeUtcDateTime(node.startedAt) : null;
  const elapsedTime = node.status === "running" && node.startedAt
    ? formatNodeElapsedTime(node.startedAt, clockNow)
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
            {statusLabel(node.status)}
            {elapsedTime && <> · <time className="deep-analysis-node-elapsed" dateTime={normalizedStartedAt ?? undefined}>{elapsedTime}</time></>}
          </small>
        </div>
        <strong>{node.title}</strong>
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
