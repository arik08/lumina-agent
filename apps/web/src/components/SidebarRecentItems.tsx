import { useEffect, useMemo, useState, type UIEventHandler } from "react";
import {
  AlertCircle,
  Check,
  CheckCheck,
  Clock3,
  Folder,
  FolderInput,
  Heart,
  LoaderCircle,
  MessageCircle,
  MessageCircleQuestion,
  MoreVertical,
  Pencil,
  Pin,
  PinOff,
  Trash2,
  Waypoints,
  X,
} from "lucide-react";

export interface SidebarRecentItem {
  id: string;
  projectId: string;
  title: string;
  isFavorite: boolean;
  isLiked: boolean;
  status?: string;
  kind?: "conversation" | "deep-analysis";
}

interface SidebarProjectOption {
  id: string;
  name: string;
}

interface SidebarRecentItemsProps {
  items: SidebarRecentItem[];
  projects: SidebarProjectOption[];
  activeId: string | null;
  loading: boolean;
  emptyText: string;
  likedEmptyText: string;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => Promise<boolean>;
  onToggleFavorite: (id: string) => Promise<void>;
  onToggleLiked: (id: string) => Promise<void>;
  onMove: (id: string, projectId: string) => Promise<boolean>;
  onDelete: (id: string) => Promise<boolean>;
  onBulkMove: (ids: string[], projectId: string) => Promise<string[]>;
  onBulkDelete: (ids: string[]) => Promise<string[]>;
  onScroll?: UIEventHandler<HTMLDivElement>;
  onLoadMore?: () => void;
  hasMore?: boolean;
}

