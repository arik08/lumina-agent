import {
  CalendarClock,
  CheckCircle2,
  Clock3,
  History,
  LoaderCircle,
  Menu,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import type { EffortOption, ExecutionSelection, ProjectSummary, ScheduleKind, ScheduledRun, ScheduledTask } from "../api-types";
import { SelectMenu } from "./SelectMenu";
import { ResizableSplitPane } from "./ResizableSplitPane";

interface ScheduleExecutionOption {
  providerId: string;
  providerLabel: string;
  modelKey: string;
  modelLabel: string;
  effortOptions: EffortOption[];
}

interface SchedulesViewProps {
  projectId: string | null;
  projects: ProjectSummary[];
  execution: ExecutionSelection | null;
  executionOptions: ScheduleExecutionOption[];
  onOpenNavigation: () => void;
  onProjectChange: (projectId: string) => void;
  onConversationsChanged: () => Promise<unknown>;
}

const kindLabels: Record<ScheduleKind, string> = {
  hourly: "매시간",
  daily: "매일",
  weekly: "매주",
  weekdays: "평일",
  manual: "수동",
};

const scheduleKindOptions = Object.entries(kindLabels).map(([value, label]) => ({ value, label }));
const weekdayOptions = ["월", "화", "수", "목", "금", "토", "일"].map((label, index) => ({ value: String(index), label }));

function effortForOption(option: ScheduleExecutionOption, preferred: string | null | undefined) {
  if (preferred === null) return null;
  const effortIds = option.effortOptions.map((item) => item.id);
  if (preferred && effortIds.includes(preferred)) return preferred;
  return effortIds.find((item) => item === "medium") ?? effortIds[0] ?? null;
}

function defaultScheduleExecution(
  execution: ExecutionSelection | null,
  options: ScheduleExecutionOption[],
): ExecutionSelection | null {
  const option = options.find((item) => (
    item.providerId === execution?.providerId && item.modelKey === execution.modelKey
  )) ?? options[0];
  if (!option) return null;
  return {
    providerId: option.providerId,
    modelKey: option.modelKey,
    effortId: effortForOption(option, option.providerId === execution?.providerId && option.modelKey === execution.modelKey
      ? execution.effortId
      : undefined),
  };
}

function scheduleText(task: ScheduledTask) {
  const hour = task.scheduleConfig.hour;
  const minute = task.scheduleConfig.minute ?? 0;
  const time = `${String(hour ?? 0).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
  if (task.scheduleKind === "hourly") return `매시간 ${String(minute).padStart(2, "0")}분`;
  if (task.scheduleKind === "daily") return `매일 ${time}`;
  if (task.scheduleKind === "weekdays") return `평일 ${time}`;
  if (task.scheduleKind === "weekly") return `매주 ${["월", "화", "수", "목", "금", "토", "일"][task.scheduleConfig.weekday ?? 0]}요일 ${time}`;
  return "수동 실행";
}

function runStatusLabel(status: string) {
  if (status === "completed") return "완료";
  if (status === "running") return "실행 중";
  if (status === "queued") return "대기";
  if (status === "failed") return "실패";
  if (status === "cancelled") return "취소";
  return status;
}

export function SchedulesView({ projectId, projects, execution, executionOptions, onOpenNavigation, onProjectChange, onConversationsChanged }: SchedulesViewProps) {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [runs, setRuns] = useState<ScheduledRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [deleteErrorId, setDeleteErrorId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [instructions, setInstructions] = useState("");
  const [kind, setKind] = useState<ScheduleKind>("daily");
  const [hour, setHour] = useState(9);
  const [minute, setMinute] = useState(0);
  const [weekday, setWeekday] = useState(0);
  const [draftProjectId, setDraftProjectId] = useState<string | null>(null);
  const [draftExecution, setDraftExecution] = useState<ExecutionSelection | null>(null);

  const selected = tasks.find((task) => task.id === selectedId) ?? tasks[0] ?? null;
  const projectOptions = useMemo(() => projects.map((project) => ({ value: project.id, label: project.name })), [projects]);
  const selectedProjectName = projects.find((project) => project.id === selected?.projectId)?.name ?? null;
  const providerOptions = useMemo(() => {
    const seen = new Set<string>();
    return executionOptions.flatMap((option) => {
      if (seen.has(option.providerId)) return [];
      seen.add(option.providerId);
      return [{ value: option.providerId, label: option.providerLabel }];
    });
  }, [executionOptions]);
  const modelOptions = useMemo(() => executionOptions
    .filter((option) => option.providerId === draftExecution?.providerId)
    .map((option) => ({ value: option.modelKey, label: option.modelLabel })), [draftExecution?.providerId, executionOptions]);
  const selectedExecutionOption = executionOptions.find((option) => (
    option.providerId === draftExecution?.providerId && option.modelKey === draftExecution.modelKey
  )) ?? null;
  const scheduleEffortOptions = [
    { value: "", label: "기본값" },
    ...(selectedExecutionOption?.effortOptions.map((option) => ({ value: option.id, label: option.label })) ?? []),
  ];

  useEffect(() => {
    setDeleteConfirmId(null);
    setDeleteErrorId(null);
  }, [projectId, selected?.id]);

  const refresh = async (preferredId?: string) => {
    if (!projectId) {
      setTasks([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const nextTasks = await api.schedules.list(projectId);
      setTasks(nextTasks);
      setSelectedId((current) => preferredId ?? (current && nextTasks.some((task) => task.id === current) ? current : nextTasks[0]?.id ?? null));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "예약 작업을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [projectId]);

  useEffect(() => {
    if (!selected?.id) {
      setRuns([]);
      return;
    }
    const controller = new AbortController();
    setHistoryLoading(true);
    api.schedules.listRuns(selected.id, controller.signal)
      .then(setRuns)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught instanceof ApiError ? caught.message : "실행 이력을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setHistoryLoading(false);
      });
    return () => controller.abort();
  }, [selected?.id]);

  const hasActiveHistory = runs.some((run) => run.status === "queued" || run.status === "running");

  useEffect(() => {
    if (!selected?.id || !hasActiveHistory) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      api.schedules.listRuns(selected.id, controller.signal)
        .then(setRuns)
        .catch((caught) => {
          if (!controller.signal.aborted) setError(caught instanceof ApiError ? caught.message : "실행 이력을 갱신하지 못했습니다.");
        });
    }, 1500);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [hasActiveHistory, selected?.id]);

  const scheduleConfig = useMemo<Record<string, number>>(() => {
    const config: Record<string, number> = {};
    if (kind === "hourly") config.minute = minute;
    if (kind === "daily" || kind === "weekdays") {
      config.hour = hour;
      config.minute = minute;
    }
    if (kind === "weekly") {
      config.weekday = weekday;
      config.hour = hour;
      config.minute = minute;
    }
    return config;
  }, [hour, kind, minute, weekday]);

  const createTask = async (event: FormEvent) => {
    event.preventDefault();
    if (!draftProjectId || !draftExecution || !name.trim() || !instructions.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.schedules.create({
        projectId: draftProjectId,
        name: name.trim(),
        instructions: instructions.trim(),
        scheduleKind: kind,
        scheduleConfig,
        execution: draftExecution,
      });
      setCreateOpen(false);
      setName("");
      setInstructions("");
      if (created.projectId !== projectId) {
        setTasks([created]);
        setSelectedId(created.id);
        onProjectChange(created.projectId);
      } else {
        await refresh(created.id);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "예약 작업을 만들지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const updated = await api.schedules.setEnabled(selected.id, !selected.enabled);
      setTasks((current) => current.map((task) => task.id === updated.id ? updated : task));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "예약 상태를 바꾸지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const runNow = async () => {
    if (!selected || busy) return;
    setBusy(true);
    try {
      const created = await api.schedules.runNow(selected.id);
      setRuns((current) => [created, ...current.filter((run) => run.id !== created.id)]);
      try {
        await onConversationsChanged();
      } catch {
        setError("실행은 시작됐지만 최근 항목을 갱신하지 못했습니다.");
      }
      await refresh(selected.id);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "예약 작업을 실행하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const openCreateForm = () => {
    setDraftProjectId(projectId ?? projects[0]?.id ?? null);
    setDraftExecution(defaultScheduleExecution(execution, executionOptions));
    setCreateOpen(true);
  };

  const selectScheduleProvider = (providerId: string) => {
    const option = executionOptions.find((item) => item.providerId === providerId);
    if (!option) return;
    setDraftExecution({
      providerId,
      modelKey: option.modelKey,
      effortId: effortForOption(option, undefined),
    });
  };

  const selectScheduleModel = (modelKey: string) => {
    const option = executionOptions.find((item) => (
      item.providerId === draftExecution?.providerId && item.modelKey === modelKey
    ));
    if (!option) return;
    setDraftExecution((current) => current ? {
      ...current,
      modelKey,
      effortId: effortForOption(option, current.effortId),
    } : null);
  };

  const deleteTask = async () => {
    if (!selected || busy) return;
    if (deleteConfirmId !== selected.id) {
      setDeleteConfirmId(selected.id);
      setDeleteErrorId(null);
      setError(null);
      return;
    }
    setBusy(true);
    setDeleteErrorId(null);
    setError(null);
    try {
      await api.schedules.delete(selected.id);
      const remaining = tasks.filter((task) => task.id !== selected.id);
      setTasks(remaining);
      setSelectedId(remaining[0]?.id ?? null);
      setDeleteConfirmId(null);
    } catch (caught) {
      setDeleteErrorId(selected.id);
      setError(caught instanceof ApiError ? caught.message : "예약 작업을 삭제하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="feature-view">
      <header className="feature-header">
        <div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><CalendarClock size={17} /><h1>예약 작업</h1><span>{tasks.length}개</span></div>
        <div>
          <button className="schedule-list-refresh" type="button" aria-label="새로 고침" onClick={() => void refresh()}><RefreshCw size={15} /></button>
        </div>
      </header>
      {error && <div className="feature-error" role="alert">{error}</div>}
      <ResizableSplitPane storageKey="lumina:schedules-list-width" ariaLabel="예약 작업 목록 너비 조절" className="schedules-split">
        <aside className="feature-list schedule-list" aria-label="예약 작업 목록">
          <div className="feature-toolbar schedule-list-toolbar">
            <button className="feature-primary-action lumina-primary-action" type="button" disabled={!projectId || !execution || executionOptions.length === 0} onClick={openCreateForm}><Plus size={15} /> 새 예약</button>
          </div>
          {loading ? <div className="feature-state"><LoaderCircle className="is-running" size={16} /> 불러오는 중</div> : tasks.length === 0 ? <div className="feature-state">예약 작업이 없습니다.</div> : tasks.map((task) => (
            <button className={task.id === selected?.id ? "is-selected" : ""} type="button" key={task.id} onClick={() => { setSelectedId(task.id); setCreateOpen(false); }}>
              <span><strong>{task.name}</strong><small>{scheduleText(task)}</small></span>
              <em className={task.enabled ? "is-enabled" : ""}>{task.enabled ? "사용" : "중지"}</em>
            </button>
          ))}
        </aside>
        <section className="feature-detail schedule-detail">
          {createOpen ? (
            <form className="compact-form schedule-form schedule-detail-form" aria-labelledby="new-schedule-title" onSubmit={(event) => void createTask(event)}>
              <header className="detail-heading schedule-form-heading">
                <div><h2 id="new-schedule-title">새 예약 작업</h2><p>예약 결과가 저장될 프로젝트와 실행 설정을 정합니다.</p></div>
                <button className="schedule-form-close" type="button" aria-label="예약 작성 닫기" onClick={() => setCreateOpen(false)}><X size={16} /></button>
              </header>
              <label><span>이름</span><input autoFocus value={name} onChange={(event) => setName(event.currentTarget.value)} /></label>
              <label><span>작업 지시</span><textarea rows={6} value={instructions} onChange={(event) => setInstructions(event.currentTarget.value)} /></label>
              <div className="lumina-select-field"><span>세션 저장 프로젝트</span><SelectMenu value={draftProjectId ?? ""} options={projectOptions} ariaLabel="예약 작업 세션 저장 프로젝트" onChange={setDraftProjectId} /></div>
              <div className="schedule-form-row">
                <div className="lumina-select-field"><span>주기</span><SelectMenu value={kind} options={scheduleKindOptions} ariaLabel="예약 주기" onChange={(value) => setKind(value as ScheduleKind)} /></div>
                {kind === "weekly" && <div className="lumina-select-field"><span>요일</span><SelectMenu value={String(weekday)} options={weekdayOptions} ariaLabel="예약 요일" onChange={(value) => setWeekday(Number(value))} /></div>}
                {kind !== "manual" && kind !== "hourly" && <label><span>시</span><input type="number" min={0} max={23} value={hour} onChange={(event) => setHour(Number(event.currentTarget.value))} /></label>}
                {kind !== "manual" && <label><span>분</span><input type="number" min={0} max={59} value={minute} onChange={(event) => setMinute(Number(event.currentTarget.value))} /></label>}
              </div>
              <div className="schedule-execution-row">
                <div className="lumina-select-field"><span>Provider</span><SelectMenu value={draftExecution?.providerId ?? ""} options={providerOptions} ariaLabel="예약 Provider" onChange={selectScheduleProvider} /></div>
                <div className="lumina-select-field"><span>Model</span><SelectMenu value={draftExecution?.modelKey ?? ""} options={modelOptions} ariaLabel="예약 Model" onChange={selectScheduleModel} /></div>
                <div className="lumina-select-field"><span>Effort</span><SelectMenu value={draftExecution?.effortId ?? ""} options={scheduleEffortOptions} ariaLabel="예약 Effort" onChange={(value) => setDraftExecution((current) => current ? { ...current, effortId: value || null } : null)} /></div>
              </div>
              <p className="form-help">예약 실행마다 선택한 프로젝트에 새 채팅을 만들고 결과를 저장합니다. 일반 채팅의 현재 실행 설정을 기본값으로 사용하며, 계정 메뉴에서 사용하도록 체크한 Provider와 Model만 선택할 수 있습니다.</p>
              <div className="dialog-actions"><button type="button" onClick={() => setCreateOpen(false)}>취소</button><button className="is-primary lumina-primary-action" type="submit" disabled={!name.trim() || !instructions.trim() || !draftProjectId || !draftExecution || busy}>예약 생성</button></div>
            </form>
          ) : !selected ? <div className="feature-state">예약 작업을 선택해 주세요.</div> : (
            <>
              <header className="detail-heading">
                <div><h2>{selected.name}</h2><p>{selected.instructions}</p></div>
                <div className="detail-badges"><span>{kindLabels[selected.scheduleKind]}</span><span>{selected.timezone}</span></div>
              </header>
              <div className="schedule-summary">
                <span><Clock3 size={14} /><strong>{scheduleText(selected)}</strong></span>
                {selectedProjectName && <span>세션 저장 프로젝트 {selectedProjectName}</span>}
                <span>다음 실행 {selected.nextRunAt ? new Date(selected.nextRunAt).toLocaleString("ko-KR") : "없음"}</span>
                <span>{selected.execution.modelKey} · {selected.execution.effortId ?? "기본 Effort"}</span>
              </div>
              <div className="detail-actions schedule-actions">
                <button type="button" disabled={busy} onClick={() => void toggleEnabled()}>{selected.enabled ? <Pause size={14} /> : <Play size={14} />}{selected.enabled ? "중지" : "사용"}</button>
                <button className="is-primary lumina-primary-action" type="button" disabled={busy} onClick={() => void runNow()}><Play size={14} /> 지금 실행</button>
                <button
                  className={`is-danger ${deleteConfirmId === selected.id ? "is-confirming" : ""}`}
                  type="button"
                  disabled={busy}
                  aria-label={deleteErrorId === selected.id ? "예약 작업 삭제 실패, 다시 시도" : undefined}
                  onClick={() => void deleteTask()}
                >
                  {busy && deleteConfirmId === selected.id ? <LoaderCircle className="is-running" size={14} /> : <Trash2 size={14} />}
                  {busy && deleteConfirmId === selected.id
                    ? "삭제 중"
                    : deleteErrorId === selected.id
                      ? "삭제 실패, 다시 시도"
                      : deleteConfirmId === selected.id
                        ? "한 번 더 눌러 삭제"
                        : "삭제"}
                </button>
              </div>
              <section className="schedule-history">
                <h3><History size={15} /> 실행 이력</h3>
                {historyLoading ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 이력을 불러오는 중</div> : runs.length === 0 ? <div className="feature-state">실행 이력이 없습니다.</div> : runs.map((run) => (
                  <div className="schedule-run-row" key={run.id}>
                    <span className={`run-state state-${run.status}`}>{run.status === "completed" ? <CheckCircle2 size={14} /> : run.status === "running" || run.status === "queued" ? <LoaderCircle className={run.status === "running" ? "is-running" : ""} size={14} /> : <Clock3 size={14} />}{runStatusLabel(run.status)}</span>
                    <span>{run.triggerType === "manual" ? "수동" : "예약"} · {new Date(run.scheduledFor).toLocaleString("ko-KR")}</span>
                    <small>{run.finishedAt ? `완료 ${new Date(run.finishedAt).toLocaleTimeString("ko-KR")}` : `시도 ${run.attempt}`}</small>
                  </div>
                ))}
              </section>
            </>
          )}
        </section>
      </ResizableSplitPane>
    </div>
  );
}
