import { AlertTriangle, Archive, Check, FileText, Folder, FolderPlus, LoaderCircle, Menu, Save, Trash2, UserPlus, Users } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ProjectMembership, ProjectRole, ProjectSummary } from "../api-types";
import { InstructionEditor } from "./InstructionEditor";
import { SelectMenu } from "./SelectMenu";
import "./ProjectSettings.css";

type AssignableRole = Exclude<ProjectRole, "owner">;

const roleLabels: Record<ProjectRole, string> = {
  owner: "소유자",
  admin: "관리자",
  member: "편집자",
  viewer: "조회자",
};

const assignableRoleOptions = (["member", "viewer", "admin"] as AssignableRole[])
  .map((role) => ({ value: role, label: roleLabels[role] }));

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

interface ProjectSettingsProps {
  projects: ProjectSummary[];
  project: ProjectSummary | null;
  onOpenNavigation: () => void;
  onSelect: (projectId: string) => void;
  onCreate: () => Promise<unknown>;
  onSave: (projectId: string, changes: { name: string; description: string; concept: string }) => Promise<unknown>;
  onDelete: (projectId: string) => Promise<boolean>;
  onMembershipsChanged: () => Promise<unknown>;
}

export function ProjectSettings({ projects, project, onOpenNavigation, onSelect, onCreate, onSave, onDelete, onMembershipsChanged }: ProjectSettingsProps) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [concept, setConcept] = useState("");
  const [busy, setBusy] = useState(false);
  const [deleteArmed, setDeleteArmed] = useState(false);
  const [personalSelected, setPersonalSelected] = useState(false);
  const [creating, setCreating] = useState(false);
  const [memberships, setMemberships] = useState<ProjectMembership[]>([]);
  const [membersLoading, setMembersLoading] = useState(false);
  const [memberActionId, setMemberActionId] = useState<string | null>(null);
  const [memberDeleteArmed, setMemberDeleteArmed] = useState<string | null>(null);
  const [memberMessage, setMemberMessage] = useState("");
  const [memberError, setMemberError] = useState("");
  const [accountLoginId, setAccountLoginId] = useState("");
  const [newRole, setNewRole] = useState<AssignableRole>("member");

  const canManageMembers = project?.role === "owner" || project?.role === "admin";
  const sortedMemberships = useMemo(
    () => [...memberships].sort((left, right) => {
      if (left.isProjectOwner !== right.isProjectOwner) return left.isProjectOwner ? -1 : 1;
      return left.displayName.localeCompare(right.displayName, "ko");
    }),
    [memberships],
  );
  const collaboratorCount = memberships.filter((membership) => !membership.isProjectOwner).length;

  const loadMemberships = useCallback(async (projectId: string, signal?: AbortSignal) => {
    const items = await api.projectMemberships.list(projectId, false, signal);
    setMemberships(items);
    return items;
  }, []);

  useEffect(() => {
    setName(project?.name ?? "");
    setDescription(project?.description ?? "");
    setConcept(project?.concept ?? "");
    setDeleteArmed(false);
    setMemberDeleteArmed(null);
    setMemberMessage("");
    setMemberError("");
    setAccountLoginId("");
    setMemberships([]);
    if (!project) {
      setMembersLoading(false);
      return;
    }
    const controller = new AbortController();
    setMembersLoading(true);
    void loadMemberships(project.id, controller.signal)
      .catch((error) => {
        if (!controller.signal.aborted) setMemberError(errorMessage(error));
      })
      .finally(() => {
        if (!controller.signal.aborted) setMembersLoading(false);
      });
    return () => controller.abort();
  }, [loadMemberships, project?.id]);

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

  const addMember = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const loginId = accountLoginId.trim();
    if (!project || !canManageMembers || !loginId) return;
    setMemberActionId("add");
    setMemberDeleteArmed(null);
    setMemberError("");
    setMemberMessage("");
    try {
      const added = await api.projectMemberships.add(project.id, { loginId, role: newRole });
      await Promise.all([loadMemberships(project.id), onMembershipsChanged()]);
      setAccountLoginId("");
      setMemberMessage(`${added.displayName} 계정을 추가했습니다.`);
    } catch (error) {
      setMemberError(errorMessage(error));
    } finally {
      setMemberActionId(null);
    }
  };

  const changeMemberRole = async (membership: ProjectMembership, role: AssignableRole) => {
    if (!project || !canManageMembers || membership.isProjectOwner || membership.role === role) return;
    setMemberActionId(membership.id);
    setMemberDeleteArmed(null);
    setMemberError("");
    setMemberMessage("");
    try {
      const updated = await api.projectMemberships.update(project.id, membership.id, {
        role,
        expectedRole: membership.role,
        expectedStatus: membership.status,
      });
      setMemberships((items) => items.map((item) => item.id === updated.id ? updated : item));
      setMemberMessage(`${updated.displayName} 계정의 권한을 변경했습니다.`);
    } catch (error) {
      setMemberError(errorMessage(error));
      await loadMemberships(project.id).catch(() => undefined);
    } finally {
      setMemberActionId(null);
    }
  };

  const removeMember = async (membership: ProjectMembership) => {
    if (!project || !canManageMembers || membership.isProjectOwner) return;
    if (memberDeleteArmed !== membership.id) {
      setMemberDeleteArmed(membership.id);
      setMemberMessage("");
      setMemberError("");
      return;
    }
    setMemberActionId(membership.id);
    setMemberError("");
    try {
      await api.projectMemberships.remove(
        project.id,
        membership.id,
        membership.role,
        membership.status,
      );
      await Promise.all([loadMemberships(project.id), onMembershipsChanged()]);
      setMemberDeleteArmed(null);
      setMemberMessage(`${membership.displayName} 계정을 제거했습니다.`);
    } catch (error) {
      setMemberError(errorMessage(error));
      await loadMemberships(project.id).catch(() => undefined);
    } finally {
      setMemberActionId(null);
    }
  };

  return (
    <main className="feature-view project-settings-view" aria-label="프로젝트 설정">
      <header className="workspace-view-header">
        <button className="mobile-menu-button" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={19} /></button>
        <div><h1>프로젝트 설정</h1><p>프로젝트 정보와 지침, 함께 일할 계정을 관리합니다.</p></div>
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

            <section className="project-membership-settings" aria-labelledby="project-membership-heading">
              <header>
                <div><h2 id="project-membership-heading">공유 및 구성원</h2><p>등록된 계정을 추가해 다른 부서의 동료와도 같은 프로젝트에서 작업할 수 있습니다.</p></div>
                <span className={collaboratorCount > 0 ? "is-shared" : ""}><Users size={13} /> {collaboratorCount > 0 ? `공유 · ${memberships.length}명` : "개인 프로젝트"}</span>
              </header>
              {canManageMembers && (
                <form className="project-member-add" onSubmit={(event) => void addMember(event)}>
                  <label><span>계정명</span><input type="email" value={accountLoginId} placeholder="name@posco.com" autoComplete="off" onChange={(event) => setAccountLoginId(event.currentTarget.value)} /></label>
                  <div className="project-role-field"><span>권한</span><SelectMenu value={newRole} options={assignableRoleOptions} ariaLabel="새 구성원 권한" disabled={memberActionId !== null} onChange={(role) => setNewRole(role as AssignableRole)} /></div>
                  <button className="primary-compact lumina-primary-action" type="submit" disabled={!accountLoginId.trim() || memberActionId !== null}>{memberActionId === "add" ? <LoaderCircle className="is-running" size={14} /> : <UserPlus size={14} />} 계정 추가</button>
                </form>
              )}
              <div className="project-member-list" aria-live="polite">
                {membersLoading ? <p className="project-member-state"><LoaderCircle className="is-running" size={14} /> 구성원을 불러오는 중입니다.</p> : sortedMemberships.map((membership) => {
                  const actionBusy = memberActionId === membership.id;
                  const removalArmed = memberDeleteArmed === membership.id;
                  const protectedOwner = membership.isProjectOwner || membership.role === "owner";
                  return (
                    <article key={membership.id}>
                      <span className="project-member-avatar" aria-hidden="true">{membership.displayName.trim().charAt(0).toUpperCase() || "?"}</span>
                      <span className="project-member-identity"><strong>{membership.displayName}</strong><small>{membership.loginId}</small></span>
                      {protectedOwner ? <span className="project-member-owner">소유자</span> : canManageMembers ? (
                        <SelectMenu className="project-member-role-select" size="small" align="end" value={membership.role} options={assignableRoleOptions} ariaLabel={`${membership.displayName} 권한`} disabled={actionBusy} onChange={(role) => void changeMemberRole(membership, role as AssignableRole)} />
                      ) : <span className="project-member-role">{roleLabels[membership.role]}</span>}
                      {!protectedOwner && canManageMembers && <button className={removalArmed ? "is-delete-armed" : ""} type="button" aria-label={removalArmed ? `${membership.displayName} 제거 확인, 한 번 더 누르면 제거` : `${membership.displayName} 제거`} disabled={actionBusy} onClick={() => void removeMember(membership)}>{actionBusy ? <LoaderCircle className="is-running" size={14} /> : removalArmed ? <AlertTriangle size={14} /> : <Trash2 size={14} />}<span>{removalArmed ? "한 번 더 눌러 제거" : "제거"}</span></button>}
                    </article>
                  );
                })}
              </div>
              {!membersLoading && memberships.length === 0 && <p className="project-member-state">구성원 정보를 찾지 못했습니다.</p>}
              {!canManageMembers && <small className="project-member-note">소유자와 관리자만 구성원을 변경할 수 있습니다.</small>}
              {memberMessage && <p className="instruction-message">{memberMessage}</p>}
              {memberError && <p className="instruction-message is-error">{memberError}</p>}
            </section>

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
