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
  Megaphone,
  Menu,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { api } from "../api";
import type { AnnouncementItem, HelpItem, HelpItemKind } from "../api-types";
import { MarkdownResponse } from "./ConversationTurn";
import { ResizableSplitPane } from "./ResizableSplitPane";

type HelpSection = "manuals" | "announcements";
const helpTreeDragMime = "application/x-lumina-help-tree";

interface HelpCenterViewProps {
  canManage: boolean;
  initialAnnouncementId?: string | null;
  onOpenNavigation: () => void;
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

function announcementWasEdited(announcement: AnnouncementItem) {
  return new Date(announcement.updatedAt).getTime() - new Date(announcement.createdAt).getTime() >= 1000;
}

function isHelpItemSelfOrDescendant(items: HelpItem[], itemId: string, candidateParentId: string) {
  let current = items.find((item) => item.id === candidateParentId) ?? null;
  while (current) {
    if (current.id === itemId) return true;
    current = current.parentId ? items.find((item) => item.id === current?.parentId) ?? null : null;
  }
  return false;
}

export function HelpCenterView({ canManage, initialAnnouncementId = null, onOpenNavigation }: HelpCenterViewProps) {
  const draggedHelpItemRef = useRef<HelpItem | null>(null);
  const [section, setSection] = useState<HelpSection>(initialAnnouncementId ? "announcements" : "manuals");
  const [items, setItems] = useState<HelpItem[]>([]);
  const [announcements, setAnnouncements] = useState<AnnouncementItem[]>([]);
  const [announcementTotal, setAnnouncementTotal] = useState(0);
  const [serverCanManage, setServerCanManage] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedAnnouncementId, setSelectedAnnouncementId] = useState<string | null>(initialAnnouncementId);
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
  const [announcementMode, setAnnouncementMode] = useState<"idle" | "create" | "edit">("idle");
  const [announcementTitle, setAnnouncementTitle] = useState("");
  const [announcementBody, setAnnouncementBody] = useState("");
  const [announcementDeleteArmed, setAnnouncementDeleteArmed] = useState(false);
  const [helpTreeDropParentId, setHelpTreeDropParentId] = useState<string | null | undefined>(undefined);

  const effectiveCanManage = canManage && serverCanManage;
  const selected = items.find((item) => item.id === selectedId) ?? null;
  const selectedAnnouncement = announcements.find((item) => item.id === selectedAnnouncementId) ?? null;
  const selectedParent = selected?.kind === "folder" ? selected : items.find((item) => item.id === selected?.parentId) ?? null;
  const createParentId = selectedParent?.kind === "folder" ? selectedParent.id : null;
  const documentCount = items.filter((item) => item.kind === "document").length;

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const [helpResponse, announcementResponse] = await Promise.all([
        api.help.list(signal),
        api.notifications.listAnnouncements(100, 0, signal),
      ]);
      setItems(helpResponse.items);
      setAnnouncements(announcementResponse.items);
      setAnnouncementTotal(announcementResponse.total);
      setServerCanManage(helpResponse.canManage);
      setExpanded((current) => current.size > 0 ? current : new Set(helpResponse.items.filter((item) => item.kind === "folder").map((item) => item.id)));
      setSelectedId((current) => helpResponse.items.some((item) => item.id === current)
        ? current
        : helpResponse.items.find((item) => item.kind === "document")?.id ?? helpResponse.items[0]?.id ?? null);
      setSelectedAnnouncementId((current) => announcementResponse.items.some((item) => item.id === current)
        ? current
        : announcementResponse.items[0]?.id ?? null);
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

  useEffect(() => {
    if (!initialAnnouncementId) return;
    setSection("announcements");
    setSelectedAnnouncementId(initialAnnouncementId);
    setAnnouncementMode("idle");
  }, [initialAnnouncementId]);

