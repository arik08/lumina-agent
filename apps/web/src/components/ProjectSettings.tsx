import { AlertTriangle, Archive, Check, FileText, Folder, FolderPlus, LoaderCircle, Menu, Save } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import type { ProjectSummary } from "../api-types";
import { InstructionEditor } from "./InstructionEditor";

interface ProjectSettingsProps {
  projects: ProjectSummary[];
  project: ProjectSummary | null;
  onOpenNavigation: () => void;
  onSelect: (projectId: string) => void;
  onCreate: () => Promise<unknown>;
  onSave: (projectId: string, changes: { name: string; description: string; concept: string }) => Promise<unknown>;
  onDelete: (projectId: string) => Promise<boolean>;
}

export function ProjectSettings({ projects, project, onOpenNavigation, onSelect, onCreate, onSave, onDelete }: ProjectSettingsProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [concept, setConcept] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [personalSelected, setPersonalSelected] = useState(false);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    setName(project?.name ?? "");
    setDescription(project?.description ?? "");
    setConcept(project?.concept ?? "");
    setDeleteArmed(false);
  }, [project]);

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!project || !name.trim()) return;
    setDeleteArmed(false);
    setBusy(true);
    try {
      await onSave(project.id, { name: name.trim(), description: description.trim(), concept });
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!project || project.isDefault) return;
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    setBusy(true);
    try {
      await onDelete(project.id);
    } finally {
      setBusy(false);
      setDeleteArmed(false);
    }
  };

  return (
    <main className="feature-view project-settings-view" aria-label="프로젝트 설정">
      <header className="workspace-view-header">
        <button className="mobile-menu-button" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={19} /></button>
        <div><h1>프로젝트 설정</h1><p>프로젝트를 추가·삭제하고 프로젝트별 정보와 지침을 관리합니다.</p></div>
      </header>
      <div className="project-settings-layout">
        <aside className="project-manager-list" aria-label="프로젝트 목록">
          <header><strong>프로젝트 목록</strong><button className="tooltip-control" type="button" aria-label="프로젝트 추가" data-tooltip="프로젝트 추가" disabled={creating} onClick={() => {
            setCreating(true);
            void onCreate().finally(() => setCreating(false));
          }}>{creating ? <LoaderCircle className="is-running" size={15} /> : <FolderPlus size={15} />}</button></header>
          <div>
            <button className={personalSelected ? "is-selected" : ""} type="button" onClick={() => setPersonalSelected(true)}>
              <FileText size={15} /><span><strong>개인 지침</strong><small>프로젝트 무관 · 개인 전역</small></span>{personalSelected && <Check size={14} />}
            </button>
            {projects.map((item) => (
              <button className={!personalSelected && item.id === project?.id ? "is-selected" : ""} type="button" key={item.id} onClick={() => { setPersonalSelected(false); onSelect(item.id); }}>
                <Folder size={15} /><span><strong>{item.name}</strong><small>{item.isDefault ? "기본 프로젝트" : item.projectType === "shared" ? "공유 프로젝트" : "개인 프로젝트"}</small></span>{!personalSelected && item.id === project?.id && <Check size={14} />}
              </button>
            ))}
          </div>
        </aside>
        {personalSelected ? (
          <div className="project-settings-scroll">
            <InstructionEditor
              scope="personal"
              heading="개인 지침"
              description="현재 프로젝트 선택과 무관하게 개인 작업에 적용할 전역 프롬프트입니다."
              note="나만 볼 수 있으며 언제든 바로 수정할 수 있습니다. 공유 프로젝트에는 포함되지 않습니다."
            />
          </div>
        ) : !project ? <p className="workspace-empty">설정할 프로젝트가 없습니다.</p> : (
          <div className="project-settings-scroll">
            <form className="project-settings-form" onSubmit={(event) => void save(event)}>
              <header><h2>프로젝트 정보</h2><p>이름과 업무 배경을 관리합니다.</p></header>
              <label>이름<input value={name} maxLength={240} required onChange={(event) => setName(event.currentTarget.value)} /></label>
              <label>설명<input value={description} maxLength={1000} placeholder="프로젝트를 구분할 짧은 설명" onChange={(event) => setDescription(event.currentTarget.value)} /></label>
              <label>업무 Concept<textarea value={concept} rows={7} placeholder="목적, 용어, 배경 정보 등 새 Run에 제공할 맥락" onChange={(event) => setConcept(event.currentTarget.value)} /></label>
              <div className="project-settings-actions">
                {!project.isDefault && <button className={`text-danger ${deleteArmed ? "is-delete-armed" : ""}`} type="button" aria-label={deleteArmed ? "프로젝트 삭제 확인, 한 번 더 누르면 삭제" : "프로젝트 삭제"} disabled={busy} onClick={() => void remove()}>{busy ? <LoaderCircle className="is-running" size={15} /> : deleteArmed ? <AlertTriangle size={15} /> : <Archive size={15} />} {deleteArmed ? "한 번 더 눌러 삭제" : "프로젝트 삭제"}</button>}
                <button className="primary-compact lumina-primary-action" type="submit" disabled={busy || !name.trim()}>{busy ? <LoaderCircle className="is-running" size={15} /> : <Save size={15} />} 정보 저장</button>
              </div>
              {project.isDefault && <small>기본 프로젝트는 삭제할 수 없습니다.</small>}
            </form>
            <InstructionEditor
              scope="project"
              projectId={project.id}
              heading="프로젝트 지침"
              description="이 프로젝트의 모든 Run에 적용할 작업 방식과 산출물 원칙입니다."
              note="모든 구성원에게 같은 지침이 적용되며, 프로젝트를 편집할 수 있는 구성원은 언제든 수정할 수 있습니다."
            />
          </div>
        )}
      </div>
    </main>
  );
}