export function SidebarRecentItems({
  items,
  projects,
  activeId,
  loading,
  emptyText,
  likedEmptyText,
  onSelect,
  onRename,
  onToggleFavorite,
  onToggleLiked,
  onMove,
  onDelete,
  onBulkMove,
  onBulkDelete,
  onScroll,
  onLoadMore,
  hasMore = false,
}: SidebarRecentItemsProps) {
  const [likedOnly, setLikedOnly] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [moveMenuId, setMoveMenuId] = useState<string | null>(null);
  const [deleteArmedId, setDeleteArmedId] = useState<string | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("");
  const [bulkMode, setBulkMode] = useState(false);
  const [bulkIds, setBulkIds] = useState<Set<string>>(new Set());
  const [bulkMoveOpen, setBulkMoveOpen] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkDeleteArmed, setBulkDeleteArmed] = useState(false);
  const visibleItems = useMemo(
    () => items.filter((item) => !likedOnly || item.isLiked),
    [items, likedOnly],
  );

  useEffect(() => {
    const ids = new Set(items.map((item) => item.id));
    setBulkIds((current) => new Set([...current].filter((id) => ids.has(id))));
    if (menuId && !ids.has(menuId)) setMenuId(null);
  }, [items, menuId]);

  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setMenuId(null);
      setMoveMenuId(null);
      setDeleteArmedId(null);
      setEditingId(null);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  useEffect(() => {
    if (!menuId && !bulkMoveOpen) return undefined;
    const closeOutsideSubmenu = (event: PointerEvent) => {
      const target = event.target instanceof Element ? event.target : null;
      const clickedItem = target?.closest<HTMLElement>(".session-item");
      if (menuId && clickedItem?.dataset.recentItemId === menuId) return;
      if (bulkMoveOpen && target?.closest(".bulk-session-heading-actions")) return;
      setMenuId(null);
      setMoveMenuId(null);
      setDeleteArmedId(null);
      setBulkMoveOpen(false);
    };
    document.addEventListener("pointerdown", closeOutsideSubmenu);
    return () => document.removeEventListener("pointerdown", closeOutsideSubmenu);
  }, [bulkMoveOpen, menuId]);

  const finishBulk = (succeeded: string[]) => {
    const remaining = new Set([...bulkIds].filter((id) => !succeeded.includes(id)));
    setBulkIds(remaining);
    if (remaining.size === 0) {
      setBulkMode(false);
      setBulkMoveOpen(false);
    }
  };

  const commitRename = async (item: SidebarRecentItem) => {
    const title = titleDraft.trim();
    if (!title || title === item.title) {
      setEditingId(null);
      return;
    }
    if (await onRename(item.id, title)) setEditingId(null);
  };

  const deleteOne = async (id: string) => {
    if (deleteBusyId) return;
    if (deleteArmedId !== id) {
      setDeleteArmedId(id);
      return;
    }
    setDeleteBusyId(id);
    try {
      if (await onDelete(id)) setMenuId(null);
    } finally {
      setDeleteBusyId(null);
      setDeleteArmedId(null);
    }
  };

  return (
    <section className="sidebar-section session-section">
      <div className="sidebar-section-heading session-heading">
        <span>{bulkMode ? `${likedOnly ? "좋아요 · " : ""}${bulkIds.size}개 선택` : likedOnly ? "좋아요" : "최근 항목"}</span>
        {bulkMode ? (
          <div className="bulk-session-heading-actions">
            <button className="tooltip-control" type="button" aria-label="선택한 항목 프로젝트 이동" data-tooltip="이동" disabled={!bulkIds.size || bulkBusy || projects.length === 0} onClick={() => setBulkMoveOpen((open) => !open)}><FolderInput size={14} /></button>
            <button className={`tooltip-control is-danger ${bulkDeleteArmed ? "is-armed" : ""}`} type="button" aria-label={bulkDeleteArmed ? "선택한 항목 삭제 확인, 한 번 더 누르면 삭제" : "선택한 항목 삭제"} data-tooltip={bulkDeleteArmed ? "삭제경고" : "삭제"} disabled={!bulkIds.size || bulkBusy} onClick={async () => {
              if (!bulkDeleteArmed) { setBulkDeleteArmed(true); return; }
              setBulkBusy(true);
              try { finishBulk(await onBulkDelete([...bulkIds])); }
              finally { setBulkBusy(false); setBulkDeleteArmed(false); }
            }}>{bulkBusy ? <LoaderCircle className="is-running" size={14} /> : bulkDeleteArmed ? <AlertCircle size={14} /> : <Trash2 size={14} />}</button>
            <button className="bulk-session-select tooltip-control" type="button" aria-label={bulkIds.size === items.length ? "모든 항목 선택 해제" : "모든 항목 선택"} data-tooltip={bulkIds.size === items.length ? "선택 해제" : "전체 선택"} onClick={() => setBulkIds((current) => current.size === items.length ? new Set() : new Set(items.map((item) => item.id)))}><CheckCheck size={14} /></button>
            <button className="tooltip-control" type="button" aria-label="항목 관리 닫기" data-tooltip="닫기" onClick={() => { setBulkMode(false); setBulkIds(new Set()); setBulkMoveOpen(false); }}><X size={14} /></button>
            {bulkMoveOpen && (
              <div className="bulk-session-projects">
                {projects.map((project) => <button type="button" key={project.id} disabled={bulkBusy} onClick={async () => {
                  setBulkBusy(true);
                  try { finishBulk(await onBulkMove([...bulkIds], project.id)); }
                  finally { setBulkBusy(false); }
                }}><Folder size={13} /> {project.name}</button>)}
              </div>
            )}
          </div>
        ) : (
          <div className="session-heading-actions">
            {loading && <LoaderCircle className="is-running" size={13} />}
            <button className={`liked-sessions-filter session-heading-action tooltip-control ${likedOnly ? "is-active" : ""}`} type="button" aria-label={likedOnly ? "전체 보기" : "좋아요만 보기"} aria-pressed={likedOnly} data-tooltip={likedOnly ? "전체 보기" : "좋아요만"} onClick={() => setLikedOnly((active) => !active)}><Heart size={14} fill={likedOnly ? "currentColor" : "none"} /></button>
            <button className="bulk-session-open tooltip-control" type="button" aria-label="항목 관리" data-tooltip="항목 관리" disabled={items.length === 0} onClick={() => { setBulkMode(true); setBulkIds(new Set()); setMenuId(null); setMoveMenuId(null); }}><CheckCheck size={14} /></button>
          </div>
        )}
      </div>
      <div className="session-list" onScroll={(event) => {
        onScroll?.(event);
        const list = event.currentTarget;
        const prefetchDistance = Math.max(132, list.clientHeight * 0.35);
        if (hasMore && list.scrollHeight - list.scrollTop - list.clientHeight <= prefetchDistance) {
          onLoadMore?.();
        }
      }}>
        {visibleItems.map((item) => (
          <div className={`session-item ${item.id === activeId && !bulkMode ? "is-selected" : ""} ${bulkMode ? "is-bulk" : ""}`} data-recent-item-id={item.id} key={item.id}>
            {bulkMode ? (
              <button className="session-row" type="button" onClick={() => setBulkIds((current) => {
                const next = new Set(current);
                if (next.has(item.id)) next.delete(item.id); else next.add(item.id);
                return next;
              })} aria-pressed={bulkIds.has(item.id)}>
                <span className={`bulk-session-checkbox ${bulkIds.has(item.id) ? "is-checked" : ""}`}>{bulkIds.has(item.id) && <Check size={11} />}</span>
                <span>{item.title}</span>
              </button>
            ) : (
              <>
                <button className="session-like-button" type="button" aria-label={`${item.title} ${item.isLiked ? "좋아요 취소" : "좋아요"}`} aria-pressed={item.isLiked} onClick={() => void onToggleLiked(item.id)}>
                  {item.isLiked ? <Heart className="session-like" size={14} fill="currentColor" /> : item.kind === "deep-analysis" ? <Waypoints size={14} /> : item.status === "running" ? <LoaderCircle className="is-running" size={14} /> : item.status === "queued" ? <Clock3 size={14} /> : item.status === "input" ? <MessageCircleQuestion size={14} /> : item.status === "failed" ? <AlertCircle size={14} /> : item.isFavorite ? <Pin className="session-pin" size={14} /> : <MessageCircle size={14} />}
                </button>
                {editingId === item.id ? (
                  <input className="session-title-inline-input" aria-label={`${item.title} 이름 변경`} autoFocus value={titleDraft} onFocus={(event) => event.currentTarget.select()} onChange={(event) => setTitleDraft(event.currentTarget.value)} onBlur={() => void commitRename(item)} onKeyDown={(event) => {
                    if (event.key === "Enter") { event.preventDefault(); void commitRename(item); }
                    if (event.key === "Escape") { event.preventDefault(); setEditingId(null); }
                  }} />
                ) : <button className="session-row session-title-button" type="button" onClick={() => onSelect(item.id)}><span>{item.title}</span></button>}
              </>
            )}
            {!bulkMode && <button className="session-options-button" type="button" aria-label={`${item.title} 옵션`} aria-expanded={menuId === item.id} onClick={(event) => {
              event.stopPropagation();
              setMoveMenuId(null);
              setDeleteArmedId(null);
              setMenuId((current) => current === item.id ? null : item.id);
            }}><MoreVertical size={15} /></button>}
            {!bulkMode && menuId === item.id && (
              <div className="session-options-menu" role="menu" onClick={(event) => event.stopPropagation()}>
                <button type="button" role="menuitem" onClick={() => { setMenuId(null); void onToggleFavorite(item.id); }}>{item.isFavorite ? <PinOff size={14} /> : <Pin size={14} />} {item.isFavorite ? "즐겨찾기 해제" : "즐겨찾기"}</button>
                <button type="button" role="menuitem" onClick={() => { setMenuId(null); void onToggleLiked(item.id); }}><Heart size={14} fill={item.isLiked ? "currentColor" : "none"} /> {item.isLiked ? "좋아요 취소" : "좋아요"}</button>
                <button type="button" role="menuitem" onClick={() => { setTitleDraft(item.title); setEditingId(item.id); setMenuId(null); }}><Pencil size={14} /> 세션명 변경</button>
                <button type="button" role="menuitem" onClick={() => setMoveMenuId((current) => current === item.id ? null : item.id)}><FolderInput size={14} /> 프로젝트 변경</button>
                {moveMenuId === item.id && (
                  <div className="session-project-options">
                    {projects.filter((project) => project.id !== item.projectId).map((project) => <button type="button" key={project.id} onClick={async () => { if (await onMove(item.id, project.id)) setMenuId(null); }}><Folder size={13} /> {project.name}</button>)}
                    {projects.length === 0 && <span>이동할 프로젝트가 없습니다.</span>}
                  </div>
                )}
                <button className={`is-danger ${deleteArmedId === item.id ? "is-armed" : ""}`} type="button" role="menuitem" disabled={deleteBusyId === item.id} onClick={() => void deleteOne(item.id)}>{deleteBusyId === item.id ? <LoaderCircle className="is-running" size={14} /> : deleteArmedId === item.id ? <AlertCircle size={14} /> : <Trash2 size={14} />} {deleteArmedId === item.id ? "삭제 확인" : "삭제"}</button>
              </div>
            )}
          </div>
        ))}
        {!loading && visibleItems.length === 0 && <p className="sidebar-empty">{likedOnly ? likedEmptyText : emptyText}</p>}
      </div>
    </section>
  );
}