  const tree = useMemo(() => filterTree(buildTree(items), query), [items, query]);
  const filteredAnnouncements = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("ko-KR");
    if (!normalized) return announcements;
    return announcements.filter((announcement) => announcement.title.toLocaleLowerCase("ko-KR").includes(normalized)
      || announcement.body.toLocaleLowerCase("ko-KR").includes(normalized));
  }, [announcements, query]);

  const switchSection = (next: HelpSection) => {
    setSection(next);
    setQuery("");
    setCreating(null);
    setEditing(false);
    setDeleteArmed(false);
    setAnnouncementMode("idle");
    setAnnouncementDeleteArmed(false);
    setError(null);
  };

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
      const created = await api.help.create({ kind: creating, title: newTitle.trim(), parentId: createParentId, markdownContent: "" });
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
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    } finally {
      setBusy(false);
    }
  };

  const moveHelpItem = async (item: HelpItem, parentId: string | null) => {
    if (busy || item.parentId === parentId) {
      draggedHelpItemRef.current = null;
      setHelpTreeDropParentId(undefined);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.help.update(item.id, {
        title: item.title,
        markdownContent: item.markdownContent,
        parentId,
        expectedRevision: item.revision,
      });
      setItems((current) => current.map((candidate) => candidate.id === updated.id ? updated : candidate));
      setSelectedId(updated.id);
      if (parentId) setExpanded((current) => new Set(current).add(parentId));
    } catch (moveError) {
      setError(errorMessage(moveError));
    } finally {
      setBusy(false);
      draggedHelpItemRef.current = null;
      setHelpTreeDropParentId(undefined);
    }
  };

  const beginAnnouncementCreate = () => {
    setSelectedAnnouncementId(null);
    setAnnouncementTitle("");
    setAnnouncementBody("");
    setAnnouncementDeleteArmed(false);
    setAnnouncementMode("create");
  };

  const beginAnnouncementEdit = () => {
    if (!selectedAnnouncement) return;
    setAnnouncementTitle(selectedAnnouncement.title);
    setAnnouncementBody(selectedAnnouncement.body);
    setAnnouncementDeleteArmed(false);
    setAnnouncementMode("edit");
  };

  const saveAnnouncement = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!announcementTitle.trim() || !announcementBody.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const saved = announcementMode === "create"
        ? await api.admin.createAnnouncement({ title: announcementTitle.trim(), body: announcementBody.trim() })
        : selectedAnnouncement
          ? await api.admin.updateAnnouncement(selectedAnnouncement.id, { title: announcementTitle.trim(), body: announcementBody.trim() })
          : null;
      if (!saved) return;
      setAnnouncements((current) => announcementMode === "create"
        ? [saved, ...current]
        : current.map((item) => item.id === saved.id ? saved : item));
      if (announcementMode === "create") setAnnouncementTotal((current) => current + 1);
      setSelectedAnnouncementId(saved.id);
      setAnnouncementMode("idle");
    } catch (saveError) {
      setError(errorMessage(saveError));
    } finally {
      setBusy(false);
    }
  };

  const removeAnnouncement = async () => {
    if (!selectedAnnouncement) return;
    if (!announcementDeleteArmed) {
      setAnnouncementDeleteArmed(true);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.admin.deleteAnnouncement(selectedAnnouncement.id);
      const remaining = announcements.filter((item) => item.id !== selectedAnnouncement.id);
      setAnnouncements(remaining);
      setAnnouncementTotal((current) => Math.max(0, current - 1));
      setSelectedAnnouncementId(remaining[0]?.id ?? null);
      setAnnouncementDeleteArmed(false);
    } catch (deleteError) {
      setError(errorMessage(deleteError));
    } finally {
      setBusy(false);
    }
  };

  const renderTree = (nodes: HelpTreeNode[], depth = 0): React.ReactNode => nodes.map((node) => {
    const isFolder = node.item.kind === "folder";
    const isExpanded = query.trim() ? true : expanded.has(node.item.id);
    const isDropTarget = isFolder && helpTreeDropParentId === node.item.id;
    return (
      <div key={node.item.id}>
        <button
          className={`file-tree-row help-tree-row ${isFolder ? "is-folder" : ""} ${selectedId === node.item.id ? "is-selected" : ""} ${isDropTarget ? "is-drop-target" : ""}`}
          style={{ "--tree-depth": depth } as CSSProperties}
          type="button"
          draggable={effectiveCanManage && !busy}
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
          onDragStart={(event) => {
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData(helpTreeDragMime, node.item.id);
            draggedHelpItemRef.current = node.item;
          }}
          onDragEnd={() => {
            draggedHelpItemRef.current = null;
            setHelpTreeDropParentId(undefined);
          }}
          onDragOver={isFolder ? (event) => {
            const source = draggedHelpItemRef.current;
            if (!source && !Array.from(event.dataTransfer.types).includes(helpTreeDragMime)) return;
            if (source && isHelpItemSelfOrDescendant(items, source.id, node.item.id)) {
              event.stopPropagation();
              event.dataTransfer.dropEffect = "none";
              setHelpTreeDropParentId(undefined);
              return;
            }
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = "move";
            setHelpTreeDropParentId(node.item.id);
          } : undefined}
          onDrop={isFolder ? (event) => {
            const source = draggedHelpItemRef.current ?? items.find((item) => item.id === event.dataTransfer.getData(helpTreeDragMime));
            if (!source || isHelpItemSelfOrDescendant(items, source.id, node.item.id)) return;
            event.preventDefault();
            event.stopPropagation();
            void moveHelpItem(source, node.item.id);
          } : undefined}
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
        <div><button className="feature-mobile-menu" type="button" aria-label="사이드바 열기" onClick={onOpenNavigation}><Menu size={17} /></button><Info size={17} /><h1>사용 안내</h1><span>{documentCount}개 매뉴얼 · 공지 {announcementTotal}건 · 모든 사용자 열람{effectiveCanManage ? " · 관리자 편집" : ""}</span></div>
        <div><button className="file-workspace-refresh tooltip-control" type="button" aria-label="사용 안내 새로 고침" data-tooltip="새로 고침" disabled={loading} onClick={() => void load()}>{loading ? <LoaderCircle className="is-running" size={15} /> : <RefreshCw size={15} />}</button></div>
      </header>
      <div className="help-section-tabs" role="tablist" aria-label="사용 안내 자료 유형">
        <button type="button" role="tab" aria-selected={section === "announcements"} onClick={() => switchSection("announcements")}><Megaphone size={14} />공지사항 <span>{announcementTotal}</span></button>
        <button type="button" role="tab" aria-selected={section === "manuals"} onClick={() => switchSection("manuals")}><FileText size={14} />매뉴얼 <span>{documentCount}</span></button>
      </div>
      {section === "manuals" ? <div className="feature-toolbar help-center-toolbar">
        <label className="feature-search"><Search size={14} /><input value={query} placeholder="매뉴얼 제목이나 내용 검색" onChange={(event) => setQuery(event.currentTarget.value)} /></label>
        {effectiveCanManage ? <div className="help-create-actions"><button type="button" disabled={busy} onClick={() => beginCreate("folder")}><FolderPlus size={14} />폴더</button><button type="button" disabled={busy} onClick={() => beginCreate("document")}><FilePlus2 size={14} />문서</button></div> : null}
      </div> : null}
      {error ? <div className="feature-error" role="alert">{error}</div> : null}
      <ResizableSplitPane storageKey="lumina:help-explorer-width" ariaLabel="사용 안내 탐색기 너비 조절" className="file-workspace-split help-center-split">
        <aside
          className={`file-workspace-explorer ${section === "manuals" && helpTreeDropParentId === null ? "is-root-drop-target" : ""}`}
          aria-label={section === "manuals" ? "매뉴얼 탐색기" : "공지사항 목록"}
          onDragOver={(event) => {
            if (section !== "manuals" || !effectiveCanManage) return;
            if (!draggedHelpItemRef.current && !Array.from(event.dataTransfer.types).includes(helpTreeDragMime)) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            setHelpTreeDropParentId(null);
          }}
          onDrop={(event) => {
            if (section !== "manuals" || !effectiveCanManage) return;
            const source = draggedHelpItemRef.current ?? items.find((item) => item.id === event.dataTransfer.getData(helpTreeDragMime));
            if (!source) return;
            event.preventDefault();
            void moveHelpItem(source, null);
          }}
        >
          {section === "announcements" ? <div className="help-announcement-explorer-controls">
            {effectiveCanManage ? <div className="help-create-actions"><button className="lumina-primary-action" type="button" disabled={busy} onClick={beginAnnouncementCreate}><Plus size={14} />공지 작성</button></div> : null}
            <label className="feature-search"><Search size={14} /><input value={query} placeholder="공지 제목이나 내용 검색" onChange={(event) => setQuery(event.currentTarget.value)} /></label>
          </div> : null}
          <div className="file-explorer-heading">{section === "manuals" ? <FolderOpen size={14} /> : <Megaphone size={14} />}<strong>{section === "manuals" ? "매뉴얼 목차" : "공지사항"}</strong>{effectiveCanManage ? <small>관리자 편집</small> : null}</div>
          {section === "manuals" && creating ? (
            <form className="help-create-form" onSubmit={(event) => { event.preventDefault(); void createItem(); }}>
              <span>{creating === "folder" ? <FolderPlus size={14} /> : <FilePlus2 size={14} />}{createParentId ? `${selectedParent?.title} 안에` : "최상위에"} {creating === "folder" ? "폴더" : "문서"} 추가</span>
              <div><input autoFocus value={newTitle} maxLength={160} placeholder={creating === "folder" ? "폴더 이름" : "문서 제목"} onChange={(event) => setNewTitle(event.currentTarget.value)} /><button type="submit" aria-label="추가" disabled={busy || !newTitle.trim()}><Check size={14} /></button><button type="button" aria-label="취소" onClick={() => setCreating(null)}><X size={14} /></button></div>
            </form>
          ) : null}
          <div className="file-tree thin-scrollbar">
            {loading && items.length === 0 && announcements.length === 0 ? <div className="feature-state"><LoaderCircle className="is-running" size={15} /> 불러오는 중</div> : section === "manuals" ? (
              tree.length === 0 ? <div className="file-tree-empty"><Info size={22} /><strong>{query ? "검색 결과가 없습니다." : "아직 매뉴얼이 없습니다."}</strong><span>{effectiveCanManage ? "위의 폴더 또는 문서 버튼으로 시작해 주세요." : "관리자가 매뉴얼을 준비하면 여기에 표시됩니다."}</span></div> : renderTree(tree)
            ) : filteredAnnouncements.length === 0 ? (
              <div className="file-tree-empty"><Megaphone size={22} /><strong>{query ? "검색 결과가 없습니다." : "게시된 공지사항이 없습니다."}</strong><span>{effectiveCanManage ? "공지 작성 버튼으로 새 소식을 게시해 주세요." : "새 공지가 게시되면 여기에 표시됩니다."}</span></div>
            ) : filteredAnnouncements.map((announcement) => (
              <button className={`help-announcement-row ${selectedAnnouncementId === announcement.id && announcementMode === "idle" ? "is-selected" : ""}`} type="button" key={announcement.id} onClick={() => { setSelectedAnnouncementId(announcement.id); setAnnouncementMode("idle"); setAnnouncementDeleteArmed(false); }}>
                <Megaphone size={14} aria-hidden="true" /><span><strong>{announcement.title}</strong><small>{formatDate(announcement.createdAt)}</small></span>
              </button>
            ))}
          </div>
        </aside>
        <section className="feature-detail file-workspace-viewer help-center-viewer" aria-live="polite">
          {section === "manuals" ? (!selected ? (
            <div className="file-viewer-empty"><Info size={28} /><strong>읽을 매뉴얼을 선택해 주세요.</strong><span>왼쪽 목차에서 Lumina 사용법과 팁을 찾아볼 수 있습니다.</span></div>
          ) : (
            <div className="file-viewer-document">
              <header className="file-viewer-heading help-viewer-heading">
                <span className="file-viewer-icon">{selected.kind === "folder" ? <FolderOpen size={22} /> : <FileText size={22} />}</span>
                <div>{editing ? <input className="help-title-input" value={draftTitle} maxLength={160} aria-label="안내 제목" onChange={(event) => setDraftTitle(event.currentTarget.value)} /> : <><h2>{selected.title}</h2><p>{selected.kind === "folder" ? "매뉴얼 폴더" : `마지막 수정 ${formatDate(selected.updatedAt)}`}</p></>}</div>
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
                  {selected.markdownContent.trim() ? <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: (props) => <a {...props} target="_blank" rel="noreferrer" /> }}>{selected.markdownContent}</ReactMarkdown> : <div className="file-viewer-empty"><FileText size={28} /><strong>아직 내용이 없습니다.</strong><span>{effectiveCanManage ? "편집을 눌러 Markdown 매뉴얼을 작성해 주세요." : "관리자가 내용을 준비하고 있습니다."}</span></div>}
                </article>
              )}
            </div>
          )) : announcementMode !== "idle" ? (
            <form className="help-announcement-form" onSubmit={(event) => void saveAnnouncement(event)}>
              <header><span className="file-viewer-icon"><Megaphone size={22} /></span><div><h2>{announcementMode === "create" ? "새 공지 작성" : "공지사항 수정"}</h2><p>게시하면 조직의 모든 사용자가 알림과 사용 안내에서 볼 수 있습니다.</p></div></header>
              <label><span>제목</span><input autoFocus maxLength={240} value={announcementTitle} onChange={(event) => setAnnouncementTitle(event.currentTarget.value)} placeholder="공지 제목" required /></label>
              <label className="help-announcement-body-field"><span>본문 Markdown 원문 (Raw code)</span><textarea className="thin-scrollbar" maxLength={20000} value={announcementBody} spellCheck={false} onChange={(event) => setAnnouncementBody(event.currentTarget.value)} placeholder="사용자에게 전달할 상세 내용을 Markdown으로 입력하세요." required /></label>
              <footer><button type="button" onClick={() => { setAnnouncementMode("idle"); if (!selectedAnnouncementId) setSelectedAnnouncementId(announcements[0]?.id ?? null); }}><X size={14} />취소</button><button className="lumina-primary-action" type="submit" disabled={busy || !announcementTitle.trim() || !announcementBody.trim()}>{busy ? <LoaderCircle className="is-running" size={14} /> : <Check size={14} />}{announcementMode === "create" ? "게시" : "저장"}</button></footer>
            </form>
          ) : !selectedAnnouncement ? (
            <div className="file-viewer-empty"><Megaphone size={28} /><strong>읽을 공지사항을 선택해 주세요.</strong><span>알림에서는 요약을 보고, 이곳에서 전체 내용을 확인할 수 있습니다.</span></div>
          ) : (
            <div className="file-viewer-document help-announcement-detail">
              <header className="file-viewer-heading help-viewer-heading">
                <span className="file-viewer-icon"><Megaphone size={22} /></span>
                <div><h2>{selectedAnnouncement.title}</h2><p>{selectedAnnouncement.author?.displayName || selectedAnnouncement.author?.loginId || "관리자"} · {formatDate(selectedAnnouncement.createdAt)}{announcementWasEdited(selectedAnnouncement) ? " · 수정됨" : ""}</p></div>
                {effectiveCanManage ? <div className="file-viewer-actions"><button type="button" disabled={busy} onClick={beginAnnouncementEdit}><Pencil size={14} />편집</button><button className={`is-danger ${announcementDeleteArmed ? "is-confirming" : ""}`} type="button" disabled={busy} onClick={() => void removeAnnouncement()}>{announcementDeleteArmed ? <AlertCircle size={14} /> : <Trash2 size={14} />}{announcementDeleteArmed ? "한 번 더 눌러 삭제" : "삭제"}</button></div> : null}
              </header>
              <article className="help-announcement-body thin-scrollbar"><MarkdownResponse text={selectedAnnouncement.body} /></article>
            </div>
          )}
        </section>
      </ResizableSplitPane>
    </main>
  );
}
