import {
  AlertTriangle,
  Brain,
  Check,
  ChevronRight,
  Clock3,
  History,
  Lightbulb,
  Link2,
  LoaderCircle,
  Menu,
  Pencil,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  ShieldCheck,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { SelectMenu } from "./SelectMenu";
import { SyntaxCode } from "./SyntaxCode";
import type {
  MemoryLearningMode,
  MemorySettings,
  ProjectLearningProposal,
  ProjectLearningProposalStatus,
  ProjectMemory,
  ProjectMemoryHistory,
  ProjectSummary,
  UserMemory,
} from "../api-types";

interface MemoryViewProps {
  onOpenNavigation: () => void;
  project: ProjectSummary | null;
  completedRunId: string | null;
  canReviewProjectLearning: boolean;
}

type MemoryTab = "personal" | "project" | "proposals";
type MemoryListStatus = "all" | "active" | "pending" | "dismissed";

const editableMemoryStatusOptions = [
  { value: "active", label: "활성" },
  { value: "dismissed", label: "보류" },
];
type ProposalFilter = "all" | ProjectLearningProposalStatus;

interface MemoryDraft {
  id: string;
  category: string;
  displayText: string;
  status: "active" | "dismissed";
}

interface ProjectProposalDraft {
  mode: "new" | "modify" | "delete";
  target: ProjectMemory | null;
  category: string;
  fact: string;
  displayText: string;
  rationale: string;
}

const EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

const modeOptions: Array<{ mode: MemoryLearningMode; label: string; description: string }> = [
  { mode: "auto", label: "자동 저장", description: "안정된 개인 선호를 자동으로 기억합니다." },
  { mode: "confirm", label: "저장 전 확인", description: "후보를 확인한 뒤 개인 기억에 저장합니다." },
  { mode: "off", label: "저장 안 함", description: "새 개인 Memory 학습을 중지합니다." },
];

const proposalStatusLabels: Record<ProjectLearningProposalStatus, string> = {
  proposed: "검토 대기",
  approved: "승인됨",
  rejected: "거절됨",
  stale: "기준 만료",
  applied: "적용됨",
  rolled_back: "롤백됨",
};

function dateLabel(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

function shortId(value: string | null | undefined, length = 8) {
  if (!value) return "—";
  return value.length > length ? `${value.slice(0, length)}…` : value;
}

function projectLearningError(caught: unknown, fallback: string) {
  if (!(caught instanceof ApiError)) return fallback;
  const messages: Record<string, string> = {
    project_learning_base_conflict: "기준 revision 또는 hash가 이미 변경되었습니다. 최신 상태를 불러온 뒤 다시 제안해 주세요.",
    project_learning_source_not_found: "현재 대화에서 완료된 Run을 찾을 수 없거나 Project가 일치하지 않습니다.",
    project_learning_invalid_state: "현재 제안 상태에서는 이 작업을 실행할 수 없습니다. 목록을 새로 고쳐 주세요.",
    project_review_required: "Project owner 또는 admin만 제안을 검토하고 적용할 수 있습니다.",
    sensitive_project_learning_forbidden: "개인정보·개인 계정·임시 승인 정보는 Project Memory에 저장할 수 없습니다.",
  };
  return messages[caught.code] ?? caught.message ?? fallback;
}

function PersonalMemoryPanel({ refreshKey }: { refreshKey: number }) {
  const [items, setItems] = useState<UserMemory[]>([]);
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<MemoryListStatus>("active");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [draft, setDraft] = useState<MemoryDraft | null>(null);
  const [deleteArmedId, setDeleteArmedId] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api.memories.getSettings(controller.signal)
      .then(setSettings)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught instanceof ApiError ? caught.message : "Memory 설정을 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [refreshKey]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      const listing = status === "all"
        ? Promise.all([
            api.memories.list(query.trim() || undefined, "active", controller.signal),
            api.memories.list(query.trim() || undefined, "pending", controller.signal),
            api.memories.list(query.trim() || undefined, "dismissed", controller.signal),
            api.memories.list(query.trim() || undefined, "superseded", controller.signal),
          ]).then((groups) => groups.flat().sort((left, right) => right.updatedAt.localeCompare(left.updatedAt)))
        : api.memories.list(query.trim() || undefined, status, controller.signal);
      listing
        .then(setItems)
        .catch((caught) => {
          if (!controller.signal.aborted) setError(caught instanceof ApiError ? caught.message : "Memory를 불러오지 못했습니다.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 160);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, refreshKey, status]);

  const changeMode = async (mode: MemoryLearningMode) => {
    if (settings?.mode === mode || busy) return;
    setBusy("settings");
    setError(null);
    try {
      setSettings(await api.memories.updateSettings(mode));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "학습 방식을 변경하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const optimize = async () => {
    if (busy || status !== "active") return;
    setBusy("optimize");
    setError(null);
    setNotice(null);
    try {
      const result = await api.memories.optimize();
      setItems(await api.memories.list(query.trim() || undefined, "active"));
      setNotice(result.mergedIds.length > 0
        ? `${result.supersededIds.length}개 Memory를 ${result.mergedIds.length}개로 LLM 최적화했습니다.`
        : "통합할 중복 Memory가 없습니다.");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Memory를 최적화하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const beginEdit = (memory: UserMemory) => {
    setDeleteArmedId(null);
    setDraft({
      id: memory.id,
      category: memory.category,
      displayText: memory.displayText,
      status: memory.status === "dismissed" ? "dismissed" : "active",
    });
  };

  const saveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!draft || busy || !draft.category.trim() || !draft.displayText.trim()) return;
    setBusy(draft.id);
    setError(null);
    try {
      const updated = await api.memories.update(draft.id, {
        category: draft.category.trim(),
        fact: draft.displayText.trim(),
        displayText: draft.displayText.trim(),
        status: draft.status,
      });
      setItems((current) => status === "all" || updated.status === status
        ? current.map((memory) => memory.id === updated.id ? updated : memory)
        : current.filter((memory) => memory.id !== updated.id));
      setDraft(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Memory를 수정하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const removeMemory = async (memory: UserMemory) => {
    if (busy) return;
    if (deleteArmedId !== memory.id) {
      setDeleteArmedId(memory.id);
      return;
    }
    setBusy(memory.id);
    setError(null);
    try {
      await api.memories.delete(memory.id);
      setItems((current) => current.filter((item) => item.id !== memory.id));
      if (draft?.id === memory.id) setDraft(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Memory를 삭제하지 못했습니다.");
    } finally {
      setBusy(null);
      setDeleteArmedId(null);
    }
  };

  const reviewMemory = async (memory: UserMemory, nextStatus: "active" | "dismissed") => {
    if (busy) return;
    setBusy(memory.id);
    setError(null);
    try {
      await api.memories.update(memory.id, { status: nextStatus });
      setItems((current) => current.filter((item) => item.id !== memory.id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Memory 후보를 검토하지 못했습니다.");
    } finally {
      setBusy(null);
    }
  };

  const activeMode = modeOptions.find((option) => option.mode === settings?.mode) ?? modeOptions[0];

  return (
    <>
      {error && <div className="feature-error" role="alert">{error}</div>}
      <section className="memory-settings" aria-label="개인 Memory 학습 방식">
        <div className="memory-setting-copy"><strong>개인 학습 방식</strong><span>{activeMode.description}</span></div>
        <div className="memory-mode-control">
          {modeOptions.map((option) => (
            <button type="button" aria-pressed={settings?.mode === option.mode} disabled={!settings || busy === "settings"} key={option.mode} onClick={() => void changeMode(option.mode)}>
              {settings?.mode === option.mode && <Check size={12} />}{option.label}
            </button>
          ))}
        </div>
      </section>
      <div className="memory-toolbar">
        <label className="feature-search"><Search size={15} /><input aria-label="개인 Memory 검색" placeholder="기억한 내용 검색" value={query} onChange={(event) => { setQuery(event.currentTarget.value); setDeleteArmedId(null); }} /></label>
        <div className="memory-toolbar-actions">
          <div className="memory-status-control" role="group" aria-label="개인 Memory 상태">
            <button type="button" aria-pressed={status === "all"} onClick={() => { setStatus("all"); setDraft(null); setDeleteArmedId(null); }}>전체</button>
            <button type="button" aria-pressed={status === "active"} onClick={() => { setStatus("active"); setDraft(null); setDeleteArmedId(null); }}>활성</button>
            <button type="button" aria-pressed={status === "pending"} onClick={() => { setStatus("pending"); setDraft(null); setDeleteArmedId(null); }}>확인 대기</button>
            <button type="button" aria-pressed={status === "dismissed"} onClick={() => { setStatus("dismissed"); setDraft(null); setDeleteArmedId(null); }}>보류</button>
          </div>
          <button className="memory-primary-action lumina-primary-action" type="button" disabled={Boolean(busy) || status !== "active" || items.length < 2} onClick={() => void optimize()}>{busy === "optimize" ? <LoaderCircle className="is-running" size={14} /> : <Sparkles size={14} />} LLM 최적화</button>
        </div>
      </div>
      {notice && <div className="feature-notice" role="status">{notice}</div>}
      <div className="feature-scroll memory-scroll">
        {loading ? <div className="feature-state"><LoaderCircle className="is-running" size={17} /> Memory를 불러오고 있습니다.</div> : items.length === 0 ? <div className="feature-state">표시할 개인 Memory가 없습니다.</div> : (
          <div className="memory-list">
            {items.map((memory) => draft?.id === memory.id ? (
              <form className="memory-edit-form" key={memory.id} onSubmit={(event) => void saveEdit(event)}>
                <div className="memory-edit-grid">
                  <label><span>Category</span><input value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.currentTarget.value })} /></label>
                  <div className="lumina-select-field"><span>상태</span><SelectMenu value={draft.status} options={editableMemoryStatusOptions} ariaLabel="개인 Memory 상태" onChange={(value) => setDraft({ ...draft, status: value as "active" | "dismissed" })} /></div>
                </div>
                <label><span>기억할 내용</span><textarea rows={3} value={draft.displayText} onChange={(event) => setDraft({ ...draft, displayText: event.currentTarget.value })} /></label>
                <div className="memory-edit-actions"><button type="button" onClick={() => setDraft(null)}><X size={14} /> 취소</button><button className="is-primary lumina-primary-action" type="submit" disabled={busy === memory.id}><Save size={14} /> 저장</button></div>
              </form>
            ) : (
              <article className="memory-row" key={memory.id}>
                <header>
                  <div><strong>{memory.category}</strong><span><Link2 size={12} /> 출처 메시지 {memory.sourceMessageIds.length}개 · Run {memory.sourceRunIds.length}개</span></div>
                  <div className="memory-row-actions">
                    {memory.status === "pending" ? (
                      <>
                        <button className="tooltip-control is-accept" type="button" aria-label="개인 Memory 후보 수락" data-tooltip="기억에 저장" disabled={busy === memory.id} onClick={() => void reviewMemory(memory, "active")}>{busy === memory.id ? <LoaderCircle className="is-running" size={14} /> : <Check size={14} />}</button>
                        <button className="tooltip-control is-reject" type="button" aria-label="개인 Memory 후보 거절" data-tooltip="거절" disabled={busy === memory.id} onClick={() => void reviewMemory(memory, "dismissed")}><X size={14} /></button>
                      </>
                    ) : (
                      <>
                        <button className="tooltip-control" type="button" aria-label="개인 Memory 수정" data-tooltip="수정" onClick={() => beginEdit(memory)}><Pencil size={14} /></button>
                        <button className={`tooltip-control ${deleteArmedId === memory.id ? "is-delete-armed" : ""}`} type="button" aria-label={deleteArmedId === memory.id ? "개인 Memory 삭제 확인, 한 번 더 누르면 삭제" : "개인 Memory 삭제"} data-tooltip={deleteArmedId === memory.id ? "한 번 더 눌러 삭제" : "삭제"} disabled={busy === memory.id} onClick={() => void removeMemory(memory)}>{busy === memory.id ? <LoaderCircle className="is-running" size={14} /> : deleteArmedId === memory.id ? <AlertTriangle size={14} /> : <Trash2 size={14} />}</button>
                      </>
                    )}
                  </div>
                </header>
                <p>{memory.displayText}</p>
                <footer><span>근거 {memory.evidenceCount}회</span><span>신뢰도 {Math.round(memory.confidence * 100)}%</span><span>확인 {dateLabel(memory.lastConfirmedAt)}</span>{memory.supersedesMemoryId && <span>기존 Memory 대체 후보</span>}{memory.expiresAt && <span>만료 {dateLabel(memory.expiresAt)}</span>}</footer>
              </article>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function ProjectMemoryPanel({
  project,
  completedRunId,
  refreshKey,
  onProposalCreated,
}: {
  project: ProjectSummary | null;
  completedRunId: string | null;
  refreshKey: number;
  onProposalCreated: () => void;
}) {
  const [items, setItems] = useState<ProjectMemory[]>([]);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [history, setHistory] = useState<ProjectMemoryHistory | null>(null);
  const [draft, setDraft] = useState<ProjectProposalDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!project) {
      setItems([]);
      setSelectedKey(null);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.projectMemories.list(project.id, false, controller.signal)
      .then((nextItems) => {
        setItems(nextItems);
        setSelectedKey((current) => current && nextItems.some((item) => item.memoryKey === current)
          ? current
          : nextItems[0]?.memoryKey ?? null);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(projectLearningError(caught, "Project Memory를 불러오지 못했습니다."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [project, refreshKey]);

  useEffect(() => {
    if (!project || !selectedKey) {
      setHistory(null);
      return;
    }
    const controller = new AbortController();
    setHistoryLoading(true);
    api.projectMemories.getHistory(project.id, selectedKey, controller.signal)
      .then(setHistory)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(projectLearningError(caught, "Memory revision 이력을 불러오지 못했습니다."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryLoading(false);
      });
    return () => controller.abort();
  }, [project, refreshKey, selectedKey]);

  const categories = useMemo(() => Array.from(new Set(items.map((item) => item.category))).sort(), [items]);
  const filteredItems = useMemo(() => {
    const term = query.trim().toLocaleLowerCase("ko-KR");
    return items.filter((item) => {
      if (category !== "all" && item.category !== category) return false;
      if (!term) return true;
      return [item.category, item.displayText, item.normalizedFact, item.contentHash, ...item.sourceRunIds]
        .some((value) => value.toLocaleLowerCase("ko-KR").includes(term));
    });
  }, [category, items, query]);

  const openDraft = (mode: ProjectProposalDraft["mode"], target: ProjectMemory | null = null) => {
    setError(null);
    setDraft({
      mode,
      target,
      category: target?.category ?? "project_rule",
      fact: target?.normalizedFact ?? "",
      displayText: target?.displayText ?? "",
      rationale: mode === "delete" ? "더 이상 사용하지 않는 Project 정보입니다." : "반복 업무에 필요한 Project 정보입니다.",
    });
  };

  const submitProposal = async (event: FormEvent) => {
    event.preventDefault();
    if (!project || !completedRunId || !draft || busy) return;
    if (draft.mode !== "delete" && (!draft.category.trim() || !draft.fact.trim() || !draft.displayText.trim())) return;
    const target = draft.target;
    setBusy(true);
    setError(null);
    try {
      await api.projectMemories.createProposal(project.id, {
        sourceRunIds: [completedRunId],
        targetType: "project_memory",
        targetId: target?.memoryKey ?? null,
        baseRevision: target?.revision ?? 0,
        baseHash: target?.contentHash ?? EMPTY_HASH,
        proposedPatch: draft.mode === "delete"
          ? { delete: true }
          : {
              category: draft.category.trim(),
              fact: draft.fact.trim(),
              displayText: draft.displayText.trim(),
            },
        rationale: draft.rationale.trim(),
        evidenceRefs: [{ kind: "run", referenceId: completedRunId, note: "현재 세션의 완료된 Run" }],
        expectedScope: "project",
      });
      setDraft(null);
      onProposalCreated();
    } catch (caught) {
      setError(projectLearningError(caught, "Project Memory 제안을 만들지 못했습니다."));
    } finally {
      setBusy(false);
    }
  };

  if (!project) return <div className="feature-state">Project를 선택하면 Project Memory를 확인할 수 있습니다.</div>;

  return (
    <div className="project-memory-panel">
      {error && <div className="feature-error" role="alert">{error}</div>}
      <div className="memory-toolbar project-memory-toolbar">
        <label className="feature-search"><Search size={15} /><input aria-label="Project Memory 검색" placeholder="내용·hash·Run 검색" value={query} onChange={(event) => setQuery(event.currentTarget.value)} /></label>
        <SelectMenu className="memory-category-select" size="small" width="auto" value={category} options={[{ value: "all", label: "모든 Category" }, ...categories.map((item) => ({ value: item, label: item }))]} ariaLabel="Project Memory category" onChange={setCategory} />
        <button className="memory-primary-action lumina-primary-action" type="button" disabled={!completedRunId} title={completedRunId ? "새 Project Memory 제안" : "현재 세션에 완료된 Run이 필요합니다."} onClick={() => openDraft("new")}><Plus size={14} /> 새 Memory 제안</button>
      </div>
      {!completedRunId && <div className="memory-source-warning"><AlertTriangle size={14} /><span>현재 세션에 완료된 Run이 없어 제안을 만들 수 없습니다. 채팅 작업을 완료한 뒤 다시 시도해 주세요.</span></div>}
      {completedRunId && <div className="memory-source-line"><Link2 size={13} /><span>제안 근거</span><code title={completedRunId}>Run {shortId(completedRunId, 12)}</code></div>}
      {draft && (
        <form className="project-proposal-form" onSubmit={(event) => void submitProposal(event)}>
          <div className="proposal-form-heading">
            <div><strong>{draft.mode === "new" ? "새 Project Memory 제안" : draft.mode === "modify" ? "Project Memory 수정 제안" : "Project Memory 삭제 제안"}</strong><span>직접 변경하지 않고 검토 가능한 제안으로 저장합니다.</span></div>
            <button type="button" aria-label="제안 작성 닫기" onClick={() => setDraft(null)}><X size={14} /></button>
          </div>
          <div className="proposal-base-line">
            <span>Base</span><code>r{draft.target?.revision ?? 0}</code><code title={draft.target?.contentHash ?? EMPTY_HASH}>{shortId(draft.target?.contentHash ?? EMPTY_HASH, 12)}</code>
          </div>
          {draft.mode !== "delete" && (
            <>
              <label><span>Category</span><input required maxLength={80} value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.currentTarget.value })} /></label>
              <label><span>정규화할 사실</span><input required maxLength={1000} value={draft.fact} onChange={(event) => setDraft({ ...draft, fact: event.currentTarget.value })} /></label>
              <label><span>표시 내용</span><textarea required rows={3} maxLength={4000} value={draft.displayText} onChange={(event) => setDraft({ ...draft, displayText: event.currentTarget.value })} /></label>
            </>
          )}
          <label><span>제안 이유</span><textarea required rows={2} maxLength={4000} value={draft.rationale} onChange={(event) => setDraft({ ...draft, rationale: event.currentTarget.value })} /></label>
          <div className="memory-edit-actions"><button type="button" onClick={() => setDraft(null)}>취소</button><button className="is-primary lumina-primary-action" type="submit" disabled={busy || !completedRunId}>{busy ? <LoaderCircle className="is-running" size={14} /> : <Save size={14} />} 제안 저장</button></div>
        </form>
      )}
      <div className="project-memory-layout">
        <section className="project-memory-list-pane" aria-label="활성 Project Memory">
          <div className="project-memory-section-title"><span>활성 Memory</span><small>{filteredItems.length}개</small></div>
          {loading ? <div className="feature-state"><LoaderCircle className="is-running" size={16} /> 불러오는 중</div> : filteredItems.length === 0 ? <div className="feature-state">조건에 맞는 활성 Memory가 없습니다.</div> : filteredItems.map((memory) => (
            <article className={`project-memory-item ${selectedKey === memory.memoryKey ? "is-selected" : ""}`} key={memory.id}>
              <button className="project-memory-select" type="button" onClick={() => setSelectedKey(memory.memoryKey)}>
                <span className="project-memory-category">{memory.category}</span>
                <strong>{memory.displayText}</strong>
                <small>{memory.normalizedFact}</small>
                <div><span>r{memory.revision}</span><code title={memory.contentHash}>{shortId(memory.contentHash, 10)}</code><span>Run {memory.sourceRunIds.length}개</span><ChevronRight size={13} /></div>
              </button>
              <div className="project-memory-actions">
                <button className="tooltip-control" type="button" aria-label="Project Memory 수정 제안" data-tooltip="수정 제안" disabled={!completedRunId} onClick={() => openDraft("modify", memory)}><Pencil size={14} /></button>
                <button className="tooltip-control" type="button" aria-label="Project Memory 삭제 제안" data-tooltip="삭제 제안" disabled={!completedRunId} onClick={() => openDraft("delete", memory)}><Trash2 size={14} /></button>
              </div>
            </article>
          ))}
        </section>
        <section className="project-memory-history-pane" aria-label="선택한 Memory revision 이력">
          <div className="project-memory-section-title"><span><History size={14} /> Revision 이력</span>{history && <small>{history.revisions.length}개</small>}</div>
          {historyLoading ? <div className="feature-state"><LoaderCircle className="is-running" size={16} /> 이력을 불러오는 중</div> : !history ? <div className="feature-state">Memory를 선택하면 불변 revision 이력이 표시됩니다.</div> : (
            <div className="project-memory-history-list">
              {history.revisions.map((revision) => (
                <article key={revision.id}>
                  <header><strong>r{revision.revision}</strong><span className={`memory-revision-status status-${revision.status}`}>{revision.status}</span><time>{dateLabel(revision.createdAt)}</time></header>
                  <p>{revision.displayText}</p>
                  <dl>
                    <div><dt>Hash</dt><dd><code title={revision.contentHash}>{shortId(revision.contentHash, 16)}</code></dd></div>
                    <div><dt>Source</dt><dd>{revision.sourceRunIds.map((runId) => <code title={runId} key={runId}>Run {shortId(runId)}</code>)}</dd></div>
                    <div><dt>Proposal</dt><dd><code title={revision.sourceProposalId}>{shortId(revision.sourceProposalId, 12)}</code></dd></div>
                  </dl>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function LearningProposalsPanel({
  project,
  completedRunId,
  canReview,
  refreshKey,
  onChanged,
}: {
  project: ProjectSummary | null;
  completedRunId: string | null;
  canReview: boolean;
  refreshKey: number;
  onChanged: () => void;
}) {
  const [items, setItems] = useState<ProjectLearningProposal[]>([]);
  const [status, setStatus] = useState<ProposalFilter>("all");
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState("");
  const [conceptFormOpen, setConceptFormOpen] = useState(false);
  const [concept, setConcept] = useState(project?.concept ?? "");
  const [conceptRationale, setConceptRationale] = useState("Project의 반복 업무 배경을 더 명확히 설명합니다.");
  const [projectBasis, setProjectBasis] = useState<ProjectSummary | null>(project);

  useEffect(() => {
    if (!project) {
      setItems([]);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.projectMemories.listProposals(project.id, status === "all" ? undefined : status, controller.signal)
      .then(setItems)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(projectLearningError(caught, "메모리 반영 제안을 불러오지 못했습니다."));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [project, refreshKey, status]);

  useEffect(() => {
    if (!project) {
      setProjectBasis(null);
      return;
    }
    const controller = new AbortController();
    api.projects.list(controller.signal)
      .then((projects) => {
        const current = projects.find((item) => item.id === project.id) ?? null;
        setProjectBasis(current);
        if (!conceptFormOpen && current) setConcept(current.concept);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(projectLearningError(caught, "Project concept 기준을 불러오지 못했습니다."));
      });
    return () => controller.abort();
  }, [conceptFormOpen, project, refreshKey]);

  const createConceptProposal = async (event: FormEvent) => {
    event.preventDefault();
    if (!project || !projectBasis || !completedRunId || busyId || !conceptRationale.trim()) return;
    setBusyId("concept");
    setError(null);
    setNotice(null);
    try {
      await api.projectMemories.createProposal(project.id, {
        sourceRunIds: [completedRunId],
        targetType: "project_concept",
        targetId: null,
        baseRevision: projectBasis.conceptRevision,
        baseHash: projectBasis.conceptHash,
        proposedPatch: { concept },
        rationale: conceptRationale.trim(),
        evidenceRefs: [{ kind: "run", referenceId: completedRunId, note: "현재 세션의 완료된 Run" }],
        expectedScope: "project",
      });
      setConceptFormOpen(false);
      setStatus("proposed");
      setNotice("Project concept 제안을 만들었습니다.");
      onChanged();
    } catch (caught) {
      setError(projectLearningError(caught, "Project concept 제안을 만들지 못했습니다."));
    } finally {
      setBusyId(null);
    }
  };

  const mutateProposal = async (proposal: ProjectLearningProposal, action: "approve" | "reject" | "apply" | "rollback") => {
    if (!project || !canReview || busyId) return;
    setBusyId(proposal.id);
    setError(null);
    setNotice(null);
    try {
      const updated = action === "approve" || action === "reject"
        ? await api.projectMemories.reviewProposal(project.id, proposal.id, action, reviewNote.trim())
        : action === "apply"
          ? (await api.projectMemories.applyProposal(project.id, proposal.id)).proposal
          : (await api.projectMemories.rollbackProposal(project.id, proposal.id)).proposal;
      setNotice(updated.status === "stale"
        ? "기준 revision 또는 hash가 달라져 제안이 만료되었습니다. 최신 기준으로 다시 제안해 주세요."
        : action === "approve" ? "제안을 승인했습니다."
          : action === "reject" ? "제안을 거절했습니다."
            : action === "apply" ? "승인된 제안을 Project에 적용했습니다."
              : "적용한 변경을 새 revision으로 롤백했습니다.");
      setReviewNote("");
      onChanged();
    } catch (caught) {
      setError(projectLearningError(caught, "메모리 반영 제안 상태를 변경하지 못했습니다."));
    } finally {
      setBusyId(null);
    }
  };

  if (!project) return <div className="feature-state">Project를 선택하면 메모리 반영 제안을 확인할 수 있습니다.</div>;

  return (
    <div className="learning-proposals-panel">
      {error && <div className="feature-error" role="alert">{error}</div>}
      {notice && <div className="feature-notice" role="status">{notice}</div>}
      <div className="learning-proposal-toolbar">
        <div className="lumina-select-field learning-proposal-select-field"><span>상태</span><SelectMenu size="small" value={status} options={[{ value: "all", label: "모든 상태" }, ...Object.entries(proposalStatusLabels).map(([value, label]) => ({ value, label }))]} ariaLabel="메모리 반영 제안 상태" onChange={(value) => setStatus(value as ProposalFilter)} /></div>
        {canReview ? <label className="proposal-review-note"><span>검토 메모</span><input maxLength={1000} placeholder="선택 입력" value={reviewNote} onChange={(event) => setReviewNote(event.currentTarget.value)} /></label> : <div className="proposal-review-policy"><ShieldCheck size={14} /><span>검토·적용은 Project owner 또는 admin만 가능합니다.</span></div>}
        <button className="memory-primary-action lumina-primary-action" type="button" disabled={!completedRunId || !projectBasis} title={completedRunId ? "Project concept 변경 제안" : "현재 세션에 완료된 Run이 필요합니다."} onClick={() => { setConcept(projectBasis?.concept ?? ""); setConceptFormOpen(true); }}><Lightbulb size={14} /> Concept 제안</button>
      </div>
      {!completedRunId && <div className="memory-source-warning"><AlertTriangle size={14} /><span>새 메모리 반영 제안에는 현재 세션의 완료된 Run이 근거로 필요합니다.</span></div>}
      {conceptFormOpen && projectBasis && (
        <form className="project-proposal-form concept-proposal-form" onSubmit={(event) => void createConceptProposal(event)}>
          <div className="proposal-form-heading"><div><strong>Project concept 변경 제안</strong><span>현재 기준과 정확히 일치할 때만 승인·적용됩니다.</span></div><button type="button" aria-label="Concept 제안 닫기" onClick={() => setConceptFormOpen(false)}><X size={14} /></button></div>
          <div className="proposal-base-line"><span>Base</span><code>r{projectBasis.conceptRevision}</code><code title={projectBasis.conceptHash}>{shortId(projectBasis.conceptHash, 12)}</code><span>{projectBasis.name}</span></div>
          <label><span>Project concept</span><textarea rows={5} maxLength={20_000} value={concept} onChange={(event) => setConcept(event.currentTarget.value)} /></label>
          <label><span>제안 이유</span><textarea required rows={2} maxLength={4000} value={conceptRationale} onChange={(event) => setConceptRationale(event.currentTarget.value)} /></label>
          <div className="memory-edit-actions"><button type="button" onClick={() => setConceptFormOpen(false)}>취소</button><button className="is-primary lumina-primary-action" type="submit" disabled={busyId === "concept" || !completedRunId}>{busyId === "concept" ? <LoaderCircle className="is-running" size={14} /> : <Save size={14} />} 제안 저장</button></div>
        </form>
      )}
      <div className="feature-scroll learning-proposal-scroll">
        {loading ? <div className="feature-state"><LoaderCircle className="is-running" size={17} /> 메모리 반영 제안을 불러오고 있습니다.</div> : items.length === 0 ? <div className="feature-state">이 상태의 메모리 반영 제안이 없습니다.</div> : (
          <div className="learning-proposal-list">
            {items.map((proposal) => (
              <article className={`learning-proposal-row status-${proposal.status}`} key={proposal.id}>
                <header>
                  <div><span className="learning-target">{proposal.targetType === "project_concept" ? "Project concept" : proposal.targetId ? `Project Memory · ${shortId(proposal.targetId)}` : "새 Project Memory"}</span><span className={`learning-status status-${proposal.status}`}>{proposalStatusLabels[proposal.status]}</span></div>
                  <time>{dateLabel(proposal.createdAt)}</time>
                </header>
                <div className="learning-proposal-body">
                  <div className="learning-proposal-copy">
                    <strong>제안 이유</strong><p>{proposal.rationale}</p>
                    <strong>변경 내용</strong><SyntaxCode value={JSON.stringify(proposal.proposedPatch, null, 2)} language="json" />
                  </div>
                  <dl className="learning-proposal-meta">
                    <div><dt>Base</dt><dd><code>r{proposal.baseRevision}</code><code title={proposal.baseHash}>{shortId(proposal.baseHash, 12)}</code></dd></div>
                    <div><dt>근거</dt><dd>{proposal.sourceRunIds.map((runId) => <code title={runId} key={runId}>Run {shortId(runId)}</code>)}</dd></div>
                    <div><dt>Evidence</dt><dd>{proposal.evidenceRefs.length > 0 ? proposal.evidenceRefs.map((evidence, index) => <code title={evidence.referenceId} key={`${evidence.kind}-${evidence.referenceId}-${index}`}>{evidence.kind} · {shortId(evidence.referenceId)}</code>) : "—"}</dd></div>
                    <div><dt>제안자</dt><dd><code title={proposal.proposedByUserId}>{shortId(proposal.proposedByUserId, 12)}</code></dd></div>
                    <div><dt>검토자</dt><dd>{proposal.reviewedByUserId ? <code title={proposal.reviewedByUserId}>{shortId(proposal.reviewedByUserId, 12)}</code> : "—"}</dd></div>
                    {proposal.reviewNote && <div><dt>검토 메모</dt><dd>{proposal.reviewNote}</dd></div>}
                  </dl>
                </div>
                {proposal.status === "stale" && <div className="proposal-stale-note"><AlertTriangle size={13} /> 기준이 변경되어 적용할 수 없습니다. 최신 revision/hash로 새 제안을 만들어 주세요.</div>}
                <footer>
                  <span><Clock3 size={12} /> 갱신 {dateLabel(proposal.updatedAt)}</span>
                  <div className="proposal-actions">
                    {proposal.status === "proposed" && <>
                      <button type="button" disabled={!canReview || busyId === proposal.id} title={canReview ? "제안 승인" : "owner/admin 권한이 필요합니다."} onClick={() => void mutateProposal(proposal, "approve")}>{busyId === proposal.id ? <LoaderCircle className="is-running" size={13} /> : <Check size={13} />} 승인</button>
                      <button type="button" disabled={!canReview || busyId === proposal.id} title={canReview ? "제안 거절" : "owner/admin 권한이 필요합니다."} onClick={() => void mutateProposal(proposal, "reject")}><X size={13} /> 거절</button>
                    </>}
                    {proposal.status === "approved" && <>
                      <button className="is-primary lumina-primary-action" type="button" disabled={!canReview || busyId === proposal.id} title={canReview ? "Project에 적용" : "owner/admin 권한이 필요합니다."} onClick={() => void mutateProposal(proposal, "apply")}>{busyId === proposal.id ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />} 적용</button>
                      <button type="button" disabled={!canReview || busyId === proposal.id} title={canReview ? "제안 거절" : "owner/admin 권한이 필요합니다."} onClick={() => void mutateProposal(proposal, "reject")}><X size={13} /> 거절</button>
                    </>}
                    {proposal.status === "applied" && <button type="button" disabled={!canReview || busyId === proposal.id} title={canReview ? "새 revision으로 롤백" : "owner/admin 권한이 필요합니다."} onClick={() => void mutateProposal(proposal, "rollback")}>{busyId === proposal.id ? <LoaderCircle className="is-running" size={13} /> : <RotateCcw size={13} />} 롤백</button>}
                  </div>
                </footer>
              </article>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function MemoryView({
  onOpenNavigation,
  project,
  completedRunId,
  canReviewProjectLearning,
}: MemoryViewProps) {
  const [tab, setTab] = useState<MemoryTab>("personal");
  const [refreshKey, setRefreshKey] = useState(0);

  const refresh = () => setRefreshKey((value) => value + 1);
  const proposalCreated = () => {
    refresh();
    setTab("proposals");
  };

  return (
    <div className="feature-view memory-view">
      <header className="feature-header">
        <div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><Brain size={17} /><h1>Memory</h1><span>개인·Project 학습 내용 검토{tab !== "personal" && project ? ` · ${project.name}` : ""}</span></div>
        <button type="button" aria-label="Memory 새로 고침" onClick={refresh}><RefreshCw size={15} /></button>
      </header>
      <nav className="memory-tabs" aria-label="Memory 영역">
        <button type="button" aria-current={tab === "personal" ? "page" : undefined} onClick={() => setTab("personal")}>개인 Memory</button>
        <button type="button" aria-current={tab === "project" ? "page" : undefined} onClick={() => setTab("project")}>Project Memory</button>
        <button type="button" aria-current={tab === "proposals" ? "page" : undefined} onClick={() => setTab("proposals")}>메모리 반영 제안</button>
      </nav>
      {tab === "personal" && <PersonalMemoryPanel refreshKey={refreshKey} />}
      {tab === "project" && <ProjectMemoryPanel project={project} completedRunId={completedRunId} refreshKey={refreshKey} onProposalCreated={proposalCreated} />}
      {tab === "proposals" && <LearningProposalsPanel project={project} completedRunId={completedRunId} canReview={canReviewProjectLearning} refreshKey={refreshKey} onChanged={refresh} />}
    </div>
  );
}
