import { AlertTriangle, History, LoaderCircle, Pencil, Save, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AdminAuditEvent, InstructionDocument } from "../api-types";
import { InstructionEditor } from "./InstructionEditor";

function formatHistoryDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

export function OrganizationInstructionsPanel() {
  const [history, setHistory] = useState<AdminAuditEvent[]>([]);
  const [current, setCurrent] = useState<InstructionDocument | null>(null);
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
    void Promise.all([
      api.admin.listAuditEvents({
        action: "organization_instructions_changed",
        targetType: "organization_instructions",
        limit: 50,
      }, controller.signal),
      api.instructions.getOrganization(controller.signal),
    ]).then(([result, document]) => {
      setHistory(result.items);
      setCurrent(document);
      setSelectedRevision((revision) => revision ?? document.revision);
    }).catch(() => {
      if (!controller.signal.aborted) {
        setHistory([]);
        setCurrent(null);
      }
    });
    return () => controller.abort();
  }, [historyRevision]);

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
        revisionLabels: {
          ...(document.revisionLabels ?? {}),
          [String(revision)]: updated.label,
        },
      } : document);
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : "revision 이름을 저장하지 못했습니다.");
    }
  };

  const currentEvent = current
    ? history.find((event) => Number(event.metadata.revision) === current.revision)
    : undefined;
  const isCurrentSelection = selectedRevision === current?.revision;

  return (
    <div className="admin-policy-layout">
      <aside className="admin-policy-history" aria-label="기본 지침 변경 이력">
        <header><History size={13} /><strong>변경 이력</strong></header>
        {current && (
          <article className={`is-current ${selectedRevision === current.revision ? "is-selected" : ""}`} role="button" tabIndex={0} onClick={() => { setSelectedRevision(current.revision); setEditingName(false); setEditingContent(false); }} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setSelectedRevision(current.revision); }}>
            <div>
              <strong>{revisionLabel(current.revision)}</strong>
              <em>현재</em>
              <button className={`tooltip-control ${deleteArmed ? "is-delete-armed" : ""}`} type="button" aria-label={!current.content ? "삭제할 기본 지침 없음" : deleteArmed ? "기본 지침 삭제 확인, 한 번 더 누르면 삭제" : "기본 지침 삭제"} data-tooltip={!current.content ? "삭제할 내용 없음" : deleteArmed ? "한 번 더 눌러 삭제" : "삭제"} disabled={deleting || !current.content} onClick={() => void deleteCurrent()}>{deleting ? <LoaderCircle className="is-running" size={12} /> : deleteArmed ? <AlertTriangle size={12} /> : <Trash2 size={12} />}</button>
            </div>
            <small>{currentEvent?.actorLoginId ?? "시스템"}</small>
            <time dateTime={current.updatedAt}>{formatHistoryDate(current.updatedAt)}</time>
          </article>
        )}
        {!current && history.length === 0 && <p>저장 이력이 없습니다.</p>}
        {deleteError && <p className="is-error">{deleteError}</p>}
        {history.filter((event) => Number(event.metadata.revision) !== current?.revision).map((event) => (
          <article className={selectedRevision === Number(event.metadata.revision) ? "is-selected" : ""} role="button" tabIndex={0} key={event.id} onClick={() => { setSelectedRevision(Number(event.metadata.revision)); setEditingName(false); setEditingContent(false); }} onKeyDown={(keyEvent) => { if (keyEvent.key === "Enter" || keyEvent.key === " ") setSelectedRevision(Number(event.metadata.revision)); }}>
            <div><strong>{revisionLabel(Number(event.metadata.revision))}</strong></div>
            <small>{event.actorLoginId ?? "시스템"}</small>
            <time dateTime={event.createdAt}>{formatHistoryDate(event.createdAt)}</time>
          </article>
        ))}
      </aside>
      <div className="admin-policy-panel">
        {selectedRevision !== null && (
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
        )}
        {isCurrentSelection ? (
          <InstructionEditor
            key={historyRevision}
            scope="organization"
            heading="기본 지침"
            description="모든 프로젝트와 Run에 가장 먼저 적용되는 관리자 정책입니다."
            note="개인·프로젝트 지침보다 우선하며 변경 이력은 모니터링 로그에 기록됩니다."
            onSaved={() => setHistoryRevision((value) => value + 1)}
          />
        ) : (
          <section className="admin-policy-revision-preview" aria-live="polite">
            <header>
              <div><h2>{revisionLabel(selectedRevision ?? 0)}</h2><span>과거 revision · rev.{selectedRevision}</span></div>
              <div>
                {editingContent ? (
                  <>
                    <button className="primary-compact" type="button" disabled={selectedContentSaving || selectedContent === selectedContentOriginal} onClick={() => void saveSelectedContent()}>{selectedContentSaving ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />} 저장</button>
                    <button type="button" onClick={() => { setSelectedContent(selectedContentOriginal); setEditingContent(false); }}><X size={13} /> 취소</button>
                  </>
                ) : (
                  <>
                    <button type="button" onClick={() => setEditingContent(true)}><Pencil size={13} /> 내용 편집</button>
                    <button className="primary-compact" type="button" disabled={activatingRevision} onClick={() => void activateSelectedContent()}>{activatingRevision ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />} 이 버전 활성화</button>
                  </>
                )}
              </div>
            </header>
            {selectedContentLoading && <p><LoaderCircle className="is-running" size={14} /> 이전 지침을 불러오는 중입니다.</p>}
            {selectedContentError && <p className="is-error">{selectedContentError}</p>}
            {!selectedContentLoading && selectedContent !== null && (
              <>
                <textarea value={selectedContent ?? ""} rows={14} maxLength={40_000} readOnly={!editingContent} aria-label={`rev.${selectedRevision} 지침 내용`} onChange={(event) => setSelectedContent(event.currentTarget.value)} />
                <footer><small>{editingContent ? "선택한 과거 revision의 내용을 직접 수정합니다." : "내용 편집 또는 현재 지침으로 활성화할 수 있습니다."}</small><span>{(selectedContent ?? "").length.toLocaleString()} / 40,000</span></footer>
              </>
            )}
          </section>
        )}
      </div>
    </div>
  );
}
