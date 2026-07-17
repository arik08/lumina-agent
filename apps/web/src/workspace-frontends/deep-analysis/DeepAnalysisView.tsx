import {
  ChevronRight,
  CircleDollarSign,
  GitBranch,
  LoaderCircle,
  Menu,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";

import { api, ApiError } from "../../api";
import type {
  DeepAnalysisAutonomyMode,
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
  const [autonomyMode, setAutonomyMode] =
    useState<DeepAnalysisAutonomyMode>("balanced");
  const [error, setError] = useState<string | null>(null);
  const [costDetailsOpen, setCostDetailsOpen] = useState(false);

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

  const selectedNode = useMemo(
    () => mission?.workflow.nodes.find((node) => node.nodeKey === selectedNodeKey) ?? null,
    [mission, selectedNodeKey],
  );

  async function createMission(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || !title.trim()) return;
    setCreating(true);
    setError(null);
    try {
      const created = await api.deepAnalysis.createMission(projectId, {
        title: title.trim(),
        objective: objective.trim(),
        autonomyMode,
      });
      setMissions((current) => [created, ...current]);
      setSelectedMissionId(created.id);
      setMission(created);
      setSelectedNodeKey(created.workflow.nodes[0]?.nodeKey ?? null);
      setTitle("");
      setObjective("");
      setAutonomyMode("balanced");
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
                  <div className="deep-analysis-cost-wrap">
                    <button
                      className="deep-analysis-cost"
                      type="button"
                      aria-expanded={costDetailsOpen}
                      onClick={() => setCostDetailsOpen((open) => !open)}
                    >
                      <CircleDollarSign size={15} /> 누적 비용 {formatCost(mission.spentMicrousd)}
                    </button>
                    {costDetailsOpen && (
                      <div className="deep-analysis-cost-popover">
                        <strong>노드별 비용</strong>
                        {mission.workflow.nodes.map((node) => (
                          <span key={node.id}><em>{node.nodeKey} · {node.title}</em><b>{formatCost(node.actualCostMicrousd)}</b></span>
                        ))}
                      </div>
                    )}
                  </div>
                </header>
                <div className="deep-analysis-tabs" role="tablist" aria-label="심층분석 화면">
                  <button className="is-active" type="button" role="tab" aria-selected="true">Workflow</button>
                  <span>Revision {mission.workflow.revisionNumber}</span>
                </div>
                <div className="deep-analysis-workflow-layout">
                  <div className="deep-analysis-canvas-scroll">
                    <div className="deep-analysis-canvas" aria-label="Workflow 캔버스">
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
                  {selectedNode && (
                    <aside className="deep-analysis-inspector" aria-label={`${selectedNode.title} 상세 정보`}>
                      <header>
                        <div><span>{selectedNode.nodeKey}</span><button type="button" aria-label="노드 상세 닫기" onClick={() => setSelectedNodeKey(null)}><X size={14} /></button></div>
                        <strong>{selectedNode.title}</strong>
                        <small className={`node-status status-${selectedNode.status}`}>{statusLabel(selectedNode.status)}</small>
                      </header>
                      <section>
                        <h3>목적</h3>
                        <p>{selectedNode.purpose}</p>
                      </section>
                      <section>
                        <h3>출력</h3>
                        <p>{selectedNode.outputSummary || "아직 생성된 출력이 없습니다."}</p>
                      </section>
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
