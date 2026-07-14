import { AlertTriangle, Braces, Check, ChevronDown, ChevronRight, Code2, Download, Eye, FileCode2, FileJson, FileText, Folder, FolderOpen, Info, LoaderCircle, Menu, Package, Pencil, RefreshCw, Save, Search, Sparkles, Store, Trash2, Undo2, Wrench, X } from "lucide-react";
import { type DragEvent, type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, ApiError } from "../api";
import type { ExtensionInstallation, SkillExtension, SkillVersion } from "../api-types";
import { McpMarketplacePanel } from "./McpMarketplacePanel";
import { ResizableSplitPane } from "./ResizableSplitPane";
import { SyntaxCode, SyntaxTextarea } from "./SyntaxCode";

interface MarketplaceViewProps {
  projectId: string | null;
  onOpenNavigation: () => void;
}

interface SkillFileNode {
  name: string;
  path: string;
  kind: "folder" | "file";
  children: SkillFileNode[];
}

function containScrollAtBoundary(event: WheelEvent) {
  const element = event.currentTarget as HTMLElement;
  const atTop = element.scrollTop <= 0;
  const atBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 1;
  if ((event.deltaY < 0 && atTop) || (event.deltaY > 0 && atBottom)) {
    event.preventDefault();
    event.stopPropagation();
  }
}

function buildSkillFileTree(paths: string[]): SkillFileNode[] {
  const root: SkillFileNode[] = [];
  for (const path of paths.sort((left, right) => left.localeCompare(right))) {
    const parts = path.split("/");
    let children = root;
    parts.forEach((name, index) => {
      const nodePath = parts.slice(0, index + 1).join("/");
      const kind = index === parts.length - 1 ? "file" : "folder";
      let node = children.find((item) => item.name === name && item.kind === kind);
      if (!node) {
        node = { name, path: nodePath, kind, children: [] };
        children.push(node);
      }
      children = node.children;
    });
  }
  const sort = (nodes: SkillFileNode[]): SkillFileNode[] => nodes
    .sort((left, right) => left.kind === right.kind ? left.name.localeCompare(right.name) : left.kind === "folder" ? -1 : 1)
    .map((node) => ({ ...node, children: sort(node.children) }));
  return sort(root);
}

function skillFileIcon(path: string): ReactNode {
  const extension = path.split(".").at(-1)?.toLocaleLowerCase();
  if (extension === "json") return <FileJson className="is-json" size={13} />;
  if (extension === "yaml" || extension === "yml") return <Braces className="is-yaml" size={13} />;
  if (["py", "js", "mjs", "ts", "tsx", "jsx"].includes(extension ?? "")) return <FileCode2 className={`is-${extension}`} size={13} />;
  return <FileText className={extension === "md" ? "is-markdown" : "is-text"} size={13} />;
}

