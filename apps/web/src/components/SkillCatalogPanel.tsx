import { Eye, LoaderCircle, Play, RotateCcw, Search, SlidersHorizontal, ThumbsUp, UserRoundCheck, X } from "lucide-react";
import { memo, type ReactNode, useCallback, useLayoutEffect, useRef } from "react";
import type { SkillCatalogItem, SkillCatalogResponse } from "../api-types";
import { MarketplaceInstallButton } from "./MarketplaceInstallButton";
import { SelectMenu } from "./SelectMenu";


export type SkillCatalogSort = "popular" | "runs" | "likes" | "recent" | "name";

interface SkillCatalogPanelProps {
  catalog: SkillCatalogResponse;
  loading: boolean;
  loadingMore: boolean;
  query: string;
  category: string;
  tag: string;
  sort: SkillCatalogSort;
  pendingInstallIds: ReadonlySet<string>;
  pendingLikeIds: ReadonlySet<string>;
  scrollPosition: number;
  onQueryChange: (value: string) => void;
  onCategoryChange: (value: string) => void;
  onTagChange: (value: string) => void;
  onSortChange: (value: SkillCatalogSort) => void;
  onReset: () => void;
  onToggleInstall: (item: SkillCatalogItem) => void;
  onToggleLike: (item: SkillCatalogItem) => void;
  onView: (item: SkillCatalogItem) => void;
  onScrollPositionChange: (value: number) => void;
  onLoadMore: () => void;
}

const sortOptions = [
  { value: "popular", label: "사용자 설치 많은 순" },
  { value: "runs", label: "실행 많은 순" },
  { value: "likes", label: "좋아요 많은 순" },
  { value: "recent", label: "최근 업데이트순" },
  { value: "name", label: "이름순" },
] as const;

const countFormatter = new Intl.NumberFormat("ko-KR");
const categoryLabel = (value: string) => value === "기본 제공" ? "공통" : value;

function CatalogMetric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return <span
    className="skill-catalog-metric"
    aria-label={`${label} ${countFormatter.format(value)}`}
    data-tooltip={label}
  >
    {icon}<span>{countFormatter.format(value)}</span>
  </span>;
}

