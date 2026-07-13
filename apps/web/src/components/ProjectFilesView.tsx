import {
  Download,
  FilePlus2,
  FileText,
  FolderOpen,
  LoaderCircle,
  Menu,
  Move,
  RefreshCw,
  Search,
  Trash2,
  Upload,
} from "lucide-react";
import { type DragEvent, type FormEvent, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { ArtifactDownload, ProjectFileDetail, ProjectFileSummary } from "../api-types";

interface ProjectFilesViewProps {
  projectId: string | null;
  onOpenNavigation: () => void;
  onToast: (message: string) => void;
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "파일 요청을 처리하지 못했습니다.";
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

export function ProjectFilesView({ projectId, onOpenNavigation, onToast }: ProjectFilesViewProps) {
  const uploadInputRef = useRef<HTMLInputElement>(null);
  const versionInputRef = useRef<HTMLInputElement>(null);
  const deleteConfirmRef = useRef<HTMLButtonElement>(null);
  const trashButtonRef = useRef<HTMLButtonElement>(null);
  const [files, setFiles] = useState<ProjectFileSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectFileDetail | null>(null);
  const [query, setQuery] = useState("");
  const [pathDraft, setPathDraft] = useState("");
  const [versionReason, setVersionReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [dropActive, setDropActive] = useState(false);
  const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!projectId) {
      setFiles([]);
      setSelectedId(null);
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      api.projectFiles.list(projectId, query, false, controller.signal)
        .then((items) => {
          setFiles(items);
          setSelectedId((current) => current && items.some((item) => item.id === current) ? current : items[0]?.id ?? null);
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

  useEffect(() => {
    if (!projectId || !selectedId) {
      setDetail(null);
      return;
    }
    const controller = new AbortController();
    setDetailLoading(true);
    api.projectFiles.get(projectId, selectedId, controller.signal)
      .then((item) => {
        setDetail(item);
        setPathDraft(item.logicalPath);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [projectId, selectedId, refreshKey]);

  useEffect(() => {
    if (!deleteConfirmOpen) return;
    const frame = window.requestAnimationFrame(() => deleteConfirmRef.current?.focus());
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setDeleteConfirmOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", closeOnEscape);
      window.requestAnimationFrame(() => trashButtonRef.current?.focus());
    };
  }, [deleteConfirmOpen]);

  const uploadFiles = async (selectedFiles: File[]) => {
    if (!projectId || selectedFiles.length === 0 || busy) return;
    setBusy(true);
    setError(null);
    try {
      let lastId: string | undefined;
      for (const file of selectedFiles) {
        const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
        const created = await api.projectFiles.upload(projectId, file, relativePath || file.name, "Workspace 업로드");
        lastId = created.id;
      }
      setSelectedId(lastId ?? null);
      setRefreshKey((value) => value + 1);
      onToast(`${selectedFiles.length}개 파일을 Project Workspace에 업로드했습니다.`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const handleDrop = (event: DragEvent<HTMLButtonElement>) => {
    event.preventDefault();
    setDropActive(false);
    void uploadFiles(Array.from(event.dataTransfer.files));
  };

  const moveFile = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !detail || !pathDraft.trim() || pathDraft.trim() === detail.logicalPath) return;
    setBusy(true);
    try {
      const updated = await api.projectFiles.move(projectId, detail.id, pathDraft.trim(), detail.revision);
      setFiles((items) => items.map((item) => item.id === updated.id ? updated : item));
      setRefreshKey((value) => value + 1);
      onToast("파일의 논리 경로를 변경했습니다.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const addVersion = async (file: File) => {
    if (!projectId || !detail || busy) return;
    setBusy(true);
    try {
      await api.projectFiles.uploadVersion(projectId, detail.id, file, detail.currentVersion, versionReason);
      setVersionReason("");
      setRefreshKey((value) => value + 1);
      onToast(`새 파일 버전 v${detail.currentVersion + 1}을 저장했습니다.`);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const download = async (version?: number) => {
    if (!projectId || !detail) return;
    setBusy(true);
    try {
      saveDownload(await api.projectFiles.download(projectId, detail.id, version));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!projectId || !detail) return;
    setDeleteConfirmOpen(false);
    setBusy(true);
    try {
      await api.projectFiles.delete(projectId, detail.id, detail.revision);
      setDetail(null);
      setSelectedId(null);
      setRefreshKey((value) => value + 1);
      onToast("파일을 휴지통으로 이동했습니다.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="feature-view project-files-view">
      <header className="feature-header">
        <div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><FolderOpen size={17} /><h1>파일 Workspace</h1><span>{files.length}개 · Server Workspace</span></div>
        <div><button className="file-workspace-refresh" type="button" aria-label="새로 고침" disabled={loading} onClick={() => setRefreshKey((value) => value + 1)}>{loading ? <LoaderCircle className="is-running" size={15} /> : <RefreshCw size={15} />}</button></div>
      </header>
      <input ref={uploadInputRef} className="visually-hidden" type="file" multiple onChange={(event) => { const selected = Array.from(event.currentTarget.files ?? []); event.currentTarget.value = ""; void uploadFiles(selected); }} />
      <input ref={versionInputRef} className="visually-hidden" type="file" onChange={(event) => { const selected = event.currentTarget.files?.[0]; event.currentTarget.value = ""; if (selected) void addVersion(selected); }} />
      <div className="feature-toolbar file-workspace-toolbar">
        <button className={`file-drop-target ${dropActive ? "is-active" : ""}`} type="button" disabled={!projectId || busy} onClick={() => uploadInputRef.current?.click()} onDragEnter={(event) => { event.preventDefault(); setDropActive(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDropActive(false)} onDrop={handleDrop}><FilePlus2 size={14} /> 파일을 놓거나 선택해서 업로드</button>
        <label className="feature-search"><Search size={14} /><input value={query} placeholder="파일명 또는 논리 경로 검색" onChange={(event) => setQuery(event.currentTarget.value)} /></label>
      </div>
      {error && <div className="feature-error" role="alert">{error}</div>}
      {!projectId ? <div className="feature-state">파일을 관리할 Project를 선택해 주세요.</div> : (
        <div className="split-feature file-workspace-split">
          <aside className="feature-list file-workspace-list" aria-label="Project 파일 목록">
            {loading && files.length === 0 ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 불러오는 중</div> : files.length === 0 ? <div className="feature-state">Project 파일이 없습니다.</div> : files.map((item) => (
              <button className={item.id === selectedId ? "is-selected" : ""} type="button" key={item.id} onClick={() => setSelectedId(item.id)}>
                <span><strong>{item.displayName}</strong><small>{item.logicalPath} · {formatBytes(item.size)}</small></span><em className="is-enabled">v{item.currentVersion}</em>
              </button>
            ))}
          </aside>
          <section className="feature-detail file-workspace-detail" aria-live="polite">
            {detailLoading ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 파일 상세를 불러오는 중</div> : !detail ? <div className="feature-state">파일을 선택해 주세요.</div> : (
              <>
                <header className="detail-heading">
                  <div><h2>{detail.displayName}</h2><p>{detail.logicalPath}</p></div>
                  <div className="detail-badges"><span>{detail.mimeType}</span><span>v{detail.currentVersion}</span><span>{detail.extractionStatus}</span></div>
                </header>
                <div className="file-detail-facts"><span>크기 <strong>{formatBytes(detail.size)}</strong></span><span>수정 <strong>{formatDate(detail.updatedAt)}</strong></span><span>Hash <code>{detail.contentHash.slice(0, 12)}</code></span></div>
                <form className="file-path-form" onSubmit={(event) => void moveFile(event)}><label>논리 경로<input value={pathDraft} onChange={(event) => setPathDraft(event.currentTarget.value)} /></label><button type="submit" disabled={busy || !pathDraft.trim() || pathDraft.trim() === detail.logicalPath}><Move size={14} /> 이동·이름 변경</button></form>
                <div className="file-version-add"><label>새 버전 사유<input value={versionReason} placeholder="변경 내용을 선택적으로 기록" onChange={(event) => setVersionReason(event.currentTarget.value)} /></label><button type="button" disabled={busy} onClick={() => versionInputRef.current?.click()}><Upload size={14} /> v{detail.currentVersion + 1} 업로드</button></div>
                <div className="file-version-heading"><strong>버전 기록</strong><div><button type="button" disabled={busy} onClick={() => void download()}><Download size={14} /> 최신 다운로드</button><button ref={trashButtonRef} className="text-danger" type="button" disabled={busy} onClick={() => setDeleteConfirmOpen(true)}><Trash2 size={14} /> 휴지통</button></div></div>
                <div className="file-version-list">
                  {detail.versions.map((version) => (
                    <article key={version.id}><FileText size={15} /><span><strong>v{version.version}</strong><small>{version.originalFilename} · {formatBytes(version.size)}{version.changeReason ? ` · ${version.changeReason}` : ""}</small></span><time>{formatDate(version.createdAt)}</time><button className="tooltip-control" type="button" aria-label={`v${version.version} 다운로드`} data-tooltip="다운로드" disabled={busy} onClick={() => void download(version.version)}><Download size={14} /></button></article>
                  ))}
                </div>
              </>
            )}
          </section>
        </div>
      )}
      {deleteConfirmOpen && detail && (
        <div className="feature-inline-dialog" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setDeleteConfirmOpen(false); }}>
          <section className="compact-dialog file-delete-dialog" role="alertdialog" aria-modal="true" aria-labelledby="file-delete-title" aria-describedby="file-delete-description">
            <header><strong id="file-delete-title">파일을 휴지통으로 이동</strong></header>
            <p id="file-delete-description"><strong>{detail.logicalPath}</strong><br />버전 기록은 보존되며 기본 목록에서는 숨겨집니다.</p>
            <div className="dialog-actions"><button type="button" onClick={() => setDeleteConfirmOpen(false)}>취소</button><button ref={deleteConfirmRef} className="is-danger" type="button" disabled={busy} onClick={() => void remove()}>휴지통으로 이동</button></div>
          </section>
        </div>
      )}
    </div>
  );
}
