import {
  AlertCircle,
  Check,
  ChevronDown,
  ChevronRight,
  FilePlus2,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  Info,
  LoaderCircle,
  Menu,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "../api";
import type { HelpItem, HelpItemKind } from "../api-types";
import { ResizableSplitPane } from "./ResizableSplitPane";


interface HelpCenterViewProps {
  canManage: boolean;
  onOpenNavigation: () => void;
  onToast: (message: string) => void;
}

interface HelpTreeNode {
  item: HelpItem;
  children: HelpTreeNode[];
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

function buildTree(items: HelpItem[]) {
  const nodes = new Map<string, HelpTreeNode>(items.map((item) => [item.id, { item, children: [] }]));
  const roots: HelpTreeNode[] = [];
  for (const item of items) {
    const node = nodes.get(item.id)!;
    const parent = item.parentId ? nodes.get(item.parentId) : undefined;
    if (parent?.item.kind === "folder") parent.children.push(node);
    else roots.push(node);
  }
  const sort = (nodesToSort: HelpTreeNode[]) => {
    nodesToSort.sort((left, right) => {
      if (left.item.sortOrder !== right.item.sortOrder) return left.item.sortOrder - right.item.sortOrder;
      if (left.item.kind !== right.item.kind) return left.item.kind === "folder" ? -1 : 1;
      return left.item.title.localeCompare(right.item.title, "ko-KR");
    });
    nodesToSort.forEach((node) => sort(node.children));
  };
  sort(roots);
  return roots;
}

function filterTree(nodes: HelpTreeNode[], query: string): HelpTreeNode[] {
  const normalized = query.trim().toLocaleLowerCase("ko-KR");
  if (!normalized) return nodes;
  return nodes.flatMap((node) => {
    const children = filterTree(node.children, normalized);
    const matches = node.item.title.toLocaleLowerCase("ko-KR").includes(normalized)
      || (node.item.kind === "document" && node.item.markdownContent.toLocaleLowerCase("ko-KR").includes(normalized));
    return matches || children.length > 0 ? [{ ...node, children }] : [];
  });
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function HelpCenterView({ canManage, onOpenNavigation, onToast }: HelpCenterViewProps) {
  const [items, setItems] = useState<HelpItem[]>([]);
  const [serverCanManage, setServerCanManage] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState<HelpItemKind | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [editing, setEditing] = useState(false);
  const [draftTitle, setDraftTitle] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const [deleteArmed, setDeleteArmed] = useState(false);

  const effectiveCanManage = canManage && serverCanManage;
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const selectedParent = selected?.kind === "folder" ? selected : items.find((item) => item.id === selected?.parentId) ?? null;
  const createParentId = selectedParent?.kind === "folder" ? selectedParent.id : null;
  const documentCount = items.filter((item) => item.kind === "document").length;

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.help.list(signal);
      setItems(response.items);
      setServerCanManage(response.canManage);
      setExpanded((current) => current.size > 0 ? current : new Set(response.items.filter((item) => item.kind === "folder").map((item) => item.id)));
      setSelectedId((current) => response.items.some((item) => item.id === current)
        ? current
        : response.items.find((item) => item.kind === "document")?.id ?? response.items[0]?.id ?? null);
    } catch (loadError) {
      if ((loadError as { name?: string }).name !== "AbortError") setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const tree = useMemo(() => filterTree(buildTree(items), query), [items, query]);

  const beginCreate = (kind: HelpItemKind) => {
    setCreating(kind);
    setNewTitle("");
    setError(null);
    if (createParentId) setExpanded((current) => new Set(current).add(createParentId));
  };

  const createItem = async () => {
    if (!creating || !newTitle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.help.create({
        kind: creating,
        title: newTitle.trim(),
        parentId: createParentId,
        markdownContent: "",
      });
      setItems((current) => [...current, created]);
      setSelectedId(created.id);
      setCreating(null);
      setNewTitle("");
      if (created.parentId) setExpanded((current) => new Set(current).add(created.parentId!));
      if (created.kind === "document") {
        setDraftTitle(created.title);
        setDraftContent("");
        setEditing(true);
      }
      onToast(created.kind === "folder" ? "안내 폴더를 만들었습니다." : "안내 문서를 만들었습니다.");
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setBusy(false);
    }
  };

  const beginEdit = () => {
    if (!selected) return;
    setDraftTitle(selected.title);
    setDraftContent(selected.markdownContent);
    setDeleteArmed(false);
    setEditing(true);
  };

  const save = async () => {
    if (!selected || !draftTitle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await api.help.update(selected.id, {
        title: draftTitle.trim(),
        markdownContent: selected.kind === "document" ? draftContent : "",
        expectedRevision: selected.revision,
      });
      setItems((current) => current.map((item) => item.id === updated.id ? updated : item));
      setEditing(false);
      onToast("사용 안내를 저장했습니다.");
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!selected) return;
    if (!deleteArmed) {
      setDeleteArmed(true);
      return;
    }
    const parentId = selected.parentId;
    setBusy(true);
    setError(null);
    try {
      await api.help.delete(selected.id);
      setSelectedId(parentId);
      setDeleteArmed(false);
      await load();
      onToast(selected.kind === "folder" ? "안내 폴더와 하위 항목을 삭제했습니다." : "안내 문서를 삭제했습니다.");
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    } finally {
      setBusy(false);
    }
  };

  const renderTree = (nodes: HelpTreeNode[], depth = 0): React.ReactNode => nodes.map((node) => {
    const isFolder = node.item.kind === "folder";
    const isExpanded = query.trim() ? true : expanded.has(node.item.id);
    return (
      <div key={node.item.id}>
        <button
          className={`file-tree-row help-tree-row ${isFolder ? "is-folder" : ""} ${selectedId === node.item.id ? "is-selected" : ""}`}
          style={{ "--tree-depth": depth } as CSSProperties}
          type="button"
          onClick={() => {
            setSelectedId(node.item.id);
            setCreating(null);
            setEditing(false);
            setDeleteArmed(false);
            if (isFolder) setExpanded((current) => {
              const next = new Set(current);
              if (next.has(node.item.id)) next.delete(node.item.id);
              else next.add(node.item.id);
              return next;
            });
          }}
        >
          <span className="file-tree-chevron" aria-hidden="true">{isFolder ? (isExpanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />) : null}</span>
          {isFolder ? <Folder size={14} /> : <FileText size={14} />}
          <span>{node.item.title}</span>
        </button>
        {isFolder && isExpanded ? renderTree(node.children, depth + 1) : null}
      </div>
    );
  });

  return (
    <main className="feature-view help-center-view" aria-label="사용 안내">
      <header className="feature-header">
        <div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><Info size={17} /><h1>사용 안내</h1><span>{documentCount}개 문서 · 모든 사용자 열람{effectiveCanManage ? " · 관리자 편집" : ""}</span></div>
        <div><button className="file-workspace-refresh tooltip-control" type="button" aria-label="사용 안내 새로 고침" data-tooltip="새로 고침" disabled={loading} onClick={() => void load()}>{loading ? <LoaderCircle className="is-running" size={15} /> : <RefreshCw size={15} />}</button></div>
      </header>
      <div className="feature-toolbar help-center-toolbar">
        <label className="feature-search"><Search size={14} /><input value={query} placeholder="안내 제목이나 내용 검색" onChange={(event) => setQuery(event.currentTarget.value)} /></label>
        {effectiveCanManage ? <div className="help-create-actions"><button type="button" disabled={busy} onClick={() => beginCreate("folder")}><FolderPlus size={14} />폴더</button><button type="button" disabled={busy} onClick={() => beginCreate("document")}><FilePlus2 size={14} />문서</button></div> : null}
      </div>
      {error ? <div className="feature-error" role="alert">{error}</div> : null}
      <ResizableSplitPane storageKey="lumina:help-explorer-width" ariaLabel="사용 안내 탐색기 너비 조절" className="file-workspace-split help-center-split">
        <aside className="file-workspace-explorer" aria-label="사용 안내 탐색기">
          <div className="file-explorer-heading"><FolderOpen size={14} /><strong>안내 목차</strong>{effectiveCanManage ? <small>관리자 편집</small> : null}</div>
          {creating ? (
            <form className="help-create-form" onSubmit={(event) => { event.preventDefault(); void createItem(); }}>
              <span>{creating === "folder" ? <FolderPlus size={14} /> : <FilePlus2 size={14} />}{createParentId ? `${selectedParent?.title} 안에` : "최상위에"} {creating === "folder" ? "폴더" : "문서"} 추가</span>
              <div><input autoFocus value={newTitle} maxLength={160} placeholder={creating === "folder" ? "폴더 이름" : "문서 제목"} onChange={(event) => setNewTitle(event.currentTarget.value)} /><button type="submit" aria-label="추가" disabled={busy || !newTitle.trim()}><Check size={14} /></button><button type="button" aria-label="취소" onClick={() => setCreating(null)}><X size={14} /></button></div>
            </form>
          ) : null}
          <div className="file-tree thin-scrollbar">
            {loading && items.length === 0 ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 불러오는 중</div> : tree.length === 0 ? <div className="file-tree-empty"><Info size={22} /><strong>{query ? "검색 결과가 없습니다." : "아직 안내 문서가 없습니다."}</strong><span>{effectiveCanManage ? "위의 폴더 또는 문서 버튼으로 시작해 주세요." : "관리자가 안내를 준비하면 여기에 표시됩니다."}</span></div> : renderTree(tree)}
          </div>
        </aside>
        <section className="feature-detail file-workspace-viewer help-center-viewer" aria-live="polite">
          {!selected ? (
            <div className="file-viewer-empty"><Info size={28} /><strong>읽을 안내 문서를 선택해 주세요.</strong><span>왼쪽 목차에서 Lumina 사용법과 팁을 찾아볼 수 있습니다.</span></div>
          ) : (
            <div className="file-viewer-document">
              <header className="file-viewer-heading help-viewer-heading">
                <span className="file-viewer-icon">{selected.kind === "folder" ? <FolderOpen size={22} /> : <FileText size={22} />}</span>
                <div>{editing ? <input className="help-title-input" value={draftTitle} maxLength={160} aria-label="안내 제목" onChange={(event) => setDraftTitle(event.currentTarget.value)} /> : <><h2>{selected.title}</h2><p>{selected.kind === "folder" ? "안내 폴더" : `마지막 수정 ${formatDate(selected.updatedAt)}`}</p></>}</div>
                {effectiveCanManage ? <div className="file-viewer-actions">
                  {editing ? <><button type="button" disabled={busy || !draftTitle.trim()} onClick={() => void save()}>{busy ? <LoaderCircle className="is-running" size={14} /> : <Check size={14} />}저장</button><button type="button" disabled={busy} onClick={() => setEditing(false)}><X size={14} />취소</button></> : <button type="button" disabled={busy} onClick={beginEdit}><Pencil size={14} />편집</button>}
                  {!editing ? <button className={`is-danger ${deleteArmed ? "is-confirming" : ""}`} type="button" disabled={busy} onClick={() => void remove()}>{deleteArmed ? <AlertCircle size={14} /> : <Trash2 size={14} />}{deleteArmed ? "한 번 더 눌러 삭제" : "삭제"}</button> : null}
                </div> : null}
              </header>
              {selected.kind === "folder" ? (
                <div className="help-folder-summary"><FolderOpen size={30} /><strong>{items.filter((item) => item.parentId === selected.id).length}개 하위 항목</strong><span>이 폴더를 선택한 상태에서 새 폴더나 문서를 만들면 안에 추가됩니다.</span></div>
              ) : editing ? (
                <div className="help-markdown-editor"><div><strong>Markdown</strong><span>제목, 목록, 표, 링크와 코드 블록을 사용할 수 있습니다.</span></div><textarea className="thin-scrollbar" value={draftContent} spellCheck={false} aria-label="안내 Markdown 편집" placeholder="# 시작하기\n\n사용 방법과 팁을 Markdown으로 작성해 주세요." onChange={(event) => setDraftContent(event.currentTarget.value)} /></div>
              ) : (
                <article className="help-markdown thin-scrollbar">
                  {selected.markdownContent.trim() ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}>{selected.markdownContent}</ReactMarkdown> : <div className="file-viewer-empty"><FileText size={28} /><strong>아직 내용이 없습니다.</strong><span>{effectiveCanManage ? "편집을 눌러 Markdown 안내를 작성해 주세요." : "관리자가 내용을 준비하고 있습니다."}</span></div>}
                </article>
              )}
            </div>
          )}
        </section>
      </ResizableSplitPane>
    </main>
  );
}