const CatalogCard = memo(function CatalogCard({
  item,
  installPending,
  likePending,
  onTagChange,
  onToggleInstall,
  onToggleLike,
  onView,
}: {
  item: SkillCatalogItem;
  installPending: boolean;
  likePending: boolean;
  onTagChange: (value: string) => void;
  onToggleInstall: (item: SkillCatalogItem) => void;
  onToggleLike: (item: SkillCatalogItem) => void;
  onView: (item: SkillCatalogItem) => void;
}) {
  return (
    <article className={`skill-catalog-card ${item.installed ? "is-installed" : ""} ${item.likedByMe ? "is-liked" : ""}`.trim()}>
      <div className="skill-catalog-card-copy">
        <div className="skill-catalog-card-header">
          <h2>{item.name}</h2>
          <span className="skill-catalog-category">{categoryLabel(item.category)}</span>
        </div>
        <p>{item.description || "설명이 등록되지 않은 Skill입니다."}</p>
        <div className="skill-catalog-tags" aria-label={`${item.name} 태그`}>
          {item.tags.map((value) => <button type="button" key={value} onClick={() => onTagChange(value)}>#{value}</button>)}
        </div>
      </div>
      <footer>
        <div className="skill-catalog-metrics">
          <CatalogMetric icon={<UserRoundCheck size={13} />} label="설치 사용자" value={item.installCount} />
          <CatalogMetric icon={<Play size={13} />} label="Skill 실행 횟수" value={item.runCount} />
          <button
            className={`skill-catalog-like ${item.likedByMe ? "is-liked" : ""}`}
            type="button"
            aria-label={`${item.name} 좋아요${item.likedByMe ? " 취소" : ""}`}
            aria-pressed={item.likedByMe}
            aria-busy={likePending}
            data-tooltip="좋아요"
            disabled={likePending}
            onClick={() => onToggleLike(item)}
          >
            {likePending ? <LoaderCircle className="is-running" size={13} /> : <ThumbsUp size={13} />}
            <span>{countFormatter.format(item.likeCount)}</span>
          </button>
        </div>
        <div className="skill-catalog-card-actions">
          {item.installed && <button className="skill-catalog-view tooltip-control" type="button" aria-label={`${item.name} 보기`} data-tooltip="보기" onClick={() => onView(item)}><Eye size={14} /></button>}
          {(item.installed || item.canInstall) && <MarketplaceInstallButton
            name={item.name}
            installed={item.installed}
            pending={installPending}
            onClick={() => onToggleInstall(item)}
          />}
        </div>
      </footer>
    </article>
  );
});

export function SkillCatalogPanel({
  catalog,
  loading,
  loadingMore,
  query,
  category,
  tag,
  sort,
  pendingInstallIds,
  pendingLikeIds,
  scrollPosition,
  onQueryChange,
  onCategoryChange,
  onTagChange,
  onSortChange,
  onReset,
  onToggleInstall,
  onToggleLike,
  onView,
  onScrollPositionChange,
  onLoadMore,
}: SkillCatalogPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const cardActionsRef = useRef({ onTagChange, onToggleInstall, onToggleLike, onView, onScrollPositionChange });
  cardActionsRef.current = { onTagChange, onToggleInstall, onToggleLike, onView, onScrollPositionChange };
  const changeCardTag = useCallback((value: string) => cardActionsRef.current.onTagChange(value), []);
  const toggleCardInstall = useCallback((item: SkillCatalogItem) => cardActionsRef.current.onToggleInstall(item), []);
  const toggleCardLike = useCallback((item: SkillCatalogItem) => cardActionsRef.current.onToggleLike(item), []);
  const hasFilters = Boolean(query.trim() || category || tag);
  useLayoutEffect(() => {
    const restoreScrollPosition = () => {
      if (scrollRef.current) scrollRef.current.scrollTop = scrollPosition;
    };
    restoreScrollPosition();
    const frame = window.requestAnimationFrame(restoreScrollPosition);
    return () => window.cancelAnimationFrame(frame);
  }, [scrollPosition]);
  const viewInstalledSkill = useCallback((item: SkillCatalogItem) => {
    cardActionsRef.current.onScrollPositionChange(scrollRef.current?.scrollTop ?? 0);
    cardActionsRef.current.onView(item);
  }, []);
  return (
    <div className="skill-catalog-layout">
      <aside className="skill-catalog-filters" aria-label="Skill 카탈로그 필터">
        <header><span><SlidersHorizontal size={14} /> 상세 필터</span><button type="button" disabled={!hasFilters} onClick={onReset}><RotateCcw size={12} /> 초기화</button></header>
        <label className="skill-catalog-search">
          <span><Search size={14} /><input type="search" aria-label="Skill 검색" placeholder="이름, 설명, 태그 검색" value={query} onChange={(event) => onQueryChange(event.currentTarget.value)} /></span>
        </label>
        <section>
          <h2>업무 영역</h2>
          <div className="skill-catalog-filter-grid">
            <button type="button" aria-pressed={!category} onClick={() => onCategoryChange("")}><span>전체</span><small>{catalog.facets.categories.reduce((sum, item) => sum + item.count, 0)}</small></button>
            {catalog.facets.categories.map((item) => <button type="button" aria-pressed={category === item.value} key={item.value} onClick={() => onCategoryChange(item.value)}><span>{categoryLabel(item.value)}</span><small>{item.count}</small></button>)}
          </div>
        </section>
        {catalog.facets.tags.length > 0 && <section>
          <h2>태그</h2>
          <div className="skill-catalog-filter-grid">
            {catalog.facets.tags.map((item) => <button type="button" aria-pressed={tag === item.value} key={item.value} onClick={() => onTagChange(tag === item.value ? "" : item.value)}><span>#{item.value}</span><small>{item.count}</small></button>)}
          </div>
        </section>}
      </aside>
      <section className="skill-catalog-results">
        <header className="skill-catalog-results-toolbar">
          <div><span>총 <strong>{countFormatter.format(catalog.total)}</strong>개의 Skill</span>{hasFilters && <div className="skill-catalog-active-filters">{category && <button type="button" onClick={() => onCategoryChange("")}>{categoryLabel(category)}<X size={11} /></button>}{tag && <button type="button" onClick={() => onTagChange("")}>#{tag}<X size={11} /></button>}</div>}</div>
          <SelectMenu value={sort} options={sortOptions} ariaLabel="카탈로그 정렬" size="small" width="auto" align="end" onChange={(value) => onSortChange(value as SkillCatalogSort)} />
        </header>
        <div className="skill-catalog-scroll" ref={scrollRef}>
          {loading ? <div className="skill-catalog-grid is-loading" aria-label="Skill 카탈로그를 불러오는 중">{Array.from({ length: 6 }, (_, index) => <div className="skill-catalog-skeleton" aria-hidden="true" key={index}><span /><strong /><p /><p /><footer /></div>)}</div>
            : catalog.items.length === 0 ? <div className="skill-catalog-empty"><Search size={20} /><strong>검색 결과가 없습니다.</strong><span>검색어나 필터를 바꿔 다시 확인해 주세요.</span>{hasFilters && <button type="button" onClick={onReset}>필터 초기화</button>}</div>
              : <><div className="skill-catalog-grid">{catalog.items.map((item) => <CatalogCard item={item} installPending={pendingInstallIds.has(item.id)} likePending={pendingLikeIds.has(item.id)} key={item.id} onTagChange={changeCardTag} onToggleInstall={toggleCardInstall} onToggleLike={toggleCardLike} onView={viewInstalledSkill} />)}</div>{catalog.hasMore && <button className="skill-catalog-more" type="button" disabled={loadingMore} onClick={onLoadMore}>{loadingMore ? <LoaderCircle className="is-running" size={14} /> : null} 더 보기</button>}</>}
        </div>
      </section>
    </div>
  );
}
