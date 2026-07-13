import {
  AlertTriangle,
  BookOpen,
  Check,
  ChevronDown,
  ChevronUp,
  CircleHelp,
  FileText,
  History,
  Layers3,
  LoaderCircle,
  Pencil,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { api } from "../api";
import type {
  AdminAuditEvent,
  InstructionDocument,
  ProjectSummary,
  RuntimePromptDocument,
  RuntimePromptKey,
} from "../api-types";
import { InstructionEditor } from "./InstructionEditor";
import { SelectMenu } from "./SelectMenu";
import "./OrganizationInstructionsPanel.css";

type PromptLayerKey = RuntimePromptKey | "organization" | "concept" | "project" | "personal";

function formatHistoryDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function RuntimePromptEditor({
  document,
  onUpdated,
}: {
  document: RuntimePromptDocument;
  onUpdated: (document: RuntimePromptDocument) => void;
}) {
  const [draft, setDraft] = useState(document.content);
  const [saving, setSaving] = useState(false);
  const [resetArmed, setResetArmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    setDraft(document.content);
    setResetArmed(false);
    setError(null);
  }, [document]);

  const update = async (content: string, reset = false) => {
    if (saving) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await api.instructions.updateRuntimePrompt(document.key, {
        content,
        expectedRevision: document.revision,
        expectedDigest: document.digest,
      });
      onUpdated(updated);
      setNotice(reset ? "기본값으로 복원했습니다. 새 Run부터 적용됩니다." : "프롬프트를 저장했습니다. 새 Run부터 적용됩니다.");
      setResetArmed(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "프롬프트를 저장하지 못했습니다.");
    } finally {
      setSaving(false);
    }
  };

  const reset = () => {
    if (!document.overridden || saving) return;
    if (!resetArmed) {
      setResetArmed(true);
      setNotice(null);
      return;
    }
    void update(document.defaultContent, true);
  };

  return (
    <section className="runtime-prompt-editor" aria-labelledby={`runtime-prompt-${document.key}`}>
      <header>
        <div>
          <span className="runtime-prompt-kicker">내부 프롬프트 · rev.{document.revision}</span>
          <h2 id={`runtime-prompt-${document.key}`}>{document.name}</h2>
          <p>{document.description}</p>
        </div>
        <span className={document.overridden ? "is-overridden" : ""}>
          {document.overridden ? "관리자 수정값" : "제품 기본값"}
        </span>
      </header>
      <textarea
        value={draft}
        rows={18}
        maxLength={40_000}
        aria-label={`${document.name} 내용`}
        onChange={(event) => {
          setDraft(event.currentTarget.value);
          setResetArmed(false);
          setNotice(null);
        }}
      />
      <footer>
        <div>
          <button
            className={resetArmed ? "is-reset-armed" : ""}
            type="button"
            disabled={!document.overridden || saving}
            onClick={reset}
          >
            {resetArmed ? <AlertTriangle size={13} /> : <RotateCcw size={13} />}
            {resetArmed ? "한 번 더 눌러 기본값 복원" : "기본값 복원"}
          </button>
          <small>{draft.length.toLocaleString()} / 40,000</small>
        </div>
        <button
          className="primary-compact lumina-primary-action"
          type="button"
          disabled={saving || !draft.trim() || draft === document.content}
          onClick={() => void update(draft)}
        >
          {saving ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />}
          저장
        </button>
      </footer>
      {notice && <p className="instruction-message" aria-live="polite">{notice}</p>}
      {error && <p className="instruction-message is-error" aria-live="polite">{error}</p>}
    </section>
  );
}