function skillTags(item: SkillExtension): string[] {
  const manifest = item.versions.at(-1)?.manifest;
  const configured = Array.isArray(manifest?.tags)
    ? manifest.tags.filter((tag): tag is string => typeof tag === "string" && Boolean(tag.trim())).map((tag) => tag.trim().replace(/^#/, ""))
    : [];
  if (configured.length > 0) return configured.slice(0, 3);
  const category = typeof manifest?.category === "string" ? manifest.category.trim() : "";
  if (category && category !== "기본 제공") return [category.replace(/^#/, "")];
  return [item.visibility === "organization" ? "조직" : "개인"];
}

function visibilityLabel(visibility: SkillExtension["visibility"]): string {
  if (visibility === "organization") return "조직";
  if (visibility === "project") return "프로젝트";
  return "개인";
}

function skillDisplayVersion(item: SkillExtension): string {
  const publish = item.versions.filter((version) => version.status === "published" || version.publishedAt).length;
  const merge = item.versions.filter((version) => version.status !== "published" && !version.publishedAt).length;
  const feedback = item.draft?.dirty ? item.draft.revision : 0;
  return `v${publish}.${merge}.${feedback}`;
}

function nextSavedSkillDisplayVersion(item: SkillExtension): string {
  const publish = item.versions.filter((version) => version.status === "published" || version.publishedAt).length;
  const merge = item.versions.filter((version) => version.status !== "published" && !version.publishedAt).length + 1;
  return `v${publish}.${merge}.0`;
}

function trashRetentionLabel(purgesAt: string | null): string {
  if (!purgesAt) return "30일 후 자동 삭제";
  const date = new Date(purgesAt);
  if (Number.isNaN(date.getTime())) return "30일 후 자동 삭제";
  return `${new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium" }).format(date)} 자동 삭제`;
}

export function MarketplaceView({ projectId, onOpenNavigation }: MarketplaceViewProps) {
  const skillContentRef = useRef<HTMLDivElement>(null);
  const repositoryRevisionRef = useRef<string | null>(null);
  const [marketKind, setMarketKind] = useState<"skill" | "mcp">("skill");
  const [mcpRefreshKey, setMcpRefreshKey] = useState(0);
  const [items, setItems] = useState<SkillExtension[]>([]);
  const [trashedItems, setTrashedItems] = useState<SkillExtension[]>([]);
  const [installations, setInstallations] = useState<ExtensionInstallation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const pendingInstallationIdsRef = useRef<Set<string>>(new Set());
  const [pendingInstallationSurfaceById, setPendingInstallationSurfaceById] = useState<Record<string, "list" | "detail">>({});
  const [error, setError] = useState<string | null>(null);
  const [skillView, setSkillView] = useState<"catalog" | "installed" | "drafts" | "trash">("catalog");

  const [query, setQuery] = useState("");
  const [versionDetail, setVersionDetail] = useState<SkillVersion | null>(null);
  const [activeFile, setActiveFile] = useState("SKILL.md");
  const [skillContentView, setSkillContentView] = useState<"source" | "rendered">("source");
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [editMode, setEditMode] = useState(false);
  const [editableFiles, setEditableFiles] = useState<Record<string, string>>({});
  const [editableName, setEditableName] = useState("");
  const [editableDescription, setEditableDescription] = useState("");
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [draggedPath, setDraggedPath] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);

  useEffect(() => {
    const element = skillContentRef.current;
    if (!element) return;
    element.addEventListener("wheel", containScrollAtBoundary, { passive: false });
    return () => element.removeEventListener("wheel", containScrollAtBoundary);
  }, [activeFile, selectedId, skillView]);

  const currentItems = skillView === "trash" ? trashedItems : items;
  const selected = currentItems.find((item) => item.id === selectedId) ?? currentItems[0] ?? null;
  const installation = selected ? installations.find((item) => item.extensionId === selected.id) ?? null : null;
  const latestVersion = selected?.versions.at(-1) ?? null;
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return currentItems.filter((item) => {
      if (skillView === "drafts" && !item.draft) return false;
      if (skillView === "installed" && !installations.some((entry) => entry.extensionId === item.id)) return false;
      const tags = skillTags(item);
      return !normalized || `${item.name} ${item.description} ${item.slug} ${tags.join(" ")} ${tags.map((tag) => `#${tag}`).join(" ")}`.toLocaleLowerCase().includes(normalized);
    });
  }, [currentItems, installations, query, skillView]);
  const sourceDetailFiles = selected?.draft?.package.files ?? versionDetail?.package?.files ?? {};
  const detailFiles = editMode ? editableFiles : sourceDetailFiles;
  const activeFileIsMarkdown = activeFile.toLocaleLowerCase().endsWith(".md");
  const fileTree = useMemo(() => buildSkillFileTree(Object.keys(detailFiles)), [detailFiles]);

  const refresh = async (preferredId?: string) => {
    setLoading(true);
    setError(null);
    try {
      const [extensions, trashed, installed] = await Promise.all([
        api.extensions.list(),
        api.extensions.listTrash(),
        api.extensions.listInstallations(),
      ]);
      setItems(extensions);
      setTrashedItems(trashed);
      setInstallations(installed.filter((entry) => entry.scopeType === "user"));
      setSelectedId((current) => preferredId ?? (current && [...extensions, ...trashed].some((item) => item.id === current) ? current : extensions[0]?.id ?? trashed[0]?.id ?? null));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Marketplace를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    const pollRepositoryState = () => {
      void api.extensions.getRepositoryState(controller.signal).then((state) => {
        const previousRevision = repositoryRevisionRef.current;
        repositoryRevisionRef.current = state.revision;
        if (!previousRevision || previousRevision === state.revision) return;
        if (marketKind === "skill") void refresh();
        else setMcpRefreshKey((value) => value + 1);
      }).catch(() => undefined);
    };
    pollRepositoryState();
    const timer = window.setInterval(pollRepositoryState, 3_000);
    return () => {
      window.clearInterval(timer);
      controller.abort();
    };
  }, [marketKind, projectId]);

  const refreshRepository = async () => {
    setError(null);
    try {
      const state = await api.extensions.syncRepository();
      repositoryRevisionRef.current = state.revision;
      if (marketKind === "skill") await refresh();
      else setMcpRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Repository 확장을 다시 찾지 못했습니다.");
    }
  };

  useEffect(() => {
    const versionId = selected?.latestPublishedVersionId;
    setVersionDetail(null);
    setActiveFile("SKILL.md");
    if (skillView === "trash" || !versionId || selected?.draft) return;
    const controller = new AbortController();
    void api.extensions.getVersion(versionId, controller.signal).then(setVersionDetail).catch(() => setVersionDetail(null));
    return () => controller.abort();
  }, [selected?.draft, selected?.id, selected?.latestPublishedVersionId, skillView]);

  useEffect(() => {
    const folders = new Set<string>();
    Object.keys(detailFiles).forEach((path) => {
      const parts = path.split("/");
      parts.slice(0, -1).forEach((_, index) => folders.add(parts.slice(0, index + 1).join("/")));
    });
    setExpandedFolders(folders);
  }, [selected?.draft?.digest, selected?.id, versionDetail?.digest]);

  useEffect(() => {
    setEditMode(false);
    setRenamingPath(null);
    setDraggedPath(null);
    setDropTarget(null);
    setDeleteConfirmId(null);
  }, [selected?.id, skillView]);

  const saveVersion = async () => {
    if (!selected?.draft || busy) return;
    setBusy(true);
    try {
      await api.extensions.saveVersion(selected.draft);
      await refresh(selected.id);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "새 Skill 버전을 저장하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const deleteSelectedSkill = async () => {
    if (!selected?.canDelete || busy) return;
    if (deleteConfirmId !== selected.id) {
      setDeleteConfirmId(selected.id);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const deletedId = selected.id;
      await api.extensions.delete(deletedId);
      setDeleteConfirmId(null);
      setSkillView("trash");
      await refresh(deletedId);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill을 보관함으로 이동하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const restoreSelectedSkill = async () => {
    if (!selected || skillView !== "trash" || busy) return;
    setBusy(true);
    setError(null);
    try {
      const restored = await api.extensions.restore(selected.id);
      setSkillView("catalog");
      await refresh(restored.id);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill을 복원하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const toggleInstallation = async (target: SkillExtension, surface: "list" | "detail") => {
    if (busy || pendingInstallationIdsRef.current.has(target.id)) return;
    const targetInstallation = installations.find((entry) => entry.extensionId === target.id) ?? null;
    const targetVersion = target.versions.at(-1) ?? null;
    if (!targetInstallation && !targetVersion) return;
    pendingInstallationIdsRef.current.add(target.id);
    setPendingInstallationSurfaceById((current) => ({ ...current, [target.id]: surface }));
    setError(null);
    try {
      if (targetInstallation) {
        await api.extensions.uninstall(targetInstallation.id);
        setInstallations((current) => current.filter((entry) => entry.extensionId !== target.id));
      } else if (targetVersion) {
        const installed = await api.extensions.install(targetVersion.id);
        setInstallations((current) => [...current.filter((entry) => entry.extensionId !== target.id), installed]);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "설치 상태를 변경하지 못했습니다.");
    } finally {
      pendingInstallationIdsRef.current.delete(target.id);
      setPendingInstallationSurfaceById((current) => {
        const next = { ...current };
        delete next[target.id];
        return next;
      });
    }
  };

  const beginPackageEdit = async () => {
    if (!selected?.canCreateDraft || busy) return;
    setBusy(true);
    setError(null);
    try {
      const draft = selected.draft ?? await api.extensions.checkoutDraft(selected.id);
      if (!selected.draft) {
        setItems((current) => current.map((item) => item.id === selected.id ? { ...item, draft } : item));
      }
      setEditableFiles({ ...draft.package.files });
      setEditableName(selected.name);
      setEditableDescription(selected.description);
      setActiveFile(draft.package.files[activeFile] !== undefined ? activeFile : "SKILL.md");
      setEditMode(true);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill 편집을 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const savePackageEdit = async () => {
    if (!selected?.draft || (selected.canEdit && !editableName.trim()) || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.extensions.updateDraft(selected.draft, editableFiles, "Marketplace 패키지 편집");
      if (selected.canEdit) {
        await api.extensions.updateMetadata(selected.id, {
          name: editableName.trim(),
          description: editableDescription.trim(),
        });
      }
      await refresh(selected.id);
      setEditMode(false);
      setRenamingPath(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill 변경 사항을 저장하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const remapPackagePath = (fromPath: string, toPath: string) => {
    if (fromPath === toPath || toPath.startsWith(`${fromPath}/`)) return;
    const affected = Object.keys(editableFiles).filter((path) => path === fromPath || path.startsWith(`${fromPath}/`));
    if (affected.length === 0) return;
    const nextPaths = affected.map((path) => `${toPath}${path.slice(fromPath.length)}`);
    if (nextPaths.some((path) => editableFiles[path] !== undefined && !affected.includes(path))) {
      setError("같은 위치에 동일한 이름의 파일 또는 폴더가 있습니다.");
      return;
    }
    setEditableFiles((current) => {
      const next = { ...current };
      affected.forEach((path) => delete next[path]);
      affected.forEach((path, index) => { next[nextPaths[index]] = current[path]; });
      return next;
    });
    if (activeFile === fromPath || activeFile.startsWith(`${fromPath}/`)) {
      setActiveFile(`${toPath}${activeFile.slice(fromPath.length)}`);
    }
    setExpandedFolders((current) => new Set([...current].map((path) => path === fromPath || path.startsWith(`${fromPath}/`) ? `${toPath}${path.slice(fromPath.length)}` : path)));
  };

  const commitRename = (node: SkillFileNode) => {
    const name = renameValue.trim();
    setRenamingPath(null);
    if (!name || name === node.name || name === "." || name === ".." || /[\\/]/.test(name)) return;
    const parent = node.path.includes("/") ? node.path.slice(0, node.path.lastIndexOf("/")) : "";
    remapPackagePath(node.path, parent ? `${parent}/${name}` : name);
  };

  const handleRenameKey = (event: KeyboardEvent<HTMLInputElement>, node: SkillFileNode) => {
    if (event.key === "Enter") commitRename(node);
    if (event.key === "Escape") setRenamingPath(null);
  };

  const moveDraggedPath = (folderPath: string) => {
    if (!draggedPath) return;
    const name = draggedPath.split("/").at(-1) ?? draggedPath;
    remapPackagePath(draggedPath, folderPath ? `${folderPath}/${name}` : name);
    setDraggedPath(null);
    setDropTarget(null);
  };

  const handleDragStart = (event: DragEvent<HTMLElement>, path: string) => {
    if (!editMode || path === "SKILL.md") return;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", path);
    setDraggedPath(path);
  };

  const counts = useMemo(() => ({ drafts: items.filter((item) => item.draft).length, installed: installations.filter((entry) => items.some((item) => item.id === entry.extensionId)).length, trashed: trashedItems.length }), [installations, items, trashedItems.length]);

  const renderFileTree = (nodes: SkillFileNode[]): ReactNode => nodes.map((node) => {
    if (node.kind === "folder") {
      const expanded = expandedFolders.has(node.path);
      return <div className="skill-tree-node" key={node.path}>
        <div className={`skill-tree-entry skill-tree-folder ${dropTarget === node.path ? "is-drop-target" : ""}`} role="treeitem" aria-expanded={expanded} draggable={editMode} onDragStart={(event) => handleDragStart(event, node.path)} onDragOver={(event) => { if (!editMode) return; event.preventDefault(); setDropTarget(node.path); }} onDragLeave={() => setDropTarget(null)} onDrop={(event) => { event.preventDefault(); moveDraggedPath(node.path); }} onClick={() => setExpandedFolders((current) => {
          const next = new Set(current);
          if (expanded) next.delete(node.path); else next.add(node.path);
          return next;
        })}>{expanded ? <ChevronDown className="skill-tree-chevron" size={12} /> : <ChevronRight className="skill-tree-chevron" size={12} />}{expanded ? <FolderOpen className="skill-tree-folder-icon" size={14} /> : <Folder className="skill-tree-folder-icon" size={14} />}{renamingPath === node.path ? <input autoFocus value={renameValue} onClick={(event) => event.stopPropagation()} onChange={(event) => setRenameValue(event.currentTarget.value)} onBlur={() => commitRename(node)} onKeyDown={(event) => handleRenameKey(event, node)} /> : <span>{node.name}</span>}{editMode && renamingPath !== node.path && <button className="skill-tree-rename tooltip-control" type="button" aria-label={`${node.name} 이름 변경`} data-tooltip="이름 변경" onClick={(event) => { event.stopPropagation(); setRenamingPath(node.path); setRenameValue(node.name); }}><Pencil size={11} /></button>}</div>
        {expanded && <div className="skill-tree-children">{renderFileTree(node.children)}</div>}
      </div>;
    }
    return <div className={`skill-tree-entry skill-tree-file ${node.path === activeFile ? "is-selected" : ""}`} role="treeitem" draggable={editMode && node.path !== "SKILL.md"} key={node.path} onDragStart={(event) => handleDragStart(event, node.path)} onClick={() => setActiveFile(node.path)}>{skillFileIcon(node.path)}{renamingPath === node.path ? <input autoFocus value={renameValue} onClick={(event) => event.stopPropagation()} onChange={(event) => setRenameValue(event.currentTarget.value)} onBlur={() => commitRename(node)} onKeyDown={(event) => handleRenameKey(event, node)} /> : <span>{node.name}</span>}{editMode && node.path !== "SKILL.md" && renamingPath !== node.path && <button className="skill-tree-rename tooltip-control" type="button" aria-label={`${node.name} 이름 변경`} data-tooltip="이름 변경" onClick={(event) => { event.stopPropagation(); setRenamingPath(node.path); setRenameValue(node.name); }}><Pencil size={11} /></button>}</div>;
  });

  return (
    <div className="feature-view marketplace-view">
      <header className="feature-header"><div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><Store size={17} /><h1>마켓스토어</h1>{marketKind === "mcp" && <span>승인 MCP · 설치 · Secret binding</span>}</div><div><button type="button" aria-label="새로 고침" onClick={() => void refreshRepository()}><RefreshCw size={15} /></button></div></header>
      <div className="feature-kind-tabs" role="tablist" aria-label="Marketplace 유형"><button type="button" role="tab" aria-selected={marketKind === "skill"} onClick={() => setMarketKind("skill")}><Sparkles size={14} /> Skill</button><button type="button" role="tab" aria-selected={marketKind === "mcp"} onClick={() => setMarketKind("mcp")}><Wrench size={14} /> MCP</button></div>
      {marketKind === "skill" && <div className="marketplace-toolbar">
        <div className="marketplace-scope-tabs" role="tablist" aria-label="Skill 보기">
          <button type="button" role="tab" aria-selected={skillView === "catalog"} onClick={() => setSkillView("catalog")}><Package size={14} /> 카탈로그 <span>{items.length}</span></button>
          <button type="button" role="tab" aria-selected={skillView === "installed"} onClick={() => setSkillView("installed")}><Download size={14} /> 설치됨 <span>{counts.installed}</span></button>
          <button type="button" role="tab" aria-selected={skillView === "drafts"} onClick={() => setSkillView("drafts")}><Sparkles size={14} /> 내 초안 <span>{counts.drafts}</span></button>
          <button className="tooltip-control" type="button" role="tab" aria-selected={skillView === "trash"} data-tooltip="삭제한 Skill은 30일 동안 보관되며 그 전에 복원할 수 있습니다." onClick={() => setSkillView("trash")}><Trash2 size={14} /> 삭제됨 <Info size={12} aria-hidden="true" /> <span>{counts.trashed}</span></button>
        </div>
        <label className="marketplace-search"><Search size={14} /><input aria-label="Skill 검색" placeholder="Skill 이름 또는 설명 검색" value={query} onChange={(event) => setQuery(event.currentTarget.value)} /></label>
      </div>}
      {error && <div className="feature-error" role="alert">{error}</div>}
      {marketKind === "mcp" ? <McpMarketplacePanel key={`${projectId ?? "none"}:${mcpRefreshKey}`} projectId={projectId} /> : <ResizableSplitPane storageKey="lumina:marketplace-list-width" ariaLabel="Skill 목록 너비 조절" className="marketplace-split">
        <aside className="feature-list" aria-label={skillView === "trash" ? "삭제된 Skill 목록" : "Skill 목록"}>
          {loading ? <div className="feature-state"><LoaderCircle className="is-running" size={16} /> 불러오는 중</div> : visibleItems.length === 0 ? <div className="feature-state">조건에 맞는 Skill이 없습니다.</div> : visibleItems.map((item) => {
            const itemInstallation = installations.find((entry) => entry.extensionId === item.id) ?? null;
            const itemVersion = item.versions.at(-1) ?? null;
            const itemInstallationPending = pendingInstallationSurfaceById[item.id] === "list";
            return <div className={`marketplace-skill-row ${item.id === selected?.id ? "is-selected" : ""}`} key={item.id}>
              <button className="marketplace-skill-select" type="button" onClick={() => setSelectedId(item.id)}>
                <span><strong>{item.name}</strong><small>{item.description || item.slug}</small>{skillView === "trash" && <small>{trashRetentionLabel(item.purgesAt)}</small>}<small className="marketplace-tags" aria-label="Skill 태그">{skillTags(item).map((tag) => <span key={tag}>#{tag}</span>)}</small></span>
              </button>
              {skillView !== "trash" && <button className={`marketplace-install-toggle ${itemInstallation ? "is-installed" : ""}`} type="button" aria-label={`${item.name} ${itemInstallation ? "미사용" : "설치"}`} aria-pressed={Boolean(itemInstallation)} aria-busy={itemInstallationPending} disabled={!itemVersion || itemInstallationPending} onClick={() => void toggleInstallation(item, "list")}>{itemInstallationPending ? <LoaderCircle className="is-running" size={12} /> : itemInstallation ? <><span className="install-toggle-rest">설치됨</span><span className="install-toggle-hover">미사용</span></> : <span>설치</span>}</button>}
            </div>;
          })}
        </aside>
        <section className="feature-detail">
          {!selected ? <div className="feature-state">Skill을 선택해 주세요.</div> : (
            <>
              <header className="detail-heading">
                <div>{editMode && selected.canEdit ? <><h2 className="marketplace-inline-editor" contentEditable="plaintext-only" suppressContentEditableWarning role="textbox" aria-label="Skill 이름" aria-multiline="false" onInput={(event) => setEditableName(event.currentTarget.textContent ?? "")} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } }}>{editableName}</h2><p className="marketplace-inline-editor" contentEditable="plaintext-only" suppressContentEditableWarning role="textbox" aria-label="Skill 설명" aria-multiline="false" data-placeholder="설명 없음" onInput={(event) => setEditableDescription(event.currentTarget.textContent ?? "")} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } }}>{editableDescription}</p></> : <><h2>{selected.name}</h2><p>{selected.description || "설명 없음"}</p></>}</div>
                <div className="detail-badges"><span>{skillView === "trash" ? "보관함" : visibilityLabel(selected.visibility)}</span><span>{skillDisplayVersion(selected)}</span></div>
              </header>
              <div className={`marketplace-package-detail ${editMode ? "is-editing" : ""}`}>
                <div className="marketplace-package-summary">
                  <div><strong>{skillView === "trash" ? trashRetentionLabel(selected.purgesAt) : `버전 ${skillDisplayVersion(selected)}`}</strong><span>Owner {selected.ownerships.filter((item) => item.role === "owner").map((item) => item.displayName).join(", ") || "미지정"}</span></div>
                  <div className="marketplace-package-actions">
                    {skillView === "trash" ? <button className="lumina-primary-action" type="button" disabled={busy} onClick={() => void restoreSelectedSkill()}>{busy ? <LoaderCircle className="is-running" size={14} /> : <Undo2 size={14} />} 복원</button> : <>
                      {editMode ? <><button type="button" disabled={busy} onClick={() => { setEditMode(false); setRenamingPath(null); }}><X size={14} /> 취소</button><button className="lumina-primary-action" type="button" disabled={busy || (selected.canEdit && !editableName.trim())} onClick={() => void savePackageEdit()}><Save size={14} /> 초안 저장</button></> : selected.canCreateDraft && <button type="button" disabled={busy} onClick={() => void beginPackageEdit()}><Pencil size={14} /> {selected.canEdit ? "편집" : "내 버전으로 수정"}</button>}
                      {!editMode && selected.draft?.dirty && <button type="button" disabled={busy} onClick={() => void saveVersion()}><Check size={14} /> {nextSavedSkillDisplayVersion(selected)}로 저장</button>}
                      {!editMode && <button className={installation ? "is-danger" : "is-primary lumina-primary-action"} type="button" aria-busy={pendingInstallationSurfaceById[selected.id] === "detail"} disabled={!latestVersion || busy || pendingInstallationSurfaceById[selected.id] === "detail"} onClick={() => selected && void toggleInstallation(selected, "detail")}>{pendingInstallationSurfaceById[selected.id] === "detail" ? <><LoaderCircle className="is-running" size={14} /> 처리 중</> : <>{installation ? <Trash2 size={14} /> : <Download size={14} />}{installation ? "미사용" : "설치"}</>}</button>}
                      {!editMode && selected.canDelete && <button className={`text-danger ${deleteConfirmId === selected.id ? "is-delete-armed" : ""}`} type="button" aria-label={deleteConfirmId === selected.id ? `${selected.name} 삭제 경고, 한 번 더 누르면 보관함으로 이동` : `${selected.name} 삭제`} disabled={busy} onClick={() => void deleteSelectedSkill()}>{busy && deleteConfirmId === selected.id ? <LoaderCircle className="is-running" size={14} /> : deleteConfirmId === selected.id ? <AlertTriangle size={14} /> : <Trash2 size={14} />} {deleteConfirmId === selected.id ? "경고" : "삭제"}</button>}
                    </>}
                  </div>
                </div>
                {skillView === "trash" ? <div className="feature-state">복원하면 Skill 파일과 버전을 다시 사용할 수 있습니다.</div> : <div className="marketplace-file-browser">
                    <aside className="skill-file-explorer" aria-label="Skill 파일"><header className={dropTarget === "" ? "is-drop-target" : ""} onDragOver={(event) => { if (!editMode) return; event.preventDefault(); setDropTarget(""); }} onDrop={(event) => { event.preventDefault(); moveDraggedPath(""); }}><FolderOpen size={14} /> 패키지 파일{editMode && <small>드래그하여 이동</small>}</header><div className="skill-tree" role="tree">{renderFileTree(fileTree)}</div></aside>
                    <section>
                      <header>
                        <span>{activeFile}</span>
                        {!editMode && activeFileIsMarkdown && <div className="skill-content-view-toggle" role="group" aria-label="Skill 본문 보기 방식">
                          <button className="tooltip-control" type="button" aria-label="원문 보기" aria-pressed={skillContentView === "source"} data-tooltip="원문 보기" onClick={() => setSkillContentView("source")}><Code2 size={14} /></button>
                          <button className="tooltip-control" type="button" aria-label="렌더링 보기" aria-pressed={skillContentView === "rendered"} data-tooltip="렌더링 보기" onClick={() => setSkillContentView("rendered")}><Eye size={14} /></button>
                        </div>}
                      </header>
                      <div className="skill-file-content" ref={skillContentRef}>
                        {editMode ? <SyntaxTextarea className="skill-file-editor" ariaLabel={`${activeFile} 내용`} fileName={activeFile} value={detailFiles[activeFile] ?? ""} onChange={(event) => { const nextValue = event.currentTarget.value; setEditableFiles((current) => ({ ...current, [activeFile]: nextValue })); }} /> : activeFileIsMarkdown && skillContentView === "rendered"
                          ? <div className="markdown-response skill-markdown-preview"><ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}>{detailFiles[activeFile] ?? "파일 내용을 불러오는 중입니다."}</ReactMarkdown></div>
                          : <SyntaxCode value={detailFiles[activeFile] ?? "파일 내용을 불러오는 중입니다."} fileName={activeFile} />}
                      </div>
                    </section>
                  </div>}
                </div>
            </>
          )}
        </section>
      </ResizableSplitPane>}
    </div>
  );
}
