import { CheckCircle2, FileCode2, FileText, LoaderCircle, Menu, RefreshCw, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { ArtifactSummary } from "../api-types";

interface ArtifactLibraryViewProps {
  projectId: string | null;
  onOpenArtifact: (artifact: ArtifactSummary) => void;
  onOpenNavigation: () => void;
}

export function ArtifactLibraryView({ projectId, onOpenArtifact, onOpenNavigation }: ArtifactLibraryViewProps) {
  const [items, setItems] = useState<ArtifactSummary[]>([]);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

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

  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return items;
    return items.filter((item) => `${item.displayName} ${item.kind}`.toLocaleLowerCase("ko-KR").includes(normalized));
  }, [items, query]);

  return (
    <div className="feature-view">
      <header className="feature-header"><div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><FileText size={17} /><h1>Artifact Library</h1><span>{items.length}개</span></div><button type="button" aria-label="새로 고침" onClick={() => setRefreshKey((value) => value + 1)}><RefreshCw size={15} /></button></header>
      {error && <div className="feature-error" role="alert">{error}</div>}
      <div className="feature-toolbar"><label className="feature-search"><Search size={15} /><input placeholder="Artifact 검색" value={query} onChange={(event) => setQuery(event.currentTarget.value)} /></label></div>
      <div className="feature-scroll">
        {loading ? <div className="feature-state"><LoaderCircle className="is-running" size={17} /> Artifact를 불러오고 있습니다.</div> : filtered.length === 0 ? <div className="feature-state">표시할 Artifact가 없습니다.</div> : (
          <div className="artifact-library-list">
            {filtered.map((artifact) => (
              <button type="button" className="artifact-library-row" key={artifact.id} onClick={() => onOpenArtifact(artifact)}>
                <span className="feature-row-icon">{artifact.kind === "html" || artifact.kind === "code" ? <FileCode2 size={17} /> : <FileText size={17} />}</span>
                <span className="feature-row-copy"><strong>{artifact.displayName}</strong><small>{artifact.kind.toUpperCase()} · v{artifact.currentVersion} · {(artifact.size / 1024).toFixed(1)}KB</small></span>
                <span className={`validation-mark status-${artifact.validationStatus}`}><CheckCircle2 size={13} /> {artifact.validationStatus}</span>
                <time>{new Date(artifact.updatedAt).toLocaleDateString("ko-KR")}</time>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