function ReadOnlyPrompt({
  heading,
  description,
  content,
  note,
  applied = true,
}: {
  heading: string;
  description: string;
  content: string;
  note: string;
  applied?: boolean;
}) {
  return (
    <section className="runtime-prompt-editor is-readonly">
      <header>
        <div>
          <span className="runtime-prompt-kicker">선택 프로젝트 기준</span>
          <h2>{heading}</h2>
          <p>{description}</p>
        </div>
        <span className={applied ? "is-applied" : "is-excluded"}>
          {applied ? <><Check size={11} /> 적용</> : "적용 제외"}
        </span>
      </header>
      <textarea
        value={content}
        rows={15}
        readOnly
        aria-label={`${heading} 내용`}
        placeholder="저장된 내용이 없습니다."
      />
      <footer><small>{note}</small><small>{content.length.toLocaleString()}자</small></footer>
    </section>
  );
}

export function OrganizationInstructionsPanel() {
  const [history, setHistory] = useState<AdminAuditEvent[]>([]);
  const [current, setCurrent] = useState<InstructionDocument | null>(null);
  const [runtimePrompts, setRuntimePrompts] = useState<RuntimePromptDocument[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [projectInstruction, setProjectInstruction] = useState<InstructionDocument | null>(null);
  const [personalInstruction, setPersonalInstruction] = useState<InstructionDocument | null>(null);
  const [selectedLayer, setSelectedLayer] = useState<PromptLayerKey>("organization");
  const [showComposition, setShowComposition] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [selectedRevision, setSelectedRevision] = useState<number | null>(null);
  const [editingName, setEditingName] = useState(false);
  const [labelDraft, setLabelDraft] = useState("");
  const [selectedContent, setSelectedContent] = useState<string | null>(null);
  const [selectedContentOriginal, setSelectedContentOriginal] = useState<string | null>(null);
  const [selectedContentLoading, setSelectedContentLoading] = useState(false);
  const [selectedContentError, setSelectedContentError] = useState<string | null>(null);
  const [selectedContentSaving, setSelectedContentSaving] = useState(false);
  const [editingContent, setEditingContent] = useState(false);
  const [activatingRevision, setActivatingRevision] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    void Promise.all([
      api.admin.listAuditEvents({
        action: "organization_instructions_changed",
        targetType: "organization_instructions",
        limit: 50,
      }, controller.signal),
      api.instructions.getOrganization(controller.signal),
      api.instructions.listRuntimePrompts(controller.signal),
      api.projects.list(controller.signal),
      api.instructions.getPersonal(controller.signal),
    ]).then(([result, document, prompts, projectList, personal]) => {
      setHistory(result.items);
      setCurrent(document);
      setRuntimePrompts(prompts);
      setProjects(projectList);
      setPersonalInstruction(personal);
      setSelectedRevision((revision) => revision ?? document.revision);
      setSelectedProjectId((projectId) => {
        if (projectId && projectList.some((project) => project.id === projectId)) return projectId;
        return (projectList.find((project) => project.isDefault) ?? projectList[0])?.id ?? "";
      });
    }).catch((error) => {
      if (!controller.signal.aborted) {
        setLoadError(error instanceof Error ? error.message : "프롬프트 구성을 불러오지 못했습니다.");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [historyRevision]);

  useEffect(() => {
    if (!selectedProjectId) {
      setProjectInstruction(null);
      return;
    }
    const controller = new AbortController();
    void api.instructions.getProject(selectedProjectId, controller.signal)
      .then(setProjectInstruction)
      .catch(() => {
        if (!controller.signal.aborted) setProjectInstruction(null);
      });
    return () => controller.abort();
  }, [selectedProjectId]);

  useEffect(() => {
    if (!current || selectedRevision === null) return;
    if (selectedRevision === current.revision) {
      setSelectedContent(current.content);
      setSelectedContentOriginal(current.content);
      setSelectedContentError(null);
      setSelectedContentLoading(false);
      return;
    }
    const controller = new AbortController();
    setSelectedContent(null);
    setSelectedContentError(null);
    setSelectedContentLoading(true);
    void api.instructions.getOrganizationRevision(selectedRevision, controller.signal)
      .then((revision) => {
        setSelectedContent(revision.content);
        setSelectedContentOriginal(revision.content);
      })
      .catch((error) => {
        if (!controller.signal.aborted) setSelectedContentError(error instanceof Error ? error.message : "이전 revision을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSelectedContentLoading(false);
      });
    return () => controller.abort();
  }, [current, selectedRevision]);

  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const systemPrompt = runtimePrompts.find((prompt) => prompt.key === "system") ?? null;
  const agentPrompt = runtimePrompts.find((prompt) => prompt.key === "agent_default") ?? null;
  const personalApplied = selectedProject?.projectType === "personal";
  const projectOptions = projects.map((project) => ({
    value: project.id,
    label: project.name,
  }));

  const updateRuntimePrompt = (updated: RuntimePromptDocument) => {
    setRuntimePrompts((documents) => documents.map((document) => document.key === updated.key ? updated : document));
  };

  const deleteCurrent = async () => {
    if (!current || deleting || !current.content) return;
    if (!deleteArmed) {
      setDeleteArmed(true);
      setDeleteError(null);
      return;
    }
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.instructions.updateOrganization({
        content: "",
        expectedRevision: current.revision,
        expectedDigest: current.digest,
      });
      setDeleteArmed(false);
      setHistoryRevision((value) => value + 1);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "기본 지침을 삭제하지 못했습니다.");
    } finally {
      setDeleting(false);
    }
  };

  const saveSelectedContent = async () => {
    if (selectedRevision === null || selectedContent === null || selectedContentSaving) return;
    setSelectedContentSaving(true);
    setSelectedContentError(null);
    try {
      const updated = await api.instructions.updateOrganizationRevision(selectedRevision, selectedContent);
      setSelectedContent(updated.content);
      setSelectedContentOriginal(updated.content);
      setEditingContent(false);
    } catch (error) {
      setSelectedContentError(error instanceof Error ? error.message : "수정한 지침을 저장하지 못했습니다.");
    } finally {
      setSelectedContentSaving(false);
    }
  };

  const activateSelectedContent = async () => {
    if (!current || selectedContent === null || activatingRevision) return;
    setActivatingRevision(true);
    setSelectedContentError(null);
    try {
      const updated = await api.instructions.updateOrganization({
        content: selectedContent,
        expectedRevision: current.revision,
        expectedDigest: current.digest,
      });
      setSelectedRevision(updated.revision);
      setEditingContent(false);
      setHistoryRevision((value) => value + 1);
    } catch (error) {
      setSelectedContentError(error instanceof Error ? error.message : "선택한 revision을 활성화하지 못했습니다.");
    } finally {
      setActivatingRevision(false);
    }
  };

  const revisionLabel = (revision: number) => current?.revisionLabels?.[String(revision)] || `rev.${revision}`;
  const beginRename = () => {
    if (selectedRevision === null) return;
    setEditingName(true);
    setLabelDraft(revisionLabel(selectedRevision));
  };
  const saveRename = async (revision: number) => {
    const normalized = labelDraft.trim();
    const storedLabel = normalized === `rev.${revision}` ? "" : normalized;
    setEditingName(false);
    try {
      const updated = await api.instructions.updateOrganizationRevisionLabel(revision, storedLabel);
      setCurrent((document) => document ? {
        ...document,
        revisionLabels: { ...(document.revisionLabels ?? {}), [String(revision)]: updated.label },
      } : document);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "revision 이름을 저장하지 못했습니다.");
    }
  };

  const currentEvent = current ? history.find((event) => Number(event.metadata.revision) === current.revision) : undefined;
  const isCurrentSelection = selectedRevision === current?.revision;

  const selectLayer = (layer: PromptLayerKey) => {
    setSelectedLayer(layer);
    setDeleteArmed(false);
    setEditingName(false);
    setEditingContent(false);
  };

  const layerButton = (
    key: PromptLayerKey,
    icon: ReactNode,
    name: string,
    meta: string,
    applied = true,
  ) => (
    <button
      className={selectedLayer === key ? "is-selected" : ""}
      type="button"
      aria-pressed={selectedLayer === key}
      onClick={() => selectLayer(key)}
    >
      {icon}
      <span><strong>{name}</strong><small>{meta}</small></span>
      {applied ? <Check size={13} /> : <span className="is-excluded">제외</span>}
    </button>
  );

  if (loading) return <div className="admin-prompt-state"><LoaderCircle className="is-running" size={16} /> 프롬프트 구성을 불러오는 중입니다.</div>;
  if (loadError) return <div className="admin-prompt-state is-error">{loadError}</div>;

  return (
    <div className="admin-prompt-layout">
      <aside className="admin-prompt-sidebar" aria-label="프롬프트 계층">
        <header>
          <div><Layers3 size={14} /><strong>프롬프트 계층</strong></div>
          <button
            className="tooltip-control"
            type="button"
            aria-label={showComposition ? "전체 프롬프트 합성 구조 닫기" : "전체 프롬프트 합성 구조 보기"}
            aria-expanded={showComposition}
            data-tooltip={showComposition ? "합성 구조 닫기" : "합성 구조 보기"}
            onClick={() => setShowComposition((value) => !value)}
          >
            <CircleHelp size={14} />
          </button>
        </header>
        <div className="admin-prompt-layer-group">
          <span>공통 실행</span>
          {layerButton("system", <ShieldCheck size={14} />, "Lumina 고정 system prompt", systemPrompt?.overridden ? `관리자 수정값 · rev.${systemPrompt.revision}` : "제품 기본값")}
          {layerButton("organization", <BookOpen size={14} />, "관리자 기본 지침", current ? `조직 정책 · rev.${current.revision}` : "조직 정책")}
          {layerButton("agent_default", <Sparkles size={14} />, "내장 Agent 기본 지침", agentPrompt?.overridden ? `관리자 수정값 · rev.${agentPrompt.revision}` : "제품 기본값")}
        </div>
        <div className="admin-prompt-layer-group">
          <span>프로젝트 기준</span>
          {layerButton("concept", <FileText size={14} />, "프로젝트 Concept", selectedProject?.name ?? "선택된 프로젝트 없음", Boolean(selectedProject))}
          {layerButton("project", <FileText size={14} />, "프로젝트 지침", "프로젝트 설정에서 수정", Boolean(selectedProject))}
          {layerButton("personal", <UserRound size={14} />, "개인 지침", personalApplied ? "개인 프로젝트에 적용" : "공유 프로젝트에서는 제외", personalApplied)}
        </div>
        {selectedLayer === "organization" && current && (
          <section className="admin-prompt-history" aria-label="관리자 기본 지침 변경 이력">
            <header><History size={12} /><strong>변경 이력</strong></header>
            <article className={selectedRevision === current.revision ? "is-selected" : ""} role="button" tabIndex={0} onClick={() => setSelectedRevision(current.revision)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedRevision(current.revision); }}>
              <div><strong>{revisionLabel(current.revision)}</strong><em>현재</em><button className={`tooltip-control ${deleteArmed ? "is-delete-armed" : ""}`} type="button" aria-label={!current.content ? "삭제할 기본 지침 없음" : deleteArmed ? "기본 지침 삭제 확인, 한 번 더 누르면 삭제" : "기본 지침 삭제"} data-tooltip={!current.content ? "삭제할 내용 없음" : deleteArmed ? "한 번 더 눌러 삭제" : "삭제"} disabled={deleting || !current.content} onClick={(event) => { event.stopPropagation(); void deleteCurrent(); }}>{deleting ? <LoaderCircle className="is-running" size={12} /> : deleteArmed ? <AlertTriangle size={12} /> : <Trash2 size={12} />}</button></div>
              <small>{currentEvent?.actorLoginId ?? "시스템"}</small>
              <time dateTime={current.updatedAt}>{formatHistoryDate(current.updatedAt)}</time>
            </article>
            {deleteError && <p className="is-error">{deleteError}</p>}
            {history.filter((event) => Number(event.metadata.revision) !== current.revision).map((event) => (
              <article className={selectedRevision === Number(event.metadata.revision) ? "is-selected" : ""} role="button" tabIndex={0} key={event.id} onClick={() => setSelectedRevision(Number(event.metadata.revision))} onKeyDown={(keyEvent) => { if (keyEvent.key === "Enter" || keyEvent.key === " ") setSelectedRevision(Number(event.metadata.revision)); }}>
                <div><strong>{revisionLabel(Number(event.metadata.revision))}</strong></div>
                <small>{event.actorLoginId ?? "시스템"}</small>
                <time dateTime={event.createdAt}>{formatHistoryDate(event.createdAt)}</time>
              </article>
            ))}
          </section>
        )}
      </aside>

      <div className="admin-policy-panel">
        <div className="admin-prompt-toolbar">
          <span>미리보기 기준</span>
          <SelectMenu
            value={selectedProjectId}
            options={projectOptions}
            ariaLabel="프롬프트 미리보기 프로젝트"
            disabled={projectOptions.length === 0}
            onChange={setSelectedProjectId}
          />
          <small>Project·개인 레이어는 여기서 읽기만 합니다.</small>
        </div>

        {showComposition && (
          <section className="admin-prompt-composition" aria-label="전체 프롬프트 합성 구조">
            <header>
              <div><CircleHelp size={15} /><h2>실제 Run 프롬프트 합성 구조</h2></div>
              <button type="button" aria-label="전체 프롬프트 합성 구조 닫기" onClick={() => setShowComposition(false)}><ChevronUp size={14} /> 접기</button>
            </header>
            <ol>
              <li><strong>고정 system</strong><span>Lumina의 기본 행동, 진행 표시, Plan과 사용자 노출 안전 계약</span></li>
              <li><strong>저장 지침 계층</strong><span>관리자 → Agent 기본 → 프로젝트 지침 → 개인 지침 순서, 공유 프로젝트는 개인 지침 제외</span></li>
              <li><strong>프로젝트 Context</strong><span>선택 Project의 Concept과 고정된 revision</span></li>
              <li><strong>선택 Skill</strong><span>명시 선택·자동 선택·예약 작업에서 고정된 Skill 지침</span></li>
              <li><strong>현재 Turn 계약</strong><span>Chat/File 출력 모드, Skill 활성화, Artifact 형식·길이 조건</span></li>
              <li><strong>복구 Context</strong><span>압축 요약, 보존 Tool 결과와 미완료 작업 상태</span></li>
              <li><strong>대화와 Memory</strong><span>대화 이력 뒤 현재 사용자 Message에 관련 Memory와 첨부 Context 결합</span></li>
              <li><strong>Provider 경계</strong><span>Provider별 protocol로 변환하며 Codex는 별도 base instructions와 구조화 출력 계약 적용</span></li>
            </ol>
            <p>모든 변경은 새 Run부터 적용되고, 시작된 Run은 revision·digest snapshot을 계속 사용합니다.</p>
          </section>
        )}

        {selectedLayer === "system" && systemPrompt && <RuntimePromptEditor document={systemPrompt} onUpdated={updateRuntimePrompt} />}
        {selectedLayer === "agent_default" && agentPrompt && <RuntimePromptEditor document={agentPrompt} onUpdated={updateRuntimePrompt} />}
        {selectedLayer === "concept" && <ReadOnlyPrompt heading="프로젝트 Concept" description={`${selectedProject?.name ?? "선택된 프로젝트"}의 목적, 용어와 업무 배경입니다.`} content={selectedProject?.concept ?? ""} note="프로젝트 설정의 업무 Concept에서 수정합니다." applied={Boolean(selectedProject)} />}
        {selectedLayer === "project" && <ReadOnlyPrompt heading="프로젝트 지침" description={`${selectedProject?.name ?? "선택된 프로젝트"}의 모든 Run에 적용되는 작업 방식입니다.`} content={projectInstruction?.content ?? ""} note="프로젝트 설정의 프로젝트 지침에서 수정합니다." applied={Boolean(selectedProject)} />}
        {selectedLayer === "personal" && <ReadOnlyPrompt heading="개인 지침" description="현재 관리자 계정의 개인 전역 지침입니다." content={personalInstruction?.content ?? ""} note={personalApplied ? "개인 프로젝트에서 프로젝트 지침 다음에 적용됩니다." : "공유 프로젝트에서는 개인 지침을 합성하지 않습니다."} applied={personalApplied} />}

        {selectedLayer === "organization" && selectedRevision !== null && (
          <>
            <div className="admin-policy-revision-editor">
              {editingName ? (
                <>
                  <input value={labelDraft} maxLength={80} autoFocus aria-label={`rev.${selectedRevision} 이름`} onChange={(event) => setLabelDraft(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === "Enter") void saveRename(selectedRevision); if (event.key === "Escape") setEditingName(false); }} />
                  <button className="primary-compact lumina-primary-action" type="button" onClick={() => void saveRename(selectedRevision)}><Save size={13} /> 저장</button>
                  <button type="button" onClick={() => setEditingName(false)}><X size={13} /> 취소</button>
                </>
              ) : (
                <>
                  <div><strong>{revisionLabel(selectedRevision)}</strong><span>rev.{selectedRevision}</span></div>
                  <button type="button" onClick={beginRename}><Pencil size={13} /> 이름 편집</button>
                </>
              )}
            </div>
            {isCurrentSelection ? (
              <InstructionEditor key={historyRevision} scope="organization" heading="관리자 기본 지침" description="모든 프로젝트와 Run에서 내장 Agent 기본 지침보다 먼저 적용되는 조직 정책입니다." note="변경 이력은 모니터링 로그에 기록되고 새 Run부터 적용됩니다." onSaved={() => setHistoryRevision((value) => value + 1)} />
            ) : (
              <section className="admin-policy-revision-preview" aria-live="polite">
                <header>
                  <div><h2>{revisionLabel(selectedRevision)}</h2><span>과거 revision · rev.{selectedRevision}</span></div>
                  <div>
                    {editingContent ? (
                      <><button className="primary-compact" type="button" disabled={selectedContentSaving || selectedContent === selectedContentOriginal} onClick={() => void saveSelectedContent()}>{selectedContentSaving ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />} 저장</button><button type="button" onClick={() => { setSelectedContent(selectedContentOriginal); setEditingContent(false); }}><X size={13} /> 취소</button></>
                    ) : (
                      <><button type="button" onClick={() => setEditingContent(true)}><Pencil size={13} /> 내용 편집</button><button className="primary-compact" type="button" disabled={activatingRevision} onClick={() => void activateSelectedContent()}>{activatingRevision ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />} 이 버전 활성화</button></>
                    )}
                  </div>
                </header>
                {selectedContentLoading && <p><LoaderCircle className="is-running" size={14} /> 이전 지침을 불러오는 중입니다.</p>}
                {selectedContentError && <p className="is-error">{selectedContentError}</p>}
                {!selectedContentLoading && selectedContent !== null && <><textarea value={selectedContent} rows={14} maxLength={40_000} readOnly={!editingContent} aria-label={`rev.${selectedRevision} 지침 내용`} onChange={(event) => setSelectedContent(event.currentTarget.value)} /><footer><small>{editingContent ? "선택한 과거 revision의 내용을 직접 수정합니다." : "내용 편집 또는 현재 지침으로 활성화할 수 있습니다."}</small><span>{selectedContent.length.toLocaleString()} / 40,000</span></footer></>}
              </section>
            )}
          </>
        )}
        {!showComposition && <button className="admin-prompt-composition-shortcut" type="button" onClick={() => setShowComposition(true)}><ChevronDown size={13} /> 전체 프롬프트가 어떻게 합쳐지는지 보기</button>}
      </div>
    </div>
  );
}
