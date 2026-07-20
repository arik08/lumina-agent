import { AlertTriangle, ArrowLeft, Braces, Check, ChevronDown, ChevronRight, Code2, Download, Eye, FileCode2, FileJson, FileText, Folder, FolderOpen, History, Info, LoaderCircle, Maximize2, Menu, Minimize2, Package, Pencil, Power, RefreshCw, Save, Search, ServerCog, Settings2, Sparkles, Store, Trash2, Undo2, Wrench, X } from "lucide-react";
import { type DragEvent, type KeyboardEvent, type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api as coreApi, ApiError } from "../api";
import { extensionsApi } from "../feature-api";
import type { ExtensionInstallation, ProjectSummary, SkillCatalogItem, SkillCatalogResponse, SkillExtension, SkillVersion, SkillVersionComparison } from "../api-types";
import { useCachedViewState } from "../view-data-cache";
import { AdminMcpPanel } from "./AdminMcpPanel";
import { McpMarketplacePanel } from "./McpMarketplacePanel";
import { MarketplaceInstallButton } from "./MarketplaceInstallButton";
import { ResizableSplitPane } from "./ResizableSplitPane";
import { SkillCatalogPanel, type SkillCatalogSort } from "./SkillCatalogPanel";
import { SkillVersionHistory } from "./SkillVersionHistory";
import { SyntaxCode, SyntaxTextarea } from "./SyntaxCode";
import { useDismissablePopover } from "./useDismissablePopover";
import "./MarketplaceTagEditor.css";
import { markdownBodyAfterFrontmatter, splitMarkdownFrontmatter } from "./markdownFrontmatter";

const api = { ...coreApi, extensions: extensionsApi };

