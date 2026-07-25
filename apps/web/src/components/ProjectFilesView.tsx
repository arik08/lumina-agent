import {
  AlertCircle,
  ChevronDown,
  ChevronRight,
  Check,
  CheckCheck,
  Code2,
  Download,
  Eye,
  FilePlus2,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  LoaderCircle,
  Menu,
  Pencil,
  RefreshCw,
  Search,
  Square,
  SquareCheckBig,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { type CSSProperties, type DragEvent, type MouseEvent, type ReactNode, type RefObject, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ApiError } from "../api";
import { projectFilesApi } from "../feature-api";

const api = { projectFiles: projectFilesApi };
import type { ArtifactDownload, ProjectFileDetail, ProjectFileSummary, ProjectFolderSummary } from "../api-types";
import { useCachedViewState } from "../view-data-cache";
import { ArtifactHtmlPreview } from "./ArtifactHtmlPreview";
import { MarkdownResponse } from "./ConversationTurn";
import { ResizableSplitPane } from "./ResizableSplitPane";

interface ProjectFilesViewProps {
  projectId: string | null;
  requestedFileId?: string | null;
  onOpenNavigation: () => void;
}

interface UploadCandidate {
  file: File;
  logicalPath: string;
}

interface DropFileEntry {
  isFile: true;
  isDirectory: false;
  fullPath: string;
  file: (success: (file: File) => void, failure?: (error: DOMException) => void) => void;
}

interface DropDirectoryReader {
  readEntries: (success: (entries: DropEntry[]) => void, failure?: (error: DOMException) => void) => void;
}

interface DropDirectoryEntry {
  isFile: false;
  isDirectory: true;
  fullPath: string;
  createReader: () => DropDirectoryReader;
}

type DropEntry = DropFileEntry | DropDirectoryEntry;

interface FileTreeNode {
  key: string;
  type: "folder" | "file";
  name: string;
  path: string;
  children: FileTreeNode[];
  file?: ProjectFileSummary;
}

interface TreeContextMenu {
  x: number;
  y: number;
  node: FileTreeNode | null;
  themeDark: boolean;
}

type TreeEditor =
  | { mode: "create"; parentPath: string; value: string }
  | { mode: "rename"; node: FileTreeNode; value: string };

type PreviewState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; kind: "text"; text: string; truncated: boolean }
  | { status: "ready"; kind: "html"; source: string }
  | { status: "ready"; kind: "image" | "pdf" | "video" | "audio"; url: string }
  | { status: "unsupported"; mimeType: string }
  | { status: "error"; message: string };

const treeCollator = new Intl.Collator("ko-KR", { numeric: true, sensitivity: "base" });
const treeDragMime = "application/x-lumina-file-tree";
const textExtensions = new Set([
  "css", "csv", "html", "htm", "ini", "js", "json", "jsx", "log", "md", "py", "sql", "svg", "toml", "ts", "tsx", "txt", "xml", "yaml", "yml",
]);

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "파일 요청을 처리하지 못했습니다.";
}

function normalizeUploadPath(value: string) {
  return value.replaceAll("\\", "/").replace(/^\/+/, "");
}

