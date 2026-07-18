import { BookOpenText, CircleDot, FileText, Search, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type { KnowledgeEntity, KnowledgeSource, KnowledgeStatement } from "../../api-types";
import type { KnowledgeTab } from "./KnowledgeView";
import { evidenceById, statementSentence } from "./knowledge-utils";

interface KnowledgeExploreProps {
  sources: KnowledgeSource[];
  entities: KnowledgeEntity[];
  statements: KnowledgeStatement[];
  entityById: Map<string, KnowledgeEntity>;
  onOpenEntity: (entityId: string, tab?: KnowledgeTab) => void;
  onOpenEvidence: (evidenceId: string) => void;
}

type SearchScope = "all" | "wiki" | "statement" | "source";

export function KnowledgeExplore({ sources, entities, statements, entityById, onOpenEntity, onOpenEvidence }: KnowledgeExploreProps) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<SearchScope>("all");
  const evidence = useMemo(() => evidenceById(sources), [sources]);
  const normalized = query.trim().toLocaleLowerCase();
  const entityResults = entities.filter((entity) => !normalized || `${entity.canonicalName} ${entity.entityType} ${entity.description}`.toLocaleLowerCase().includes(normalized));
  const statementResults = statements.filter((statement) => statement.status !== "rejected" && (!normalized || statementSentence(statement, entityById).toLocaleLowerCase().includes(normalized)));
  const sourceResults = sources.filter((source) => !normalized || `${source.title} ${source.evidenceSegments.map((item) => item.text).join(" ")}`.toLocaleLowerCase().includes(normalized));
  const resultCount = (scope === "all" || scope === "wiki" ? entityResults.length : 0)
    + (scope === "all" || scope === "statement" ? statementResults.length : 0)
    + (scope === "all" || scope === "source" ? sourceResults.length : 0);

  return (
    <div className="knowledge-page knowledge-explore">
      <section className="knowledge-search-hero">
        <div className="knowledge-search-box">
          <Search size={18} />
          <input autoFocus value={query} placeholder="Entity, 사실, 원문에서 검색" aria-label="지식 검색" onChange={(event) => setQuery(event.target.value)} />
          {query && <button type="button" aria-label="검색어 지우기" onClick={() => setQuery("")}><X size={15} /></button>}
        </div>
        <p>현재 Space의 원문·Entity·Statement를 함께 검색합니다. 검색 결과의 근거를 열어 원문까지 확인할 수 있습니다.</p>
      </section>
      <div className="knowledge-filter-row" role="group" aria-label="검색 범위">
        {(["all", "wiki", "statement", "source"] as const).map((value) => (
          <button type="button" className={scope === value ? "is-active" : ""} key={value} onClick={() => setScope(value)}>
            {{ all: "전체", wiki: "Wiki", statement: "Statement", source: "원문" }[value]}
          </button>
        ))}
        <span>{resultCount}개 결과</span>
      </div>

      {!resultCount ? <div className="knowledge-empty"><Search size={24} /><h3>검색 결과가 없습니다.</h3><p>다른 표현이나 Entity 이름으로 다시 찾아보세요.</p></div> : (
        <div className="knowledge-search-results">
          {(scope === "all" || scope === "wiki") && entityResults.length > 0 && <SearchGroup icon={<BookOpenText size={15} />} title="Wiki Entity" count={entityResults.length}>{entityResults.map((entity) => (
            <button type="button" key={entity.id} onClick={() => onOpenEntity(entity.id)}>
              <CircleDot size={14} /><span><strong>{entity.canonicalName}</strong><small>{entity.description || `${entity.entityType} Entity`}</small></span><em>{entity.entityType}</em>
            </button>
          ))}</SearchGroup>}

          {(scope === "all" || scope === "statement") && statementResults.length > 0 && <SearchGroup icon={<CircleDot size={15} />} title="Statement" count={statementResults.length}>{statementResults.map((statement) => {
            const firstEvidence = statement.evidenceSegmentIds[0];
            const evidenceInfo = firstEvidence ? evidence.get(firstEvidence) : null;
            return <article key={statement.id}><button type="button" onClick={() => onOpenEntity(statement.subjectEntityId)}><span><strong>{statementSentence(statement, entityById)}</strong><small>revision {statement.revisionNumber ?? "-"} · {statement.status === "approved" ? "승인" : "검토 대기"}</small></span></button>{evidenceInfo && <button className="knowledge-citation" type="button" onClick={() => onOpenEvidence(firstEvidence)}><FileText size={12} /> {evidenceInfo.source.title}</button>}</article>;
          })}</SearchGroup>}

          {(scope === "all" || scope === "source") && sourceResults.length > 0 && <SearchGroup icon={<FileText size={15} />} title="원문" count={sourceResults.length}>{sourceResults.map((source) => (
            <button type="button" key={source.id} onClick={() => source.evidenceSegments[0] && onOpenEvidence(source.evidenceSegments[0].id)}>
              <FileText size={14} /><span><strong>{source.title}</strong><small>{source.evidenceSegments[0]?.text.slice(0, 140) || "보존된 텍스트가 없습니다."}</small></span><em>rev {source.revision.revisionNumber}</em>
            </button>
          ))}</SearchGroup>}
        </div>
      )}
    </div>
  );
}

interface SearchGroupProps {
  icon: ReactNode;
  title: string;
  count: number;
  children: ReactNode;
}

function SearchGroup({ icon, title, count, children }: SearchGroupProps) {
  return <section className="knowledge-result-group"><header>{icon}<strong>{title}</strong><span>{count}</span></header><div>{children}</div></section>;
}