interface MarketplaceViewProps {
  projectId: string | null;
  onOpenNavigation: () => void;
  canManage: boolean;
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

const EMPTY_SKILL_CATALOG: SkillCatalogResponse = {
  items: [],
  total: 0,
  offset: 0,
  hasMore: false,
  facets: { categories: [], tags: [] },
};

function skillTags(item: SkillExtension): string[] {
  const storedTags = (item as SkillExtension & { tags?: unknown }).tags;
  if (Array.isArray(storedTags) && storedTags.length > 0) return storedTags.slice(0, 3);
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
  if (visibility === "organization") return "기본";
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

function SkillMarkdownPreview({ value }: { value: string }) {
  const frontmatter = splitMarkdownFrontmatter(value);
  const markdown = frontmatter ? markdownBodyAfterFrontmatter(frontmatter.body) : value;

  return <div className="markdown-response skill-markdown-preview">
    {frontmatter && <section className="skill-frontmatter-preview" aria-label="Skill 트리거 메타데이터">
      <hr />
      <SyntaxCode value={frontmatter.yaml} language="yaml" />
      <hr />
    </section>}
    <ReactMarkdown skipHtml remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
  </div>;
}

export function MarketplaceView({ projectId, onOpenNavigation, canManage }: MarketplaceViewProps) {
  const skillContentRef = useRef<HTMLDivElement>(null);
  const projectScopeButtonRef = useRef<HTMLButtonElement>(null);
  const projectScopeMenuRef = useRef<HTMLDivElement>(null);
  const repositoryRevisionRef = useRef<string | null>(null);
  const catalogRequestIdRef = useRef(0);
  const [marketKind, setMarketKind] = useState<"skill" | "mcp">("skill");
  const [mcpView, setMcpView] = useState<"catalog" | "admin">("catalog");
  const [mcpRefreshKey, setMcpRefreshKey] = useState(0);
  const cacheKey = `marketplace:${projectId ?? "none"}`;
  const [items, setItems, hasCachedItems] = useCachedViewState<SkillExtension[]>(`${cacheKey}:items`, []);
  const [trashedItems, setTrashedItems, hasCachedTrash] = useCachedViewState<SkillExtension[]>(`${cacheKey}:trash`, []);
  const [installations, setInstallations, hasCachedInstallations] = useCachedViewState<ExtensionInstallation[]>(`${cacheKey}:installations`, []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(!hasCachedItems || !hasCachedTrash || !hasCachedInstallations);
  const [busy, setBusy] = useState(false);
  const pendingInstallationIdsRef = useRef<Set<string>>(new Set());
  const [pendingInstallationSurfaceById, setPendingInstallationSurfaceById] = useState<Record<string, "catalog" | "list" | "detail">>({});
  const [pendingLikeIds, setPendingLikeIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [skillView, setSkillView] = useState<"catalog" | "installed" | "drafts" | "trash">("catalog");
  const [enteredInstalledFromCatalog, setEnteredInstalledFromCatalog] = useState(false);

  const [query, setQuery] = useState("");
  const [catalogQuery, setCatalogQuery] = useState("");
  const [catalogCategory, setCatalogCategory] = useState("");
  const [catalogTag, setCatalogTag] = useState("");
  const [catalogSort, setCatalogSort] = useState<SkillCatalogSort>("popular");
  const [catalogScrollPosition, setCatalogScrollPosition] = useState(0);
  const catalogCacheKey = `${cacheKey}:catalog:${catalogQuery.trim().toLocaleLowerCase("ko-KR")}:${catalogCategory}:${catalogTag}:${catalogSort}`;
  const [catalog, setCatalog, hasCachedCatalog] = useCachedViewState<SkillCatalogResponse>(catalogCacheKey, EMPTY_SKILL_CATALOG);
  const lastVisibleCatalogRef = useRef(catalog);
  useEffect(() => {
    if (hasCachedCatalog) lastVisibleCatalogRef.current = catalog;
  }, [catalog, hasCachedCatalog]);
  const visibleCatalog = hasCachedCatalog ? catalog : lastVisibleCatalogRef.current;
  const selectedTagCount = catalogTag
    ? visibleCatalog.facets.tags.find((item) => item.value === catalogTag)?.count
    : undefined;
  const catalogTabCount = hasCachedCatalog
    ? catalog.total
    : selectedTagCount ?? (visibleCatalog.total || items.length);
  const [catalogLoading, setCatalogLoading] = useState(!hasCachedCatalog);
  const [catalogLoadingMore, setCatalogLoadingMore] = useState(false);
  const [versionDetail, setVersionDetail] = useState<SkillVersion | null>(null);
  const [versionHistoryOpen, setVersionHistoryOpen] = useState(false);
  const [versionComparison, setVersionComparison] = useState<SkillVersionComparison | null>(null);
  const [activeFile, setActiveFile] = useState("SKILL.md");
  const [skillContentView, setSkillContentView] = useState<"source" | "rendered">("rendered");
  const [skillContentExpanded, setSkillContentExpanded] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [editMode, setEditMode] = useState(false);
  const [editableFiles, setEditableFiles] = useState<Record<string, string>>({});
  const [editableName, setEditableName] = useState("");
  const [editableDescription, setEditableDescription] = useState("");
  const [editableChangeSummary, setEditableChangeSummary] = useState("");
  const [editableTags, setEditableTags] = useState<string[]>([]);
  const [editableTagInput, setEditableTagInput] = useState("");
  const [renamingPath, setRenamingPath] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [draggedPath, setDraggedPath] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectScopeOpen, setProjectScopeOpen] = useState(false);
  const [projectScopeDraft, setProjectScopeDraft] = useState<Set<string> | null>(null);
  const [projectScopeBusy, setProjectScopeBusy] = useState(false);
  const [projectScopePosition, setProjectScopePosition] = useState({ top: 0, right: 0 });
  useDismissablePopover(projectScopeOpen, projectScopeButtonRef, projectScopeMenuRef, setProjectScopeOpen);

  useEffect(() => {
    const element = skillContentRef.current;
    if (!element) return;
    element.addEventListener("wheel", containScrollAtBoundary, { passive: false });
    return () => element.removeEventListener("wheel", containScrollAtBoundary);
  }, [activeFile, selectedId, skillView]);

  const currentItems = skillView === "trash" ? trashedItems : items;
  const selectedCandidate = currentItems.find((item) => item.id === selectedId) ?? currentItems[0] ?? null;
  const selected = skillView === "installed" && selectedCandidate && !installations.some((entry) => entry.extensionId === selectedCandidate.id)
    ? currentItems.find((item) => installations.some((entry) => entry.extensionId === item.id)) ?? null
    : selectedCandidate;
  const installation = selected ? installations.find((item) => item.extensionId === selected.id) ?? null : null;
  const latestVersion = selected?.versions.at(-1) ?? null;
  const visibleItems = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    return currentItems.filter((item) => {
      if (skillView === "drafts" && !item.draft?.dirty) return false;
      if (skillView === "installed" && !installations.some((entry) => entry.extensionId === item.id)) return false;
      const tags = skillTags(item);
      return !normalized || `${item.name} ${item.description} ${item.slug} ${tags.join(" ")} ${tags.map((tag) => `#${tag}`).join(" ")}`.toLocaleLowerCase().includes(normalized);
    });
  }, [currentItems, installations, query, skillView]);
  const sourceDetailFiles = selected?.draft?.package?.files ?? versionDetail?.package?.files ?? {};
  const detailFiles = editMode ? editableFiles : sourceDetailFiles;
  const activeFileIsMarkdown = activeFile.toLocaleLowerCase().endsWith(".md");
  const fileTree = useMemo(() => buildSkillFileTree(Object.keys(detailFiles)), [detailFiles]);

  const refresh = async (preferredId?: string) => {
    setLoading(true);
    setError(null);
    try {
      const [extensions, trashed, installed, availableProjects] = await Promise.all([
        api.extensions.list(),
        api.extensions.listTrash(),
        api.extensions.listInstallations(),
        api.projects.list(),
      ]);
      setItems(extensions);
      setTrashedItems(trashed);
      setInstallations(installed.filter((entry) => entry.scopeType === "user"));
      setProjects(availableProjects);
      setSelectedId((current) => preferredId ?? (current && [...extensions, ...trashed].some((item) => item.id === current) ? current : extensions[0]?.id ?? trashed[0]?.id ?? null));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Marketplace를 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  };

  const refreshCatalog = useCallback(async ({
    offset = 0,
    append = false,
    signal,
  }: {
    offset?: number;
    append?: boolean;
    signal?: AbortSignal;
  } = {}) => {
    const requestId = ++catalogRequestIdRef.current;
    if (append) setCatalogLoadingMore(true);
    else setCatalogLoading(true);
    try {
      const response = await api.extensions.listCatalog({
        query: catalogQuery.trim() || undefined,
        category: catalogCategory || undefined,
        tag: catalogTag || undefined,
        sort: catalogSort,
        offset,
        limit: 60,
      }, signal);
      if (requestId !== catalogRequestIdRef.current) return;
      setCatalog((current) => append ? { ...response, items: [...current.items, ...response.items] } : response);
    } catch (caught) {
      if (signal?.aborted || requestId !== catalogRequestIdRef.current) return;
      setError(caught instanceof ApiError ? caught.message : "Skill 카탈로그를 불러오지 못했습니다.");
    } finally {
      if (requestId === catalogRequestIdRef.current) {
        setCatalogLoading(false);
        setCatalogLoadingMore(false);
      }
    }
  }, [catalogCategory, catalogQuery, catalogSort, catalogTag]);

  useEffect(() => {
    void refresh();
  }, [projectId]);

  useEffect(() => {
    if (marketKind !== "skill" || skillView !== "catalog") return;
    const controller = new AbortController();
    const timer = window.setTimeout(() => void refreshCatalog({ signal: controller.signal }), 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [marketKind, refreshCatalog, skillView]);

  useEffect(() => {
    const controller = new AbortController();
    const pollRepositoryState = () => {
      void api.extensions.getRepositoryState(controller.signal).then((state) => {
        const previousRevision = repositoryRevisionRef.current;
        repositoryRevisionRef.current = state.revision;
        if (!previousRevision || previousRevision === state.revision) return;
        if (marketKind === "skill") {
          void refresh();
          void refreshCatalog();
        }
        else setMcpRefreshKey((value) => value + 1);
      }).catch(() => undefined);
    };
    const pollWhenVisible = () => {
      if (document.visibilityState === "visible") pollRepositoryState();
    };
    pollWhenVisible();
    const timer = window.setInterval(pollWhenVisible, 15_000);
    document.addEventListener("visibilitychange", pollWhenVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", pollWhenVisible);
      controller.abort();
    };
  }, [marketKind, projectId]);

  useEffect(() => {
    if (!selected?.draft || selected.draft.package) return;
    const controller = new AbortController();
    void api.extensions.getDraft(selected.id, controller.signal).then((draft) => {
      setItems((current) => current.map((item) => (
        item.id === selected.id ? { ...item, draft } : item
      )));
    }).catch(() => undefined);
    return () => controller.abort();
  }, [selected?.draft?.id, selected?.draft?.package, selected?.id]);

  const refreshRepository = async () => {
    setError(null);
    try {
      const state = await api.extensions.syncRepository();
      repositoryRevisionRef.current = state.revision;
      if (marketKind === "skill") {
        await Promise.all([refresh(), refreshCatalog()]);
      }
      else setMcpRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Repository 확장을 다시 찾지 못했습니다.");
    }
  };

  useEffect(() => {
    const versionId = selected?.latestPublishedVersionId;
    setVersionDetail(null);
    setActiveFile("SKILL.md");
    if (skillView === "catalog" || skillView === "trash" || !versionId || selected?.draft) return;
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
    setVersionHistoryOpen(false);
    setVersionComparison(null);
    setRenamingPath(null);
    setDraggedPath(null);
    setDropTarget(null);
    setDeleteConfirmId(null);
  }, [selected?.id, skillView]);

  useEffect(() => {
    if (!skillContentExpanded) return;
    const closeExpandedView = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setSkillContentExpanded(false);
    };
    window.addEventListener("keydown", closeExpandedView);
    return () => window.removeEventListener("keydown", closeExpandedView);
  }, [skillContentExpanded]);

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

  const compareVersions = async (fromVersionId: string, toVersionId: string) => {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      setVersionComparison(await api.extensions.compareVersions(selected.id, fromVersionId, toVersionId));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill 버전을 비교하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const rollbackVersion = async (target: SkillVersion, changeSummary: string) => {
    if (!selected?.latestPublishedVersionId || selected.currentUserRole !== "owner" || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.extensions.rollbackVersion(
        selected.id,
        target.id,
        selected.latestPublishedVersionId,
        changeSummary,
      );
      setVersionComparison(null);
      await refresh(selected.id);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill 버전을 복원하지 못했습니다.");
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
      await Promise.all([refresh(restored.id), refreshCatalog()]);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill을 복원하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const changeInstallation = async ({
    extensionId,
    versionId,
    installationId,
    surface,
  }: {
    extensionId: string;
    versionId: string | null;
    installationId: string | null;
    surface: "catalog" | "list" | "detail";
  }) => {
    if (pendingInstallationIdsRef.current.has(extensionId)) return;
    const currentInstallation = installations.find((entry) => entry.extensionId === extensionId) ?? null;
    const currentInstallationId = currentInstallation?.id ?? installationId;
    if (!currentInstallationId && !versionId) return;
    pendingInstallationIdsRef.current.add(extensionId);
    setPendingInstallationSurfaceById((current) => ({ ...current, [extensionId]: surface }));
    setError(null);
    try {
      if (currentInstallationId) {
        await api.extensions.uninstall(currentInstallationId);
        setInstallations((current) => current.filter((entry) => entry.extensionId !== extensionId));
        setCatalog((current) => ({
          ...current,
          items: current.items.map((item) => item.id === extensionId ? {
            ...item,
            installed: false,
            installationId: null,
            installCount: Math.max(0, item.installCount - 1),
          } : item),
        }));
      } else if (versionId) {
        const installed = await api.extensions.install(versionId);
        setInstallations((current) => [...current.filter((entry) => entry.extensionId !== extensionId), installed]);
        setCatalog((current) => ({
          ...current,
          items: current.items.map((item) => item.id === extensionId ? {
            ...item,
            installed: true,
            installationId: installed.id,
            installCount: item.installCount + 1,
          } : item),
        }));
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "설치 상태를 변경하지 못했습니다.");
    } finally {
      pendingInstallationIdsRef.current.delete(extensionId);
      setPendingInstallationSurfaceById((current) => {
        const next = { ...current };
        delete next[extensionId];
        return next;
      });
    }
  };

  const toggleInstallation = async (target: SkillExtension, surface: "list" | "detail") => {
    const targetInstallation = installations.find((entry) => entry.extensionId === target.id) ?? null;
    await changeInstallation({
      extensionId: target.id,
      versionId: target.versions.at(-1)?.id ?? null,
      installationId: targetInstallation?.id ?? null,
      surface,
    });
  };

  const toggleCatalogInstallation = async (target: SkillCatalogItem) => {
    await changeInstallation({
      extensionId: target.id,
      versionId: target.latestVersionId,
      installationId: target.installationId,
      surface: "catalog",
    });
  };

  const toggleCatalogLike = async (target: SkillCatalogItem) => {
    if (pendingLikeIds.has(target.id)) return;
    setPendingLikeIds((current) => new Set(current).add(target.id));
    setError(null);
    try {
      const result = await api.extensions.setLike(target.id, !target.likedByMe);
      setCatalog((current) => ({
        ...current,
        items: current.items.map((item) => item.id === target.id ? {
          ...item,
          likedByMe: result.liked,
          likeCount: result.likeCount,
        } : item),
      }));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "좋아요 상태를 변경하지 못했습니다.");
    } finally {
      setPendingLikeIds((current) => {
        const next = new Set(current);
        next.delete(target.id);
        return next;
      });
    }
  };

  useEffect(() => {
    setProjectScopeOpen(false);
    setProjectScopeDraft(null);
  }, [selected?.id]);

  const openProjectScope = () => {
    if (!installation) return;
    const rect = projectScopeButtonRef.current?.getBoundingClientRect();
    if (rect) setProjectScopePosition({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) });
    setProjectScopeDraft(installation.projectIds === null ? null : new Set(installation.projectIds));
    setProjectScopeOpen((current) => !current);
  };

  const toggleProjectScope = (targetProjectId: string) => {
    setProjectScopeDraft((current) => {
      const next = current === null ? new Set(projects.map((item) => item.id)) : new Set(current);
      if (next.has(targetProjectId)) next.delete(targetProjectId);
      else next.add(targetProjectId);
      return next;
    });
  };

  const saveProjectScope = async () => {
    if (!installation) return;
    setProjectScopeBusy(true);
    setError(null);
    try {
      const updated = await api.extensions.updateProjects(
        installation.id,
        projectScopeDraft === null ? null : [...projectScopeDraft],
      );
      setInstallations((current) => current.map((item) => item.id === updated.id ? updated : item));
      setProjectScopeOpen(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "프로젝트 사용 범위를 저장하지 못했습니다.");
    } finally {
      setProjectScopeBusy(false);
    }
  };

  const viewCatalogSkill = (target: SkillCatalogItem) => {
    if (!target.installed) return;
    window.history.pushState({
      ...window.history.state,
      luminaMarketplaceCatalogDetail: {
        projectId: projectId ?? "none",
        skillId: target.id,
      },
    }, "");
    setSelectedId(target.id);
    setEnteredInstalledFromCatalog(true);
    setSkillView("installed");
  };

  const returnToCatalog = () => {
    if (window.history.state?.luminaMarketplaceCatalogDetail?.projectId === (projectId ?? "none")) {
      window.history.back();
      return;
    }
    setEnteredInstalledFromCatalog(false);
    setSkillView("catalog");
  };

  useEffect(() => {
    const handlePopState = (event: PopStateEvent) => {
      const detail = event.state?.luminaMarketplaceCatalogDetail;
      if (detail?.projectId === (projectId ?? "none") && typeof detail.skillId === "string") {
        setSelectedId(detail.skillId);
        setEnteredInstalledFromCatalog(true);
        setSkillView("installed");
      } else if (enteredInstalledFromCatalog) {
        setEnteredInstalledFromCatalog(false);
        setSkillView("catalog");
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, [enteredInstalledFromCatalog, projectId]);

  const beginPackageEdit = async () => {
    if (!selected?.canCreateDraft || busy) return;
    setBusy(true);
    setError(null);
    try {
      let draft = selected.draft ?? await api.extensions.checkoutDraft(selected.id);
      if (!draft.package) draft = await api.extensions.getDraft(selected.id);
      if (!draft.package) throw new Error("Skill Draft package is unavailable.");
      setItems((current) => current.map((item) => item.id === selected.id ? { ...item, draft } : item));
      setEditableFiles({ ...draft.package.files });
      setEditableName(selected.name);
      setEditableDescription(selected.description);
      setEditableChangeSummary("");
      setEditableTags(selected.tags);
      setEditableTagInput("");
      setActiveFile(draft.package.files[activeFile] !== undefined ? activeFile : "SKILL.md");
      setVersionHistoryOpen(false);
      setEditMode(true);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Skill 편집을 시작하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };

  const savePackageEdit = async () => {
    if (!selected?.draft || (selected.canEdit && !editableName.trim()) || busy) return;
    const pendingTag = editableTagInput.trim().replace(/^#/, "").trim().slice(0, 40);
    const tagsToSave = pendingTag && !editableTags.includes(pendingTag) && editableTags.length < 8
      ? [...editableTags, pendingTag]
      : editableTags;
    setBusy(true);
    setError(null);
    try {
      await api.extensions.updateDraft(
        selected.draft,
        editableFiles,
        editableChangeSummary.trim() || "Marketplace 패키지 편집",
      );
      if (selected.canEdit) {
        await api.extensions.updateMetadata(selected.id, {
          name: editableName.trim(),
          description: editableDescription.trim(),
          ...(selected.canEditTags ? { tags: tagsToSave } : {}),
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

  const addEditableTag = () => {
    const tag = editableTagInput.trim().replace(/^#/, "").trim();
    if (!tag || editableTags.includes(tag) || editableTags.length >= 8) {
      setEditableTagInput("");
      return;
    }
    setEditableTags((current) => [...current, tag.slice(0, 40)]);
    setEditableTagInput("");
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

  const counts = useMemo(() => ({ drafts: items.filter((item) => item.draft?.dirty).length, installed: installations.filter((entry) => items.some((item) => item.id === entry.extensionId)).length, trashed: trashedItems.length }), [installations, items, trashedItems.length]);
  const pendingCatalogInstallIds = useMemo(() => new Set(Object.entries(pendingInstallationSurfaceById).filter(([, surface]) => surface === "catalog").map(([id]) => id)), [pendingInstallationSurfaceById]);

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

  const renderPackageBrowser = () => (
    <ResizableSplitPane
      storageKey="lumina:marketplace-file-explorer-width"
      ariaLabel="패키지 파일 탐색기 너비 조절"
      className={`marketplace-file-browser ${skillContentExpanded ? "is-expanded" : ""}`}
      defaultWidth={220}
      minimumWidth={170}
      maximumRatio={0.48}
    >
      <aside className="skill-file-explorer" aria-label="Skill 파일">
        <header className={dropTarget === "" ? "is-drop-target" : ""} onDragOver={(event) => { if (!editMode) return; event.preventDefault(); setDropTarget(""); }} onDrop={(event) => { event.preventDefault(); moveDraggedPath(""); }}><FolderOpen size={14} /> 패키지 파일{editMode && <small>드래그하여 이동</small>}</header>
        <div className="skill-tree" role="tree">{renderFileTree(fileTree)}</div>
      </aside>
      <section>
        <header>
          <span>{activeFile}</span>
          <div className="skill-content-view-actions">
            {!editMode && activeFileIsMarkdown && <button className="tooltip-control" type="button" aria-label={skillContentView === "source" ? "렌더링 보기" : "원문 보기"} aria-pressed={skillContentView === "rendered"} data-tooltip={skillContentView === "source" ? "렌더링 보기" : "원문 보기"} onClick={() => setSkillContentView((current) => current === "source" ? "rendered" : "source")}>{skillContentView === "source" ? <Eye size={14} /> : <Code2 size={14} />}</button>}
            <button className="tooltip-control" type="button" aria-label={skillContentExpanded ? "원래 크기로 보기" : "확대해서 보기"} aria-pressed={skillContentExpanded} data-tooltip={skillContentExpanded ? "원래 크기로 보기" : "확대해서 보기"} onClick={() => setSkillContentExpanded((current) => !current)}>{skillContentExpanded ? <Minimize2 size={14} /> : <Maximize2 size={14} />}</button>
          </div>
        </header>
        <div className="skill-file-content" ref={skillContentRef}>
          {editMode ? <SyntaxTextarea className="skill-file-editor" ariaLabel={`${activeFile} 내용`} fileName={activeFile} value={detailFiles[activeFile] ?? ""} onChange={(event) => { const nextValue = event.currentTarget.value; setEditableFiles((current) => ({ ...current, [activeFile]: nextValue })); }} /> : activeFileIsMarkdown && skillContentView === "rendered"
            ? <SkillMarkdownPreview value={detailFiles[activeFile] ?? "파일 내용을 불러오는 중입니다."} />
            : <SyntaxCode value={detailFiles[activeFile] ?? "파일 내용을 불러오는 중입니다."} fileName={activeFile} />}
        </div>
      </section>
    </ResizableSplitPane>
  );

  const renderSkillDetail = () => (
    <section className={`feature-detail ${skillContentExpanded ? "is-skill-content-expanded" : selected ? "has-skill-package" : ""}`}>
      {!selected ? <div className="feature-state">Skill을 선택해 주세요.</div> : (
        skillContentExpanded ? renderPackageBrowser() : <>
          <header className="detail-heading">
            <div>{enteredInstalledFromCatalog && skillView === "installed" && <button className="marketplace-catalog-back" type="button" onClick={returnToCatalog}><ArrowLeft size={14} /> 뒤로가기</button>}{editMode && selected.canEdit ? <><h2 className="marketplace-inline-editor" contentEditable="plaintext-only" suppressContentEditableWarning role="textbox" aria-label="Skill 이름" aria-multiline="false" onInput={(event) => setEditableName(event.currentTarget.textContent ?? "")} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } }}>{editableName}</h2><p className="marketplace-inline-editor" contentEditable="plaintext-only" suppressContentEditableWarning role="textbox" aria-label="Skill 설명" aria-multiline="false" data-placeholder="설명 없음" onInput={(event) => setEditableDescription(event.currentTarget.textContent ?? "")} onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); event.currentTarget.blur(); } }}>{editableDescription}</p>{selected.canEditTags && <div className="marketplace-tag-editor" aria-label="Skill 태그 편집"><div>{editableTags.map((tag) => <button type="button" key={tag} aria-label={`${tag} 태그 삭제`} onClick={() => setEditableTags((current) => current.filter((item) => item !== tag))}>#{tag}<X size={11} /></button>)}</div><input aria-label="Skill 태그 추가" placeholder={editableTags.length >= 8 ? "태그는 최대 8개입니다" : "태그 입력 후 Enter"} value={editableTagInput} maxLength={41} disabled={editableTags.length >= 8} onChange={(event) => setEditableTagInput(event.currentTarget.value)} onBlur={addEditableTag} onKeyDown={(event) => { if (event.key === "Enter" || event.key === ",") { event.preventDefault(); addEditableTag(); } }} /></div>}</> : <><h2>{selected.name}</h2><p>{selected.description || "설명 없음"}</p></>}</div>
            <div className="detail-badges"><span>{skillView === "trash" ? "보관함" : visibilityLabel(selected.visibility)}</span><span>{skillDisplayVersion(selected)}</span></div>
          </header>
          <div className={`marketplace-package-detail ${editMode ? "is-editing" : ""}`}>
            <div className="marketplace-package-summary">
              <div>{skillView === "trash" && <strong>{trashRetentionLabel(selected.purgesAt)}</strong>}<span>Owner {selected.ownerships.filter((item) => item.role === "owner").map((item) => item.displayName).join(", ") || "미지정"}</span>{editMode && <input className="marketplace-change-summary" aria-label="Skill 변경 요약" placeholder="이번 변경 요약" value={editableChangeSummary} maxLength={500} onChange={(event) => setEditableChangeSummary(event.currentTarget.value)} />}</div>
              <div className="marketplace-package-actions">
                {skillView === "trash" ? <button className="lumina-primary-action" type="button" disabled={busy} onClick={() => void restoreSelectedSkill()}>{busy ? <LoaderCircle className="is-running" size={14} /> : <Undo2 size={14} />} 복원</button> : <>
                  {editMode ? <><button type="button" disabled={busy} onClick={() => { setEditMode(false); setRenamingPath(null); }}><X size={14} /> 취소</button><button className="lumina-primary-action" type="button" disabled={busy || (selected.canEdit && !editableName.trim())} onClick={() => void savePackageEdit()}><Save size={14} /> 초안 저장</button></> : selected.canCreateDraft && <button type="button" disabled={busy} onClick={() => void beginPackageEdit()}><Pencil size={14} /> {selected.canEdit ? "편집" : "내 버전으로 수정"}</button>}
                  {!editMode && selected.draft?.dirty && <button type="button" disabled={busy} onClick={() => void saveVersion()}><Check size={14} /> {nextSavedSkillDisplayVersion(selected)}로 저장</button>}
                  {!editMode && selected.versions.length > 0 && <button type="button" aria-pressed={versionHistoryOpen} disabled={busy} onClick={() => setVersionHistoryOpen((current) => !current)}><History size={14} /> {versionHistoryOpen ? "패키지 보기" : "버전 이력"}</button>}
                  {!editMode && installation && <div className="marketplace-project-selector" onClick={(event) => event.stopPropagation()}>
                    <button ref={projectScopeButtonRef} type="button" aria-haspopup="listbox" aria-expanded={projectScopeOpen} onClick={openProjectScope}><Settings2 size={14} /> 프로젝트 설정</button>
                    {projectScopeOpen && createPortal(<div ref={projectScopeMenuRef} className="marketplace-project-options project-options" style={{ top: projectScopePosition.top, right: projectScopePosition.right }} role="listbox" aria-label="Skill을 사용할 프로젝트" aria-multiselectable="true" onClick={(event) => event.stopPropagation()}>
                      <button className="marketplace-project-all" type="button" role="option" aria-selected={projectScopeDraft === null || projectScopeDraft.size === projects.length} onClick={() => setProjectScopeDraft(projectScopeDraft === null || projectScopeDraft.size === projects.length ? new Set() : null)}><FolderOpen size={15} /><span>{projectScopeDraft === null || projectScopeDraft.size === projects.length ? "전체 해제" : "전체 선택"}</span><Check size={14} /></button>
                      <div className="marketplace-project-option-list">{projects.map((item) => {
                        const checked = projectScopeDraft === null || projectScopeDraft.has(item.id);
                        return <button type="button" role="option" aria-selected={checked} key={item.id} onClick={() => toggleProjectScope(item.id)}><Folder size={15} /><span>{item.name}</span>{checked && <Check size={14} />}</button>;
                      })}</div>
                      <footer><span>{projectScopeDraft === null ? "모든 프로젝트" : `${projectScopeDraft.size}개 선택`}</span><div><button type="button" disabled={projectScopeBusy} onClick={() => setProjectScopeOpen(false)}>취소</button><button className="lumina-primary-action" type="button" disabled={projectScopeBusy} onClick={() => void saveProjectScope()}>{projectScopeBusy ? <LoaderCircle className="is-running" size={13} /> : <Save size={13} />} 적용</button></div></footer>
                    </div>, document.body)}
                  </div>}
                  {!editMode && <button className={`marketplace-detail-install-toggle ${installation ? "is-disable" : "is-primary lumina-primary-action"}`} type="button" aria-busy={pendingInstallationSurfaceById[selected.id] === "detail"} disabled={!latestVersion || busy || pendingInstallationSurfaceById[selected.id] === "detail"} onClick={() => selected && void toggleInstallation(selected, "detail")}>{pendingInstallationSurfaceById[selected.id] === "detail" ? <><LoaderCircle className="is-running" size={14} /> 처리 중</> : <>{installation ? <Power size={14} /> : <Download size={14} />}{installation ? "미사용" : "설치"}</>}</button>}
                  {!editMode && selected.canDelete && <button className={`text-danger ${deleteConfirmId === selected.id ? "is-delete-armed" : ""}`} type="button" aria-label={deleteConfirmId === selected.id ? `${selected.name} 삭제 경고, 한 번 더 누르면 보관함으로 이동` : `${selected.name} 삭제`} disabled={busy} onClick={() => void deleteSelectedSkill()}>{busy && deleteConfirmId === selected.id ? <LoaderCircle className="is-running" size={14} /> : deleteConfirmId === selected.id ? <AlertTriangle size={14} /> : <Trash2 size={14} />} {deleteConfirmId === selected.id ? "경고" : "삭제"}</button>}
                </>}
              </div>
            </div>
            {skillView === "trash" ? <div className="feature-state">복원하면 Skill 파일과 버전을 다시 사용할 수 있습니다.</div> : versionHistoryOpen ? <SkillVersionHistory
              versions={selected.versions}
              latestPublishedVersionId={selected.latestPublishedVersionId}
              comparison={versionComparison}
              busy={busy}
              canRollback={selected.currentUserRole === "owner" && Boolean(selected.latestPublishedVersionId)}
              onCompare={(fromVersionId, toVersionId) => void compareVersions(fromVersionId, toVersionId)}
              onRollback={(target, changeSummary) => void rollbackVersion(target, changeSummary)}
            /> : renderPackageBrowser()}
          </div>
        </>
      )}
    </section>
  );

  return (
    <div className="feature-view marketplace-view">
      <header className="feature-header"><div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><Store size={17} /><h1>마켓스토어</h1><div className="feature-kind-tabs" role="tablist" aria-label="Marketplace 유형"><button type="button" role="tab" aria-selected={marketKind === "skill"} onClick={() => setMarketKind("skill")}><Sparkles size={14} /> Skill</button><button type="button" role="tab" aria-selected={marketKind === "mcp"} onClick={() => setMarketKind("mcp")}><Wrench size={14} /> MCP</button></div><span>탐색·설치·관리</span></div><div><button type="button" aria-label="새로 고침" onClick={() => void refreshRepository()}><RefreshCw size={15} /></button></div></header>
      {marketKind === "skill" && <div className="marketplace-toolbar">
        <div className="marketplace-scope-tabs" role="tablist" aria-label="Skill 보기">
          <button type="button" role="tab" aria-selected={skillView === "catalog"} onClick={returnToCatalog}><Package size={14} /> 카탈로그 <span>{catalogTabCount}</span></button>
          <button type="button" role="tab" aria-selected={skillView === "installed"} onClick={() => { setEnteredInstalledFromCatalog(false); setSkillView("installed"); }}><Download size={14} /> 설치됨 <span>{counts.installed}</span></button>
          <button type="button" role="tab" aria-selected={skillView === "drafts"} onClick={() => { setEnteredInstalledFromCatalog(false); setSkillView("drafts"); }}><Sparkles size={14} /> 내 초안 <span>{counts.drafts}</span></button>
          <button className="tooltip-control" type="button" role="tab" aria-selected={skillView === "trash"} data-tooltip="삭제한 Skill은 30일 동안 보관되며 그 전에 복원할 수 있습니다." onClick={() => { setEnteredInstalledFromCatalog(false); setSkillView("trash"); }}><Trash2 size={14} /> 삭제됨 <span>{counts.trashed}</span></button>
        </div>
        {skillView !== "catalog" && <label className="marketplace-search"><Search size={14} /><input aria-label="Skill 검색" placeholder="Skill 이름 또는 설명 검색" value={query} onChange={(event) => setQuery(event.currentTarget.value)} /></label>}
      </div>}
      {marketKind === "mcp" && <div className="marketplace-toolbar">
        <div className="marketplace-scope-tabs" role="tablist" aria-label="MCP 보기">
          <button type="button" role="tab" aria-selected={mcpView === "catalog"} onClick={() => setMcpView("catalog")}><Package size={14} /> 카탈로그·설치</button>
          {canManage && <button type="button" role="tab" aria-selected={mcpView === "admin"} onClick={() => setMcpView("admin")}><ServerCog size={14} /> 정의 관리</button>}
        </div>
      </div>}
      {error && <div className="feature-error" role="alert">{error}</div>}
      {marketKind === "mcp" ? mcpView === "admin" && canManage ? <AdminMcpPanel key={mcpRefreshKey} /> : <McpMarketplacePanel key={`${projectId ?? "none"}:${mcpRefreshKey}`} projectId={projectId} /> : skillView === "catalog" ? <SkillCatalogPanel
        catalog={visibleCatalog}
        loading={!hasCachedCatalog && visibleCatalog.items.length === 0 && (catalogLoading || !error)}
        loadingMore={catalogLoadingMore}
        query={catalogQuery}
        category={catalogCategory}
        tag={catalogTag}
        sort={catalogSort}
        pendingInstallIds={pendingCatalogInstallIds}
        pendingLikeIds={pendingLikeIds}
        scrollPosition={catalogScrollPosition}
        onQueryChange={setCatalogQuery}
        onCategoryChange={setCatalogCategory}
        onTagChange={setCatalogTag}
        onSortChange={setCatalogSort}
        onReset={() => { setCatalogQuery(""); setCatalogCategory(""); setCatalogTag(""); }}
        onToggleInstall={(item) => void toggleCatalogInstallation(item)}
        onToggleLike={(item) => void toggleCatalogLike(item)}
        onView={viewCatalogSkill}
        onScrollPositionChange={setCatalogScrollPosition}
        onLoadMore={() => void refreshCatalog({ offset: catalog.items.length, append: true })}
      /> : <ResizableSplitPane storageKey="lumina:marketplace-list-width" ariaLabel="Skill 목록 너비 조절" className="marketplace-split">
        <aside className="feature-list" aria-label={skillView === "trash" ? "삭제된 Skill 목록" : "Skill 목록"}>
          {loading && (!hasCachedItems || !hasCachedTrash || !hasCachedInstallations) ? <div className="feature-state"><LoaderCircle className="is-running" size={16} /> 불러오는 중</div> : visibleItems.length === 0 ? <div className="feature-state">조건에 맞는 Skill이 없습니다.</div> : visibleItems.map((item) => {
            const itemInstallation = installations.find((entry) => entry.extensionId === item.id) ?? null;
            const itemVersion = item.versions.at(-1) ?? null;
            const itemInstallationPending = pendingInstallationSurfaceById[item.id] === "list";
            return <div className={`marketplace-skill-row ${item.id === selected?.id ? "is-selected" : ""}`} key={item.id}>
              <button className="marketplace-skill-select" type="button" onClick={() => setSelectedId(item.id)}>
                <span><strong>{item.name}</strong><small>{item.description || item.slug}</small>{skillView === "trash" && <small>{trashRetentionLabel(item.purgesAt)}</small>}<small className="marketplace-tags" aria-label="Skill 태그">{skillTags(item).map((tag) => <span key={tag}>#{tag}</span>)}</small></span>
              </button>
              {skillView !== "trash" && <MarketplaceInstallButton name={item.name} installed={Boolean(itemInstallation)} pending={itemInstallationPending} disabled={!itemVersion} onClick={() => void toggleInstallation(item, "list")} />}
            </div>;
          })}
        </aside>
        {renderSkillDetail()}
      </ResizableSplitPane>}
    </div>
  );
}