function saveDownload(download: ArtifactDownload) {
  const url = URL.createObjectURL(download.blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = download.fileName;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function buildFileTree(files: ProjectFileSummary[], folders: ProjectFolderSummary[]) {
  const roots: FileTreeNode[] = [];
  const folderByPath = new Map<string, FileTreeNode>();
  const ensureFolder = (path: string) => {
    const parts = path.split("/").filter(Boolean);
    let children = roots;
    let currentPath = "";
    for (const part of parts) {
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      let folder = folderByPath.get(currentPath);
      if (!folder) {
        folder = { key: `folder:${currentPath}`, type: "folder", name: part, path: currentPath, children: [] };
        folderByPath.set(currentPath, folder);
        children.push(folder);
      }
      children = folder.children;
    }
    return children;
  };
  folders.forEach((folder) => ensureFolder(folder.logicalPath));
  for (const file of files) {
    const parts = file.logicalPath.split("/").filter(Boolean);
    const children = ensureFolder(parts.slice(0, -1).join("/"));
    children.push({
      key: `file:${file.id}`,
      type: "file",
      name: parts.at(-1) ?? file.displayName,
      path: file.logicalPath,
      children: [],
      file,
    });
  }
  const sortNodes = (nodes: FileTreeNode[]) => {
    nodes.sort((left, right) => Number(left.type === "file") - Number(right.type === "file") || treeCollator.compare(left.name, right.name));
    nodes.forEach((node) => sortNodes(node.children));
  };
  sortNodes(roots);
  return roots;
}

function parentPath(path: string) {
  return path.split("/").slice(0, -1).join("/");
}

function childPath(parent: string, name: string) {
  return parent ? `${parent}/${name}` : name;
}

function isSameOrDescendantPath(path: string, parent: string) {
  const pathParts = path.toLocaleLowerCase("en-US").split("/");
  const parentParts = parent.toLocaleLowerCase("en-US").split("/");
  return parentParts.every((part, index) => pathParts[index] === part);
}

function collectFolderPaths(nodes: FileTreeNode[], paths: string[] = []) {
  for (const node of nodes) {
    if (node.type === "folder") {
      paths.push(node.path);
      collectFolderPaths(node.children, paths);
    }
  }
  return paths;
}

function findTreeNode(nodes: FileTreeNode[], key: string): FileTreeNode | null {
  for (const node of nodes) {
    if (node.key === key) return node;
    const child = findTreeNode(node.children, key);
    if (child) return child;
  }
  return null;
}

function collectSelectedRoots(nodes: FileTreeNode[], selectedKeys: Set<string>, roots: FileTreeNode[] = []) {
  for (const node of nodes) {
    if (selectedKeys.has(node.key)) {
      roots.push(node);
    } else {
      collectSelectedRoots(node.children, selectedKeys, roots);
    }
  }
  return roots;
}

function readFileEntry(entry: DropFileEntry) {
  return new Promise<UploadCandidate>((resolve, reject) => {
    entry.file(
      (file) => resolve({ file, logicalPath: normalizeUploadPath(entry.fullPath || file.name) }),
      (error) => reject(error),
    );
  });
}

function readDirectoryBatch(reader: DropDirectoryReader) {
  return new Promise<DropEntry[]>((resolve, reject) => reader.readEntries(resolve, reject));
}

async function readDropEntry(entry: DropEntry): Promise<UploadCandidate[]> {
  if (entry.isFile) return [await readFileEntry(entry)];
  const reader = entry.createReader();
  const children: DropEntry[] = [];
  for (;;) {
    const batch = await readDirectoryBatch(reader);
    if (batch.length === 0) break;
    children.push(...batch);
  }
  return (await Promise.all(children.map(readDropEntry))).flat();
}

async function collectDroppedFiles(dataTransfer: DataTransfer) {
  const entries: DropEntry[] = [];
  for (const item of Array.from(dataTransfer.items)) {
    const entry = (item as unknown as { webkitGetAsEntry?: () => DropEntry | null }).webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  if (entries.length > 0) return (await Promise.all(entries.map(readDropEntry))).flat();
  return Array.from(dataTransfer.files).map((file) => ({ file, logicalPath: file.name }));
}

function classifyPreview(detail: ProjectFileDetail, blob: Blob) {
  const mimeType = (blob.type || detail.mimeType).toLocaleLowerCase("en-US");
  const extension = detail.displayName.split(".").at(-1)?.toLocaleLowerCase("en-US") ?? "";
  if (mimeType.startsWith("image/")) return "image";
  if (mimeType === "application/pdf") return "pdf";
  if (mimeType === "text/html" || extension === "html" || extension === "htm") return "html";
  if (mimeType.startsWith("video/")) return "video";
  if (mimeType.startsWith("audio/")) return "audio";
  if (mimeType.startsWith("text/") || textExtensions.has(extension) || mimeType.includes("json") || mimeType.includes("xml")) return "text";
  return "unsupported";
}

function looksLikeStandaloneHtml(value: string) {
  const normalized = value.trimStart().toLocaleLowerCase("en-US");
  return ["<!doctype html", "<html", "<head", "<body"].every((marker) => normalized.includes(marker));
}

function injectArtifactPreviewBridge(value: string) {
  const bridgePath = "/artifact-preview-bridge.js";
  if (value.includes(bridgePath)) return value;
  const bridge = `<script src="${new URL(bridgePath, window.location.origin).href}"></script>`;
  return /<\/body\s*>/i.test(value)
    ? value.replace(/<\/body\s*>/i, `${bridge}</body>`)
    : `${value}${bridge}`;
}

function isMarkdownFile(detail: ProjectFileDetail) {
  const extension = detail.displayName.split(".").at(-1)?.toLocaleLowerCase("en-US");
  return extension === "md" || extension === "markdown" || detail.mimeType.toLocaleLowerCase("en-US") === "text/markdown";
}

function renderFilePreview(
  preview: PreviewState,
  detail: ProjectFileDetail,
  markdownSource: boolean,
  htmlPreviewFrameRef: RefObject<HTMLIFrameElement | null>,
): ReactNode {
  if (preview.status === "loading" || preview.status === "idle") {
    return <div className="feature-state"><LoaderCircle className="is-running" size={15} /> Preview 준비 중</div>;
  }
  if (preview.status === "error") {
    return <div className="file-preview-message"><strong>Preview를 열지 못했습니다.</strong><span>{preview.message}</span></div>;
  }
  if (preview.status === "unsupported") {
    return <div className="file-preview-message"><FileText size={28} /><strong>브라우저 Preview를 지원하지 않는 형식입니다.</strong><span>{preview.mimeType || "알 수 없는 파일 형식"} · 다운로드해서 확인해 주세요.</span></div>;
  }
  if (preview.kind === "text") {
    return <>{isMarkdownFile(detail) && !markdownSource
      ? <div className="file-preview-markdown conversation-response-typography"><MarkdownResponse text={preview.text} /></div>
      : <pre>{preview.text}</pre>}
    {preview.truncated && <div className="file-preview-truncated">Preview는 앞부분만 표시합니다.</div>}</>;
  }
  if (preview.kind === "image") return <img src={preview.url} alt={`${detail.displayName} Preview`} loading="lazy" decoding="async" />;
  if (preview.kind === "pdf") return <iframe src={preview.url} title={`${detail.displayName} PDF Preview`} />;
  if (preview.kind === "html") return <ArtifactHtmlPreview
    frameRef={htmlPreviewFrameRef}
    source={preview.source}
    previewUrl={null}
    title={`${detail.displayName} HTML Preview`}
  />;
  if (preview.kind === "video") return <video src={preview.url} controls />;
  return <audio src={preview.url} controls />;
}

export function ProjectFilesView({ projectId, requestedFileId = null, onOpenNavigation }: ProjectFilesViewProps) {
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);
  const htmlPreviewFrameRef = useRef<HTMLIFrameElement>(null);
  const draggedNodeRef = useRef<FileTreeNode | null>(null);
  const loadingMoreRef = useRef(false);
  const loadMoreControllerRef = useRef<AbortController | null>(null);
  const [query, setQuery] = useState("");
  const cacheKey = `files:${projectId ?? "none"}:${query.trim().toLocaleLowerCase("ko-KR")}`;
  const [files, setFiles, hasCachedFiles] = useCachedViewState<ProjectFileSummary[]>(`${cacheKey}:items`, []);
  const [folders, setFolders, hasCachedFolders] = useCachedViewState<ProjectFolderSummary[]>(`${cacheKey}:folders`, []);
  const [selectedId, setSelectedId] = useState<string | null>(requestedFileId);
  const [selectedFolderPath, setSelectedFolderPath] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectFileDetail | null>(null);
  const [loading, setLoading] = useState(!hasCachedFiles || !hasCachedFolders);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [draggedNode, setDraggedNode] = useState<FileTreeNode | null>(null);
  const [treeDropPath, setTreeDropPath] = useState<string | null | undefined>(undefined);
  const [contextMenu, setContextMenu] = useState<TreeContextMenu | null>(null);
  const [treeEditor, setTreeEditor] = useState<TreeEditor | null>(null);
  const [contextDeleteConfirming, setContextDeleteConfirming] = useState<string | null>(null);
  const [bulkSelectionMode, setBulkSelectionMode] = useState(false);
  const [selectedTreeKeys, setSelectedTreeKeys] = useState<Set<string>>(new Set());
  const [bulkDeleteArmed, setBulkDeleteArmed] = useState(false);
  const [deleteConfirming, setDeleteConfirming] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<PreviewState>({ status: "idle" });
  const [markdownSource, setMarkdownSource] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const tree = useMemo(() => buildFileTree(files, folders), [files, folders]);
  const folderPaths = useMemo(() => collectFolderPaths(tree), [tree]);
  const selectedFolderFiles = useMemo(
    () => selectedFolderPath ? files.filter((file) => file.logicalPath.startsWith(`${selectedFolderPath}/`)) : [],
    [files, selectedFolderPath],
  );

  useEffect(() => {
    folderInputRef.current?.setAttribute("webkitdirectory", "");
    folderInputRef.current?.setAttribute("directory", "");
  }, []);

  useEffect(() => {
    setBulkSelectionMode(false);
    setSelectedTreeKeys(new Set());
    setBulkDeleteArmed(false);
  }, [projectId, query]);

  useEffect(() => {
    setMarkdownSource(false);
  }, [selectedId]);

  useEffect(() => {
    if (!requestedFileId) return;
    setSelectedFolderPath(null);
    setSelectedId(requestedFileId);
  }, [requestedFileId]);

  useEffect(() => {
    loadMoreControllerRef.current?.abort();
    loadMoreControllerRef.current = null;
    loadingMoreRef.current = false;
    setLoadingMore(false);
    if (!projectId) {
      setFiles([]);
      setFolders([]);
      setSelectedId(null);
      setSelectedFolderPath(null);
      setDetail(null);
      setBulkSelectionMode(false);
      setSelectedTreeKeys(new Set());
      setBulkDeleteArmed(false);
      setNextCursor(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      Promise.all([
        api.projectFiles.list(projectId, query, false, undefined, controller.signal),
        api.projectFiles.listFolders(projectId, controller.signal),
      ])
        .then(([filePage, nextFolders]) => {
          setFiles(filePage.items);
          setNextCursor(filePage.nextCursor);
          const normalizedQuery = query.trim().toLocaleLowerCase("ko-KR");
          setFolders(normalizedQuery ? nextFolders.filter((folder) => folder.logicalPath.toLocaleLowerCase("ko-KR").includes(normalizedQuery)) : nextFolders);
        })
        .catch((caught) => {
          if (!controller.signal.aborted) setError(errorMessage(caught));
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 140);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [projectId, query, refreshKey]);

  async function loadMoreFiles() {
    if (!projectId || !nextCursor || loadingMoreRef.current) return;
    const controller = new AbortController();
    loadMoreControllerRef.current = controller;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    try {
      const page = await api.projectFiles.list(
        projectId,
        query,
        false,
        nextCursor,
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setFiles((current) => {
        const known = new Set(current.map((file) => file.id));
        return [...current, ...page.items.filter((file) => !known.has(file.id))];
      });
      setNextCursor(page.nextCursor);
    } catch (caught) {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    } finally {
      if (loadMoreControllerRef.current === controller) {
        loadMoreControllerRef.current = null;
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }

  useEffect(() => () => loadMoreControllerRef.current?.abort(), []);

  useEffect(() => {
    if (!contextMenu) return;
    const close = () => {
      setContextMenu(null);
      setContextDeleteConfirming(null);
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", handleKey);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", handleKey);
    };
  }, [contextMenu]);

  useEffect(() => {
    if (query.trim()) setExpandedFolders(new Set(folderPaths));
    else setExpandedFolders((current) => current.size > 0 ? current : new Set(tree.filter((node) => node.type === "folder").map((node) => node.path)));
  }, [folderPaths, query, tree]);

  useEffect(() => {
    if (selectedId && (selectedId === requestedFileId || files.some((file) => file.id === selectedId))) return;
    if (selectedFolderPath && folderPaths.includes(selectedFolderPath)) {
      setSelectedId(null);
      return;
    }
    setSelectedFolderPath(null);
    setSelectedId(files[0]?.id ?? null);
  }, [files, folderPaths, requestedFileId, selectedFolderPath, selectedId]);

  useEffect(() => {
    setDeleteConfirming(false);
    if (!projectId || !selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    api.projectFiles.get(projectId, selectedId, controller.signal)
      .then(setDetail)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [projectId, selectedId, refreshKey]);

  useEffect(() => {
    if (!projectId || !detail) {
      setPreview({ status: "idle" });
      return;
    }
    const controller = new AbortController();
    let objectUrl: string | null = null;
    setPreview({ status: "loading" });
    api.projectFiles.download(projectId, detail.id, undefined, controller.signal)
      .then(async (download) => {
        const kind = classifyPreview(detail, download.blob);
        if (kind === "html") {
          let text = await download.blob.text();
          const limit = 240_000;
          if (!looksLikeStandaloneHtml(text)) {
            setPreview({ status: "ready", kind: "text", text: text.slice(0, limit), truncated: text.length > limit });
            return;
          }
          text = injectArtifactPreviewBridge(text);
          setPreview({ status: "ready", kind, source: text });
          return;
        }
        if (kind === "text") {
          const text = await download.blob.text();
          if (looksLikeStandaloneHtml(text)) {
            setPreview({ status: "ready", kind: "html", source: injectArtifactPreviewBridge(text) });
            return;
          }
          const limit = 240_000;
          setPreview({ status: "ready", kind: "text", text: text.slice(0, limit), truncated: text.length > limit });
          return;
        }
        if (kind === "unsupported") {
          setPreview({ status: "unsupported", mimeType: download.blob.type || detail.mimeType });
          return;
        }
        objectUrl = URL.createObjectURL(download.blob);
        setPreview({ status: "ready", kind, url: objectUrl });
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setPreview({ status: "error", message: errorMessage(caught) });
      });
    return () => {
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [detail, projectId]);

  const uploadFiles = async (candidates: UploadCandidate[]) => {
    if (!projectId || candidates.length === 0 || busy) return;
    const unique = Array.from(new Map(candidates.map((item) => [item.logicalPath.toLocaleLowerCase("en-US"), item])).values());
    setBusy(true);
    setError(null);
    try {
      let lastId: string | undefined;
      for (const candidate of unique.sort((left, right) => treeCollator.compare(left.logicalPath, right.logicalPath))) {
        const created = await api.projectFiles.upload(projectId, candidate.file, candidate.logicalPath, "사용자 업로드");
        lastId = created.id;
      }
      setSelectedFolderPath(null);
      setSelectedId(lastId ?? null);
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const handleDrop = async (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDropActive(false);
    try {
      await uploadFiles(await collectDroppedFiles(event.dataTransfer));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  };

  const moveTreeNode = async (node: FileTreeNode, destinationPath: string) => {
    if (!projectId || busy) return;
    if (node.type === "folder" && isSameOrDescendantPath(destinationPath, node.path)) {
      setTreeDropPath(undefined);
      setDraggedNode(null);
      draggedNodeRef.current = null;
      if (destinationPath !== node.path) setError("폴더를 자기 하위로 이동할 수 없습니다.");
      return;
    }
    const targetPath = childPath(destinationPath, node.name);
    if (targetPath.toLocaleLowerCase("en-US") === node.path.toLocaleLowerCase("en-US")) {
      setTreeDropPath(undefined);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (node.type === "file" && node.file) {
        await api.projectFiles.move(projectId, node.file.id, targetPath, node.file.revision);
        setSelectedFolderPath(null);
        setSelectedId(node.file.id);
      } else {
        await api.projectFiles.moveFolder(projectId, node.path, targetPath);
        setSelectedId(null);
        setSelectedFolderPath(targetPath);
      }
      if (destinationPath) setExpandedFolders((current) => new Set(current).add(destinationPath));
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
      setDraggedNode(null);
      draggedNodeRef.current = null;
      setTreeDropPath(undefined);
    }
  };

  const openContextMenu = (event: MouseEvent, node: FileTreeNode | null) => {
    event.preventDefault();
    event.stopPropagation();
    setContextDeleteConfirming(null);
    setContextMenu({
      x: Math.max(8, Math.min(event.clientX, window.innerWidth - 190)),
      y: Math.max(8, Math.min(event.clientY, window.innerHeight - 150)),
      node,
      themeDark: Boolean(event.currentTarget.closest(".theme-dark")),
    });
  };

  const beginCreateFolder = (parent: string) => {
    setContextMenu(null);
    setContextDeleteConfirming(null);
    setTreeEditor({ mode: "create", parentPath: parent, value: "새 폴더" });
    if (parent) setExpandedFolders((current) => new Set(current).add(parent));
  };

  const beginRename = (node: FileTreeNode) => {
    setContextMenu(null);
    setContextDeleteConfirming(null);
    setTreeEditor({ mode: "rename", node, value: node.name });
  };

  const commitTreeEditor = async () => {
    if (!projectId || !treeEditor || busy) return;
    const name = treeEditor.value.trim();
    if (!name || name === "." || name === ".." || /[\\/]/.test(name)) {
      setError("이름에는 / 또는 \\를 사용할 수 없습니다.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (treeEditor.mode === "create") {
        const path = childPath(treeEditor.parentPath, name);
        await api.projectFiles.createFolder(projectId, path);
        setSelectedId(null);
        setSelectedFolderPath(path);
      } else {
        const { node } = treeEditor;
        const targetPath = childPath(parentPath(node.path), name);
        if (node.type === "file" && node.file) {
          await api.projectFiles.move(projectId, node.file.id, targetPath, node.file.revision);
          setSelectedFolderPath(null);
          setSelectedId(node.file.id);
        } else {
          await api.projectFiles.moveFolder(projectId, node.path, targetPath);
          setSelectedId(null);
          setSelectedFolderPath(targetPath);
        }
      }
      setTreeEditor(null);
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const removeContextNode = async (node: FileTreeNode) => {
    if (!projectId || busy) return;
    if (contextDeleteConfirming !== node.key) {
      setContextDeleteConfirming(node.key);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      if (node.type === "file" && node.file) {
        await api.projectFiles.delete(projectId, node.file.id, node.file.revision);
        if (selectedId === node.file.id) {
          setDetail(null);
          setSelectedId(null);
        }
      } else {
        await api.projectFiles.deleteFolder(projectId, node.path);
        if (selectedFolderPath && (selectedFolderPath === node.path || selectedFolderPath.startsWith(`${node.path}/`))) {
          setSelectedFolderPath(null);
        }
        if (detail?.logicalPath.startsWith(`${node.path}/`)) {
          setDetail(null);
          setSelectedId(null);
        }
      }
      setContextMenu(null);
      setContextDeleteConfirming(null);
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const toggleTreeSelection = (key: string) => {
    setBulkDeleteArmed(false);
    setSelectedTreeKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const toggleBulkSelectionMode = () => {
    setBulkSelectionMode((current) => !current);
    setSelectedTreeKeys(new Set());
    setBulkDeleteArmed(false);
    setContextMenu(null);
  };

  const removeSelectedTreeNodes = async () => {
    if (!projectId || selectedTreeKeys.size === 0 || busy) return;
    if (!bulkDeleteArmed) {
      setBulkDeleteArmed(true);
      return;
    }
    const selectedRoots = collectSelectedRoots(tree, selectedTreeKeys);
    setBusy(true);
    setError(null);
    try {
      for (const node of selectedRoots) {
        if (node.type === "folder") await api.projectFiles.deleteFolder(projectId, node.path);
        else if (node.file) await api.projectFiles.delete(projectId, node.file.id, node.file.revision);
      }
      setDetail(null);
      setSelectedId(null);
      setSelectedFolderPath(null);
      setSelectedTreeKeys(new Set());
      setBulkDeleteArmed(false);
      setBulkSelectionMode(false);
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(errorMessage(caught));
      setBulkDeleteArmed(false);
      setRefreshKey((value) => value + 1);
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    if (!projectId || !detail) return;
    setBusy(true);
    try {
      saveDownload(await api.projectFiles.download(projectId, detail.id));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!projectId || !detail) return;
    if (!deleteConfirming) {
      setDeleteConfirming(true);
      return;
    }
    setBusy(true);
    try {
      await api.projectFiles.delete(projectId, detail.id, detail.revision);
      setDetail(null);
      setSelectedId(null);
      setDeleteConfirming(false);
      setRefreshKey((value) => value + 1);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const chooseFile = (id: string) => {
    setSelectedFolderPath(null);
    setSelectedId(id);
  };

  const chooseFolder = (path: string) => {
    setSelectedId(null);
    setSelectedFolderPath(path);
    setExpandedFolders((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const renderTreeEditor = (depth: number) => treeEditor ? (
    <form
      className="file-tree-editor"
      style={{ "--tree-depth": depth } as CSSProperties}
      onSubmit={(event) => { event.preventDefault(); void commitTreeEditor(); }}
    >
      {treeEditor.mode === "create" || treeEditor.node.type === "folder" ? <Folder size={15} /> : <FileText size={15} />}
      <input
        autoFocus
        aria-label={treeEditor.mode === "create" ? "새 폴더 이름" : "새 이름"}
        value={treeEditor.value}
        onFocus={(event) => event.currentTarget.select()}
        onChange={(event) => setTreeEditor({ ...treeEditor, value: event.currentTarget.value })}
        onKeyDown={(event) => { if (event.key === "Escape") setTreeEditor(null); }}
      />
      <button type="submit" aria-label="저장" disabled={busy}><Check size={13} /></button>
      <button type="button" aria-label="취소" onClick={() => setTreeEditor(null)}><X size={13} /></button>
    </form>
  ) : null;

  const renderTree = (nodes: FileTreeNode[], depth = 0): ReactNode => nodes.map((node) => {
    const selected = node.type === "folder" ? node.path === selectedFolderPath : node.file?.id === selectedId;
    const expanded = node.type === "folder" && expandedFolders.has(node.path);
    const renaming = treeEditor?.mode === "rename" && treeEditor.node.key === node.key;
    const dropTarget = node.type === "folder" && treeDropPath === node.path;
    const bulkSelected = selectedTreeKeys.has(node.key);
    return (
      <div className="file-tree-node" key={node.key}>
        {renaming ? renderTreeEditor(depth) : (
          <button
            className={`file-tree-row is-${node.type} ${selected && !bulkSelectionMode ? "is-selected" : ""} ${bulkSelected ? "is-bulk-selected" : ""} ${dropTarget ? "is-drop-target" : ""}`}
            type="button"
            style={{ "--tree-depth": depth } as CSSProperties}
            draggable={!busy}
            aria-pressed={bulkSelectionMode ? bulkSelected : undefined}
            onClick={() => bulkSelectionMode ? toggleTreeSelection(node.key) : node.type === "folder" ? chooseFolder(node.path) : node.file && chooseFile(node.file.id)}
            onContextMenu={(event) => openContextMenu(event, node)}
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = "move";
              event.dataTransfer.setData(treeDragMime, node.key);
              draggedNodeRef.current = node;
              setDraggedNode(node);
            }}
            onDragEnd={() => { draggedNodeRef.current = null; setDraggedNode(null); setTreeDropPath(undefined); }}
            onDragOver={node.type === "folder" ? (event) => {
              const source = draggedNodeRef.current;
              if (!source && !Array.from(event.dataTransfer.types).includes(treeDragMime)) return;
              if (source?.type === "folder" && isSameOrDescendantPath(node.path, source.path)) {
                event.stopPropagation();
                event.dataTransfer.dropEffect = "none";
                setTreeDropPath(undefined);
                return;
              }
              event.preventDefault();
              event.stopPropagation();
              event.dataTransfer.dropEffect = "move";
              setTreeDropPath(node.path);
            } : undefined}
            onDrop={node.type === "folder" ? (event) => {
              const source = draggedNodeRef.current ?? findTreeNode(tree, event.dataTransfer.getData(treeDragMime));
              if (!source) return;
              event.preventDefault();
              event.stopPropagation();
              void moveTreeNode(source, node.path);
            } : undefined}
          >
            <span className="file-tree-chevron" aria-hidden="true">{node.type === "folder" ? expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} /> : null}</span>
            {bulkSelectionMode ? <span className="file-tree-selection" aria-hidden="true">{bulkSelected ? <SquareCheckBig size={14} /> : <Square size={14} />}</span> : null}
            {node.type === "folder" ? expanded ? <FolderOpen size={15} /> : <Folder size={15} /> : <FileText size={15} />}
            <span>{node.name}</span>
          </button>
        )}
        {node.type === "folder" && treeEditor?.mode === "create" && treeEditor.parentPath === node.path ? renderTreeEditor(depth + 1) : null}
        {node.type === "folder" && expanded ? renderTree(node.children, depth + 1) : null}
      </div>
    );
  });

  return (
    <>
    <div className="feature-view project-files-view">
      <header className="feature-header">
        <div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><FolderOpen size={17} /><h1>파일 저장소</h1><span>{files.length}개 · 사용자 전용 · @ 참조</span></div>
        <div><button className="file-workspace-refresh" type="button" aria-label="새로 고침" disabled={loading} onClick={() => setRefreshKey((value) => value + 1)}>{loading ? <LoaderCircle className="is-running" size={15} /> : <RefreshCw size={15} />}</button></div>
      </header>
      <input ref={uploadInputRef} className="visually-hidden" type="file" multiple onChange={(event) => { const selected = Array.from(event.currentTarget.files ?? []).map((file) => ({ file, logicalPath: file.name })); event.currentTarget.value = ""; void uploadFiles(selected); }} />
      <input ref={folderInputRef} className="visually-hidden" type="file" multiple onChange={(event) => { const selected = Array.from(event.currentTarget.files ?? []).map((file) => ({ file, logicalPath: normalizeUploadPath((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name) })); event.currentTarget.value = ""; void uploadFiles(selected); }} />
      <div className="feature-toolbar file-workspace-toolbar">
        <div
          className={`file-drop-target ${dropActive ? "is-active" : ""}`}
          onDragEnter={(event) => { event.preventDefault(); setDropActive(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={(event) => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropActive(false); }}
          onDrop={(event) => void handleDrop(event)}
        >
          <button type="button" disabled={!projectId || busy} onClick={() => uploadInputRef.current?.click()}><FilePlus2 size={13} /> 파일 선택</button>
          <button type="button" disabled={!projectId || busy} onClick={() => folderInputRef.current?.click()}><FolderOpen size={13} /> 폴더 선택</button>
          <span className="file-drop-hint" aria-hidden="true"><Upload size={14} /></span>
        </div>
        <label className="feature-search"><Search size={14} /><input value={query} placeholder="파일명 또는 폴더 경로 검색" onChange={(event) => setQuery(event.currentTarget.value)} /></label>
      </div>
      {error && <div className="feature-error" role="alert">{error}</div>}
      {!projectId ? <div className="feature-state">파일을 보관할 Project를 선택해 주세요.</div> : (
        <ResizableSplitPane storageKey="lumina:file-explorer-width" ariaLabel="파일 탐색기 너비 조절" className="file-workspace-split">
          <aside
            className={`file-workspace-explorer ${treeDropPath === null ? "is-root-drop-target" : ""}`}
            aria-label="Project 파일 탐색기"
            onContextMenu={(event) => openContextMenu(event, null)}
            onDragOver={(event) => {
              if (!draggedNodeRef.current && !Array.from(event.dataTransfer.types).includes(treeDragMime)) return;
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
              setTreeDropPath(null);
            }}
            onDrop={(event) => {
              const source = draggedNodeRef.current ?? findTreeNode(tree, event.dataTransfer.getData(treeDragMime));
              if (!source) return;
              event.preventDefault();
              void moveTreeNode(source, "");
            }}
          >
            <div className="file-explorer-heading">
              <FolderOpen size={14} /><strong>프로젝트 파일</strong>
              <div className="file-explorer-heading-actions">
                {bulkSelectionMode && selectedTreeKeys.size > 0 ? (
                  <button
                    className={`tooltip-control is-danger ${bulkDeleteArmed ? "is-armed" : ""}`}
                    type="button"
                    aria-label={bulkDeleteArmed ? "선택 항목 삭제 확인, 한 번 더 누르면 삭제" : "선택 항목 삭제"}
                    data-tooltip={bulkDeleteArmed ? "삭제경고" : "삭제"}
                    disabled={busy}
                    onClick={() => void removeSelectedTreeNodes()}
                  >
                    {busy ? <LoaderCircle className="is-running" size={14} /> : bulkDeleteArmed ? <AlertCircle size={14} /> : <Trash2 size={14} />}
                  </button>
                ) : null}
                <button
                  className={`file-explorer-bulk-toggle tooltip-control ${bulkSelectionMode ? "is-active" : ""}`}
                  type="button"
                  aria-label={bulkSelectionMode ? "여러 항목 선택 닫기" : "여러 항목 선택"}
                  aria-pressed={bulkSelectionMode}
                  data-tooltip={bulkSelectionMode ? "선택 닫기" : "여러 항목 선택"}
                  disabled={tree.length === 0 || busy}
                  onClick={toggleBulkSelectionMode}
                ><CheckCheck size={14} /></button>
              </div>
            </div>
            <div className="file-tree thin-scrollbar" onScroll={(event) => {
              const target = event.currentTarget;
              if (target.scrollHeight - target.scrollTop - target.clientHeight < 80) {
                void loadMoreFiles();
              }
            }}>
              {treeEditor?.mode === "create" && treeEditor.parentPath === "" ? renderTreeEditor(0) : null}
              {(!hasCachedFiles || !hasCachedFolders) && (loading || !error) ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 불러오는 중</div> : tree.length === 0 ? <div className="file-tree-empty"><Folder size={22} /><strong>아직 파일이 없습니다.</strong><span>우클릭해 폴더를 만들거나 파일을 놓아 주세요.</span></div> : renderTree(tree)}
              {loadingMore ? <div className="file-tree-loading-more"><LoaderCircle className="is-running" size={14} /> 파일을 더 불러오는 중</div> : null}
            </div>
          </aside>
          <section className="feature-detail file-workspace-viewer" aria-live="polite">
            {selectedFolderPath ? (
              <div className="folder-viewer">
                <header className="file-viewer-heading"><span className="file-viewer-icon"><FolderOpen size={22} /></span><div><h2>{selectedFolderPath.split("/").at(-1)}</h2><p>{selectedFolderPath}</p></div></header>
                <div className="folder-file-list">
                  {selectedFolderFiles.map((file) => <button type="button" key={file.id} onClick={() => chooseFile(file.id)}><FileText size={14} /><span><strong>{file.displayName}</strong><small>{file.logicalPath} · {formatBytes(file.size)}</small></span><ChevronRight size={14} /></button>)}
                </div>
              </div>
            ) : detailLoading ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 파일을 여는 중</div> : !detail ? (
              <div className="file-viewer-empty"><FileText size={28} /><strong>미리 볼 파일을 선택해 주세요.</strong><span>이 저장소의 파일과 폴더는 채팅에서 @로 참조할 수 있습니다.</span></div>
            ) : (
              <div className="file-viewer-document">
                <header className="file-viewer-heading">
                  <span className="file-viewer-icon"><FileText size={22} /></span>
                  <div><h2>{detail.displayName}</h2></div>
                  <div className="file-viewer-actions">
                    <div className="file-viewer-meta" aria-label="파일 정보"><span>{formatBytes(detail.size)}</span><span>{formatDate(detail.createdAt)}</span></div>
                    {isMarkdownFile(detail) ? (
                      <button
                        className={`file-preview-mode-toggle tooltip-control ${markdownSource ? "is-active" : ""}`}
                        type="button"
                        aria-label={markdownSource ? "렌더링 보기" : "원문 보기"}
                        aria-pressed={markdownSource}
                        data-tooltip={markdownSource ? "렌더링 보기" : "원문 보기"}
                        onClick={() => setMarkdownSource((current) => !current)}
                      >{markdownSource ? <Eye size={14} /> : <Code2 size={14} />}</button>
                    ) : null}
                    <button type="button" disabled={busy} onClick={() => void download()}><Download size={14} /> 다운로드</button>
                    <button className={`is-danger ${deleteConfirming ? "is-confirming" : ""}`} type="button" disabled={busy} onClick={() => void remove()}><Trash2 size={14} /> {deleteConfirming ? "한 번 더 눌러 삭제" : "삭제"}</button>
                  </div>
                </header>
                <div className="file-preview-surface thin-scrollbar">
                  {renderFilePreview(preview, detail, markdownSource, htmlPreviewFrameRef)}
                </div>
              </div>
            )}
          </section>
        </ResizableSplitPane>
      )}
    </div>
    {contextMenu ? createPortal(
      <div
        className={`file-tree-context-menu${contextMenu.themeDark ? " theme-dark" : ""}`}
        role="menu"
        aria-label="파일 탐색기 메뉴"
        style={{ left: contextMenu.x, top: contextMenu.y }}
        onPointerDown={(event) => event.stopPropagation()}
      >
        {contextMenu.node?.type !== "file" ? (
          <button type="button" role="menuitem" onClick={() => beginCreateFolder(contextMenu.node?.path ?? "")}>
            <FolderPlus size={14} /> 새 폴더
          </button>
        ) : null}
        {contextMenu.node ? (
          <>
            <button type="button" role="menuitem" onClick={() => beginRename(contextMenu.node!)}>
              <Pencil size={14} /> 이름 변경
            </button>
            <button
              className={contextDeleteConfirming === contextMenu.node.key ? "is-confirming" : "is-danger"}
              type="button"
              role="menuitem"
              disabled={busy}
              onClick={() => void removeContextNode(contextMenu.node!)}
            >
              <Trash2 size={14} /> {contextDeleteConfirming === contextMenu.node.key ? "한 번 더 눌러 삭제" : "삭제"}
            </button>
          </>
        ) : null}
      </div>,
      document.body,
    ) : null}
    </>
  );
}
