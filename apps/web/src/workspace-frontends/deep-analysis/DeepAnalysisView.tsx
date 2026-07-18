import {
  AlertTriangle,
  ChevronRight,
  CircleAlert,
  CircleDollarSign,
  GitBranch,
  LoaderCircle,
  Menu,
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
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { api, ApiError } from "../../api";
import type {
  DeepAnalysisAutonomyMode,
  DeepAnalysisCompletionContract,
  DeepAnalysisMissionCharter,
  DeepAnalysisMissionDetail,
  DeepAnalysisMissionSummary,
  DeepAnalysisWorkflowNode,
} from "../../api-types";
import "./deep-analysis.css";

interface DeepAnalysisViewProps {
  projectId: string | null;
  canEdit: boolean;
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

const workflowActionLabels: Record<string, string> = {
  initial: "질문 기반 초기 Workflow",
  legacy_upgraded: "질문 기반 Workflow로 승격",
  question_updated: "질문 변경으로 재구성",
  expand: "분석 단계 확장",
  shrink: "불필요 단계 축소",
  replace: "분석 단계 교체",
  finish: "조기 합성 전환",
};

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

export function DeepAnalysisView({
  projectId,
  canEdit,
  onOpenNavigation,
}: DeepAnalysisViewProps) {
  const [missions, setMissions] = useState<DeepAnalysisMissionSummary[]>([]);
  const [selectedMissionId, setSelectedMissionId] = useState<string | null>(null);
  const [mission, setMission] = useState<DeepAnalysisMissionDetail | null>(null);
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
  const [error, setError] = useState<string | null>(null);
  const [costDetailsOpen, setCostDetailsOpen] = useState(false);
  const [startingMission, setStartingMission] = useState(false);
  const [cancellingMission, setCancellingMission] = useState(false);
  const [retryingNodeKey, setRetryingNodeKey] = useState<string | null>(null);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deletingMission, setDeletingMission] = useState(false);
  const [decisionOptionId, setDecisionOptionId] = useState("");
  const [decisionAnswerText, setDecisionAnswerText] = useState("");
  const [answeringDecision, setAnsweringDecision] = useState(false);
  const [contractOpen, setContractOpen] = useState(false);
  const [savingContract, setSavingContract] = useState(false);
  const [runningQualityGate, setRunningQualityGate] = useState(false);
  const [charterDraft, setCharterDraft] = useState<DeepAnalysisMissionCharter | null>(null);
  const [completionDraft, setCompletionDraft] = useState<DeepAnalysisCompletionContract | null>(null);
  const [canvasScale, setCanvasScale] = useState(1);
  const [canvasOffset, setCanvasOffset] = useState({ x: 0, y: 0 });
  const [canvasPanning, setCanvasPanning] = useState(false);
  const canvasViewportRef = useRef<HTMLDivElement>(null);
  const canvasPanRef = useRef<{
    pointerId: number;
    clientX: number;
    clientY: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);

  useEffect(() => {
    setMissions([]);
    setMission(null);
    setSelectedMissionId(null);
    setSelectedNodeKey(null);
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
    return () => controller.abort();
  }, [projectId]);

  useEffect(() => {
    setMission(null);
    setSelectedNodeKey(null);
    setCostDetailsOpen(false);
    setDeleteArmed(false);
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
        setMission(detail);
        setSelectedNodeKey(detail.workflow.nodes[0]?.nodeKey ?? null);
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
    if (!selectedMissionId || mission?.status !== "running") return;
    let active = true;
    const refresh = () => {
      void api.deepAnalysis.getMission(selectedMissionId).then((detail) => {
        if (!active) return;
        setMission(detail);
        setMissions((current) =>
          current.map((item) => (item.id === detail.id ? detail : item)),
        );
      }).catch(() => {
        // A transient polling failure must not hide the last durable snapshot.
      });
    };
    const timer = window.setInterval(refresh, 1_500);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [mission?.status, selectedMissionId]);

  const selectedNode = useMemo(
    () => mission?.workflow.nodes.find((node) => node.nodeKey === selectedNodeKey) ?? null,
    [mission, selectedNodeKey],
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
  const latestGraphChange = useMemo(
    () => mission?.workflow.changeLog
      .slice()
      .reverse()
      .find((item) => item.graphChanged) ?? null,
    [mission],
  );
  const latestQualityGate = useMemo(
    () => mission?.qualityGates.at(-1) ?? null,
    [mission?.qualityGates],
  );
  const workflowTopology = useMemo(() => {
    const outgoing = new Map<string, number>();
    const incoming = new Map<string, number>();
    for (const edge of mission?.workflow.edges ?? []) {
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
  }, [mission?.workflow.edges]);

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
    setCharterDraft(mission.charter);
    setCompletionDraft(mission.completionContract);
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
    const nodes = mission?.workflow.nodes ?? [];
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
    if (!mission?.workflow.graphDigest) return;
    const frame = window.requestAnimationFrame(() => fitCanvasToViewport());
    return () => window.cancelAnimationFrame(frame);
  }, [mission?.workflow.graphDigest]);

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
      });
      setMissions((current) => [created, ...current]);
      setSelectedMissionId(created.id);
      setMission(created);
      setSelectedNodeKey(created.workflow.nodes[0]?.nodeKey ?? null);
      setTitle("");
      setObjective("");
      setAutonomyMode("balanced");
      setBudgetUsd("");
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
        {canEdit && projectId && (
          <button type="button" onClick={() => setCreateOpen((open) => !open)}>
            {createOpen ? <X size={15} /> : <Plus size={15} />}
            {createOpen ? "닫기" : "새 분석"}
          </button>
        )}
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
          <aside className="deep-analysis-missions" aria-label="심층분석 목록">
            <div className="deep-analysis-pane-title">
              <strong>Mission</strong>
              <span>{missions.length}</span>
            </div>
            {createOpen && (
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
            )}
            {loadingList ? (
              <div className="deep-analysis-loading"><LoaderCircle className="is-running" size={16} /> 불러오는 중</div>
            ) : missions.length ? (
              <div className="deep-analysis-mission-list">
                {missions.map((item) => (
                  <button
                    className={selectedMissionId === item.id ? "is-active" : ""}
                    type="button"
                    key={item.id}
                    aria-current={selectedMissionId === item.id ? "page" : undefined}
                    onClick={() => setSelectedMissionId(item.id)}
                  >
                    <span><strong>{item.title}</strong><small>{item.objective || "목적 미입력"}</small></span>
                    <ChevronRight size={14} />
                  </button>
                ))}
              </div>
            ) : !createOpen ? (
              <div className="deep-analysis-list-empty">
                <p>아직 심층분석이 없습니다.</p>
                {canEdit && <button type="button" onClick={() => setCreateOpen(true)}><Plus size={14} /> 첫 분석 만들기</button>}
              </div>
            ) : null}
          </aside>

          <section className="deep-analysis-workspace">
            {loadingMission ? (
              <div className="deep-analysis-empty"><LoaderCircle className="is-running" size={20} /><p>Workflow를 불러오는 중입니다.</p></div>
            ) : mission ? (
              <>
                <header className="deep-analysis-mission-header">
                  <div>
                    <span className={`deep-analysis-status status-${mission.status}`}>{statusLabel(mission.status)}</span>
                    <h2>{mission.title}</h2>
                    <p>{mission.objective || "분석 목적이 아직 입력되지 않았습니다."}</p>
                  </div>
                  <div className="deep-analysis-mission-actions">
                    {canEdit && (mission.status === "draft" || mission.status === "ready") && (
                      <button
                        className={`deep-analysis-start ${!mission.executionAvailable ? "is-unavailable" : ""}`}
                        type="button"
                        disabled={startingMission || !mission.executionAvailable}
                        data-tooltip={!mission.executionAvailable ? "실제 분석 실행기가 연결된 후 시작할 수 있습니다." : undefined}
                        onClick={() => void startMission()}
                      >
                        {startingMission ? <LoaderCircle className="is-running" size={15} /> : <Play size={15} />}
                        {startingMission ? "시작 중" : mission.executionAvailable ? "Workflow 시작" : "실행 엔진 준비 중"}
                      </button>
                    )}
                    {canEdit && (mission.status === "running" || mission.status === "awaiting_input") && (
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
                      onClick={() => setContractOpen((open) => !open)}
                    >
                      Mission 계약
                    </button>
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
                          <strong>노드별 비용</strong>
                          {mission.budgetMicrousd !== null && (
                            <span className="is-budget"><em>설정 한도</em><b>{formatCost(mission.budgetMicrousd)}</b></span>
                          )}
                          {mission.workflow.nodes.map((node) => (
                            <span key={node.id}><em>{node.nodeKey} · {node.title}</em><b>{formatCost(node.actualCostMicrousd)}</b></span>
                          ))}
                        </div>
                      )}
                    </div>
                    {canEdit && (
                      <button
                        className={`deep-analysis-delete ${deleteArmed ? "is-armed" : ""}`}
                        type="button"
                        aria-label={deleteArmed ? "심층분석 삭제 확인, 한 번 더 누르면 삭제" : "심층분석 삭제"}
                        data-tooltip={mission.status === "running" || mission.status === "awaiting_input" ? "먼저 실행을 중단해 주세요." : deleteArmed ? "한 번 더 눌러 삭제" : "삭제"}
                        disabled={deletingMission || mission.status === "running" || mission.status === "awaiting_input"}
                        onClick={() => void deleteMission()}
                      >
                        {deletingMission ? <LoaderCircle className="is-running" size={14} /> : deleteArmed ? <AlertTriangle size={14} /> : <Trash2 size={14} />}
                        {deleteArmed ? "한 번 더 눌러 삭제" : "삭제"}
                      </button>
                    )}
                  </div>
                </header>
                <div className="deep-analysis-tabs" role="tablist" aria-label="심층분석 화면">
                  <button className="is-active" type="button" role="tab" aria-selected="true">Workflow</button>
                  <span>
                    {completedNodeCount}/{mission.workflow.nodes.length} 완료 · 분기 {workflowTopology.branchCount} · 합류 {workflowTopology.mergeCount} · 입력 자료 {mission.sourceManifest.length}개 · Revision {mission.workflow.revisionNumber}
                  </span>
                </div>
                {contractOpen && charterDraft && completionDraft && (
                  <section className="deep-analysis-contract" aria-label="Mission Charter와 완료 조건">
                    <div className="deep-analysis-contract-grid">
                      <div>
                        <strong>Mission Charter</strong>
                        <label>목적<textarea rows={2} value={charterDraft.purpose} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, purpose: event.target.value })} /></label>
                        <label>반드시 답할 핵심 질문<textarea rows={3} value={charterDraft.keyQuestions.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, keyQuestions: splitContractLines(event.target.value) })} /></label>
                        <label>필수 산출물<textarea rows={2} value={charterDraft.deliverables.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, deliverables: splitContractLines(event.target.value) })} /></label>
                        <label>독자<input value={charterDraft.audience} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, audience: event.target.value })} /></label>
                      </div>
                      <div>
                        <strong>범위와 기준</strong>
                        <label>포함 범위<textarea rows={2} value={charterDraft.inScope.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, inScope: splitContractLines(event.target.value) })} /></label>
                        <label>제외 범위<textarea rows={2} value={charterDraft.outOfScope.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, outOfScope: splitContractLines(event.target.value) })} /></label>
                        <label>비교 기준·기간·단위<textarea rows={2} value={charterDraft.comparisonBasis} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, comparisonBasis: event.target.value })} /></label>
                        <label>품질 기준<textarea rows={2} value={charterDraft.qualityStandards.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCharterDraft({ ...charterDraft, qualityStandards: splitContractLines(event.target.value) })} /></label>
                      </div>
                      <div>
                        <strong>Completion Contract</strong>
                        <label>보고서 필수 섹션<textarea rows={2} value={completionDraft.requiredSections.join("\n")} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCompletionDraft({ ...completionDraft, requiredSections: splitContractLines(event.target.value) })} /></label>
                        <label>최소 근거 coverage (%)<input type="number" min="0" max="100" value={Math.round(completionDraft.minimumEvidenceCoverage * 100)} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCompletionDraft({ ...completionDraft, minimumEvidenceCoverage: Math.min(1, Math.max(0, Number(event.target.value) / 100)) })} /></label>
                        <label>허용 미해결 항목 수<input type="number" min="0" max="1000" value={completionDraft.maximumOpenIssues} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCompletionDraft({ ...completionDraft, maximumOpenIssues: Math.max(0, Number(event.target.value)) })} /></label>
                        <label className="deep-analysis-contract-check"><input type="checkbox" checked={completionDraft.requiresFinalReview} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCompletionDraft({ ...completionDraft, requiresFinalReview: event.target.checked })} /> 최종 사용자 검토 필요</label>
                        <label className="deep-analysis-contract-check"><input type="checkbox" checked={completionDraft.allowWaiver} disabled={mission.status !== "draft" && mission.status !== "ready"} onChange={(event) => setCompletionDraft({ ...completionDraft, allowWaiver: event.target.checked })} /> 미충족 시 명시적 예외 승인 허용</label>
                      </div>
                    </div>
                    {(mission.status === "draft" || mission.status === "ready") && canEdit && (
                      <div className="deep-analysis-contract-actions">
                        <span>실행을 시작하면 이 계약이 해당 Mission revision에 고정됩니다.</span>
                        <button type="button" disabled={savingContract || !charterDraft.purpose.trim()} onClick={() => void saveMissionContract()}>
                          {savingContract && <LoaderCircle className="is-running" size={14} />}
                          {savingContract ? "저장 중" : "계약 저장"}
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
                {latestGraphChange && (
                  <div className="deep-analysis-workflow-change" role="status">
                    <GitBranch size={15} />
                    <div>
                      <strong>{workflowActionLabels[latestGraphChange.action] ?? "Workflow 조정"}</strong>
                      <span>{latestGraphChange.reason || "중간 결과에 따라 남은 Workflow를 조정했습니다."}</span>
                    </div>
                    <small>
                      {(latestGraphChange.addedNodeKeys?.length ?? 0) > 0 && `+${latestGraphChange.addedNodeKeys?.length}`}
                      {(latestGraphChange.addedNodeKeys?.length ?? 0) > 0 && (latestGraphChange.removedNodeKeys?.length ?? 0) > 0 && " · "}
                      {(latestGraphChange.removedNodeKeys?.length ?? 0) > 0 && `−${latestGraphChange.removedNodeKeys?.length}`}
                    </small>
                  </div>
                )}
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
                        {mission.workflow.edges.map((edge) => {
                          const source = mission.workflow.nodes.find((node) => node.nodeKey === edge.sourceNodeKey);
                          const target = mission.workflow.nodes.find((node) => node.nodeKey === edge.targetNodeKey);
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
                      {mission.workflow.nodes.map((node) => (
                        <WorkflowNodeButton
                          key={node.id}
                          node={node}
                          selected={selectedNodeKey === node.nodeKey}
                          onSelect={() => setSelectedNodeKey(node.nodeKey)}
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
                        <p>{selectedNode.purpose}</p>
                        {typeof selectedNode.config.reason === "string" && (
                          <small className="deep-analysis-node-origin">
                            <GitBranch size={12} /> {selectedNode.config.reason}
                          </small>
                        )}
                      </section>
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

function WorkflowNodeButton({
  node,
  selected,
  onSelect,
}: {
  node: DeepAnalysisWorkflowNode;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      className={`deep-analysis-node ${selected ? "is-selected" : ""}`}
      style={{ left: node.positionX, top: node.positionY }}
      type="button"
      aria-pressed={selected}
      onClick={onSelect}
    >
      <span><GitBranch size={14} />{node.nodeKey}</span>
      <strong>{node.title}</strong>
      <small className={`node-status status-${node.status}`}>{statusLabel(node.status)}</small>
    </button>
  );
}
