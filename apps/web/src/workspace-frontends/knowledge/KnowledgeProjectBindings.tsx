import { Folder, Link2, LoaderCircle, LockKeyhole, Plus, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api } from "../../api";
import type { KnowledgeProjectBinding, KnowledgeRevision, ProjectSummary } from "../../api-types";
import { SelectMenu } from "../../components/SelectMenu";
import { formatDate } from "./knowledge-utils";

interface KnowledgeProjectBindingsProps {
  spaceId: string;
  onError: (error: unknown) => void;
}

export function KnowledgeProjectBindings({ spaceId, onError }: KnowledgeProjectBindingsProps) {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [revisions, setRevisions] = useState<KnowledgeRevision[]>([]);
  const [bindings, setBindings] = useState<KnowledgeProjectBinding[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedRevisionId, setSelectedRevisionId] = useState("");
  const [loading, setLoading] = useState(true);
  const [savingBindingId, setSavingBindingId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const writableProjects = useMemo(
    () => projects.filter((project) => project.role !== "viewer"),
    [projects],
  );
  const boundProjectIds = useMemo(
    () => new Set(bindings.map((binding) => binding.projectId)),
    [bindings],
  );
  const availableProjects = writableProjects.filter((project) => !boundProjectIds.has(project.id));
  const projectOptions = availableProjects.map((project) => ({ value: project.id, label: project.name }));
  const revisionOptions = revisions.map((revision) => ({
    value: revision.id,
    label: `revision ${revision.revisionNumber} · ${revision.changeSummary || "승인된 변경"}`,
  }));

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    Promise.all([
      api.projects.list(controller.signal),
      api.knowledge.listRevisions(spaceId, controller.signal),
      api.knowledge.listProjectBindings(spaceId, controller.signal),
    ])
      .then(([nextProjects, nextRevisions, nextBindings]) => {
        if (controller.signal.aborted) return;
        setProjects(nextProjects);
        setRevisions(nextRevisions);
        setBindings(nextBindings);
        const boundIds = new Set(nextBindings.map((binding) => binding.projectId));
        setSelectedProjectId(nextProjects.find((project) => project.role !== "viewer" && !boundIds.has(project.id))?.id ?? "");
        setSelectedRevisionId(nextRevisions[0]?.id ?? "");
      })
      .catch((error) => {
        if (!controller.signal.aborted) onError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [onError, spaceId]);

  async function createBinding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedProjectId || !selectedRevisionId || savingBindingId) return;
    setSavingBindingId("new");
    try {
      const created = await api.knowledge.createProjectBinding(spaceId, {
        projectId: selectedProjectId,
        knowledgeRevisionId: selectedRevisionId,
      });
      const nextBindings = [...bindings, created];
      setBindings(nextBindings);
      const nextBoundIds = new Set(nextBindings.map((binding) => binding.projectId));
      setSelectedProjectId(writableProjects.find((project) => !nextBoundIds.has(project.id))?.id ?? "");
    } catch (error) {
      onError(error);
    } finally {
      setSavingBindingId(null);
    }
  }

  async function updateBinding(binding: KnowledgeProjectBinding, knowledgeRevisionId: string) {
    if (knowledgeRevisionId === binding.knowledgeRevision.id || savingBindingId) return;
    setSavingBindingId(binding.id);
    try {
      const updated = await api.knowledge.updateProjectBinding(binding.id, {
        expectedRevision: binding.bindingRevision,
        knowledgeRevisionId,
      });
      setBindings((current) => current.map((item) => item.id === updated.id ? updated : item));
    } catch (error) {
      onError(error);
    } finally {
      setSavingBindingId(null);
    }
  }

  async function deleteBinding(binding: KnowledgeProjectBinding) {
    if (confirmDeleteId !== binding.id || savingBindingId) return;
    setSavingBindingId(binding.id);
    try {
      await api.knowledge.deleteProjectBinding(binding.id, binding.bindingRevision);
      const nextBindings = bindings.filter((item) => item.id !== binding.id);
      setBindings(nextBindings);
      setConfirmDeleteId(null);
      const nextBoundIds = new Set(nextBindings.map((item) => item.projectId));
      setSelectedProjectId((current) => current || writableProjects.find((project) => !nextBoundIds.has(project.id))?.id || "");
    } catch (error) {
      onError(error);
      setConfirmDeleteId(null);
    } finally {
      setSavingBindingId(null);
    }
  }

  return (
    <section className="knowledge-card knowledge-project-binding-card">
      <header><div><strong><Link2 size={15} /> Project 연결</strong><small>Project가 사용할 승인 Knowledge revision을 명시적으로 고정합니다.</small></div><span>{bindings.length}개 연결</span></header>
      {loading ? <div className="knowledge-loading"><LoaderCircle className="is-running" size={14} /> 연결 정보를 불러오는 중</div> : <>
        {revisions.length === 0 ? <p className="knowledge-binding-empty"><LockKeyhole size={15} /> 승인된 Statement가 생기면 Project에 고정할 revision을 선택할 수 있습니다.</p> : <>
          {availableProjects.length > 0 && <form className="knowledge-binding-create" onSubmit={createBinding}>
            <label>Project<SelectMenu size="small" value={selectedProjectId} options={projectOptions} ariaLabel="Knowledge를 연결할 Project" onChange={setSelectedProjectId} /></label>
            <label>고정 revision<SelectMenu size="small" value={selectedRevisionId} options={revisionOptions} ariaLabel="Project에 고정할 Knowledge revision" onChange={setSelectedRevisionId} /></label>
            <button type="submit" disabled={!selectedProjectId || !selectedRevisionId || savingBindingId !== null}>{savingBindingId === "new" ? <LoaderCircle className="is-running" size={13} /> : <Plus size={13} />} 연결</button>
          </form>}
          {bindings.length > 0 ? <div className="knowledge-binding-list">{bindings.map((binding) => <div key={binding.id}>
            <Folder size={16} />
            <span><strong>{binding.projectName}</strong><small>read · 수동 고정 · 연결 {formatDate(binding.createdAt)}</small></span>
            <SelectMenu className="knowledge-binding-revision" size="small" width="auto" align="end" value={binding.knowledgeRevision.id} options={revisionOptions} ariaLabel={`${binding.projectName}의 고정 Knowledge revision`} disabled={savingBindingId !== null} onChange={(value) => updateBinding(binding, value)} />
            {confirmDeleteId === binding.id ? <div className="knowledge-binding-confirm"><span>연결을 해제할까요?</span><button type="button" onClick={() => setConfirmDeleteId(null)}><X size={12} /> 취소</button><button type="button" disabled={savingBindingId !== null} onClick={() => deleteBinding(binding)}>{savingBindingId === binding.id ? <LoaderCircle className="is-running" size={12} /> : <Trash2 size={12} />} 해제</button></div> : <button className="knowledge-binding-delete" type="button" aria-label={`${binding.projectName} Knowledge 연결 해제`} onClick={() => setConfirmDeleteId(binding.id)}><Trash2 size={13} /></button>}
          </div>)}</div> : <p className="knowledge-binding-empty"><Link2 size={15} /> 아직 연결된 Project가 없습니다. revision을 선택해 첫 연결을 만드세요.</p>}
        </>}
      </>}
      <footer><LockKeyhole size={13} /><span>새 revision은 자동 반영되지 않습니다. 위 선택을 직접 변경할 때만 Project의 고정 지식이 바뀝니다.</span></footer>
    </section>
  );
}
