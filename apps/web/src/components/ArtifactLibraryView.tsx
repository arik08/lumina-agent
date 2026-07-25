import { AlertTriangle, FileCode2, FileText, LoaderCircle, Menu, RefreshCw, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ArtifactSummary } from "../api-types";
import { useCachedViewState } from "../view-data-cache";
import { SelectMenu, type SelectMenuOption } from "./SelectMenu";
import "./ArtifactLibraryView.css";

type ArtifactSortOrder = "latest" | "alphabetical";

const ALL_EXTENSIONS = "all";
const artifactNameCollator = new Intl.Collator("ko-KR", { numeric: true, sensitivity: "base" });
const artifactSortOptions: readonly SelectMenuOption[] = [
  { value: "latest", label: "최신순" },
  { value: "alphabetical", label: "알파벳순" },
];

function getArtifactExtension(displayName: string) {
  const match = /\.([^.\\/]+)$/.exec(displayName.trim());
  return match?.[1]?.toLocaleLowerCase("en-US") ?? "";
}

interface ArtifactLibraryViewProps {
  projectId: string | null;
  canDelete: boolean;
  onOpenArtifact: (artifact: ArtifactSummary) => void;
  onArtifactDeleted: (artifactId: string) => void;
  onOpenNavigation: () => void;
}

export function ArtifactLibraryView({ projectId, canDelete, onOpenArtifact, onArtifactDeleted, onOpenNavigation }: ArtifactLibraryViewProps) {
  const [items, setItems, hasCachedItems] = useCachedViewState<ArtifactSummary[]>(`library:${projectId ?? "all"}`, []);
  const [query, setQuery] = useState("");
  const [extension, setExtension] = useState(ALL_EXTENSIONS);
  const [sortOrder, setSortOrder] = useState<ArtifactSortOrder>("latest");
  const [loading, setLoading] = useState(!hasCachedItems);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [deleteArmedId, setDeleteArmedId] = useState<string | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<{ id: string; message: string } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api.artifacts.list(projectId ?? undefined, controller.signal)
      .then((page) => setItems(page.items))
      .catch((caught) => {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Artifact를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, refreshKey]);

  const extensionOptions = useMemo<readonly SelectMenuOption[]>(() => {
    const extensions = Array.from(new Set(items.map((item) => getArtifactExtension(item.displayName)).filter(Boolean)))
      .sort(artifactNameCollator.compare);
    return [
      { value: ALL_EXTENSIONS, label: "전체" },
      ...extensions.map((value) => ({ value, label: value.toLocaleUpperCase("en-US") })),
    ];
  }, [items]);

  useEffect(() => {
    if (extension !== ALL_EXTENSIONS && !extensionOptions.some((option) => option.value === extension)) {
      setExtension(ALL_EXTENSIONS);
    }
  }, [extension, extensionOptions]);

  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ko-KR");
    return [...items]
      .filter((item) => extension === ALL_EXTENSIONS || getArtifactExtension(item.displayName) === extension)
      .filter((item) => !normalized || `${item.displayName} ${item.kind}`.toLocaleLowerCase("ko-KR").includes(normalized))
      .sort((left, right) => {
        if (sortOrder === "alphabetical") {
          return artifactNameCollator.compare(left.displayName, right.displayName)
            || Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
        }
        return Date.parse(right.updatedAt) - Date.parse(left.updatedAt)
          || artifactNameCollator.compare(left.displayName, right.displayName);
      });
  }, [extension, items, query, sortOrder]);

  async function removeArtifact(artifact: ArtifactSummary) {
    if (deleteArmedId !== artifact.id) {
      setDeleteArmedId(artifact.id);
      setDeleteError(null);
      return;
    }
    setDeleteBusyId(artifact.id);
    setDeleteError(null);
    try {
      await api.artifacts.delete(artifact.id);
      setItems((current) => current.filter((item) => item.id !== artifact.id));
      setDeleteArmedId(null);
      onArtifactDeleted(artifact.id);
    } catch (caught) {
      setDeleteError({
        id: artifact.id,
        message: caught instanceof Error ? caught.message : "Artifact를 삭제하지 못했습니다.",
      });
    } finally {
      setDeleteBusyId(null);
    }
  }

  return (
    <div className="feature-view">
      <header className="feature-header"><div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><FileText size={17} /><h1>Artifact Library</h1><span>{items.length}개 · 생성된 결과물 검색·미리보기</span></div><button type="button" aria-label="새로 고침" onClick={() => setRefreshKey((value) => value + 1)}><RefreshCw size={15} /></button></header>
      {error && <div className="feature-error" role="alert">{error}</div>}
      <div className="feature-toolbar artifact-library-toolbar">
        <label className="feature-search"><Search size={15} /><input placeholder="Artifact 검색" value={query} onChange={(event) => setQuery(event.currentTarget.value)} /></label>
        <div className="artifact-library-controls">
          <SelectMenu
            value={extension}
            options={extensionOptions}
            ariaLabel="파일 확장자 필터"
            onChange={setExtension}
            size="small"
            width="auto"
            align="end"
            className="artifact-extension-select"
          />
          <SelectMenu
            value={sortOrder}
            options={artifactSortOptions}
            ariaLabel="Artifact 정렬 순서"
            onChange={(value) => setSortOrder(value as ArtifactSortOrder)}
            size="small"
            width="auto"
            align="end"
            className="artifact-sort-select"
          />
        </div>
      </div>
      <div className="feature-scroll artifact-library-scroll">
        {loading && !hasCachedItems ? <div className="feature-state"><LoaderCircle className="is-running" size={17} /> Artifact를 불러오고 있습니다.</div> : filtered.length === 0 ? <div className="feature-state">표시할 Artifact가 없습니다.</div> : (
          <div className="artifact-library-list">
            {filtered.map((artifact) => (
              <div className="artifact-library-row" key={artifact.id}>
                <button type="button" className="artifact-library-open" onClick={() => { setDeleteArmedId(null); setDeleteError(null); onOpenArtifact(artifact); }}>
                  <span className="feature-row-icon">{artifact.kind === "html" || artifact.kind === "code" ? <FileCode2 size={17} /> : <FileText size={17} />}</span>
                  <span className="feature-row-copy"><strong>{artifact.displayName}</strong><small>{artifact.kind.toUpperCase()} · v{artifact.currentVersion} · {(artifact.size / 1024).toFixed(1)}KB</small></span>
                  <time>{new Date(artifact.updatedAt).toLocaleDateString("ko-KR")}</time>
                </button>
                {canDelete && <button className={`artifact-library-delete tooltip-control ${deleteArmedId === artifact.id ? "is-delete-armed" : ""}`} type="button" aria-label={deleteArmedId === artifact.id ? `${artifact.displayName} 삭제 확인, 한 번 더 누르면 삭제` : `${artifact.displayName} 삭제`} data-tooltip={deleteArmedId === artifact.id ? "한 번 더 눌러 삭제" : "삭제"} disabled={deleteBusyId !== null} onClick={() => void removeArtifact(artifact)}>{deleteBusyId === artifact.id ? <LoaderCircle className="is-running" size={14} /> : deleteArmedId === artifact.id ? <AlertTriangle size={14} /> : <Trash2 size={14} />}</button>}
                {deleteError?.id === artifact.id && <small className="artifact-library-delete-error" role="alert">{deleteError.message}</small>}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
