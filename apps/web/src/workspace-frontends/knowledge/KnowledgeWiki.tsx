import { BookOpenText, ChevronRight, CircleDot, FileText, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import type { KnowledgeEntity, KnowledgeSource, KnowledgeStatement } from "../../api-types";
import { evidenceById, formatDate, statementObject } from "./knowledge-utils";

interface KnowledgeWikiProps {
  sources: KnowledgeSource[];
  entities: KnowledgeEntity[];
  statements: KnowledgeStatement[];
  entityById: Map<string, KnowledgeEntity>;
  selectedEntityId: string | null;
  onSelectEntity: (entityId: string) => void;
  onOpenEvidence: (evidenceId: string) => void;
}

export function KnowledgeWiki({ sources, entities, statements, entityById, selectedEntityId, onSelectEntity, onOpenEvidence }: KnowledgeWikiProps) {
  const [filter, setFilter] = useState("");
  const selected = entities.find((entity) => entity.id === selectedEntityId) ?? entities[0] ?? null;
  const evidence = useMemo(() => evidenceById(sources), [sources]);
  const filtered = entities.filter((entity) => entity.canonicalName.toLocaleLowerCase().includes(filter.trim().toLocaleLowerCase()));
  const related = selected ? statements.filter((statement) => statement.subjectEntityId === selected.id || statement.objectEntityId === selected.id) : [];
  const approved = related.filter((statement) => statement.status === "approved");
  const pending = related.filter((statement) => statement.status === "proposed");
  const sourceCoverage = new Set(approved.flatMap((statement) => statement.evidenceSegmentIds.map((id) => evidence.get(id)?.source.id).filter(Boolean)));

  if (!entities.length) return <div className="knowledge-empty"><BookOpenText size={25} /><h3>Wiki로 표시할 Entity가 없습니다.</h3><p>원문에서 Entity를 추출하거나 상단에서 직접 등록해 주세요.</p></div>;

  return (
    <div className="knowledge-master-detail knowledge-wiki-page">
      <aside className="knowledge-master-list">
        <header><div><strong>Wiki</strong><small>{entities.length}개 Entity projection</small></div><input value={filter} aria-label="Wiki Entity 필터" placeholder="Entity 찾기" onChange={(event) => setFilter(event.target.value)} /></header>
        {filtered.map((entity) => {
          const count = statements.filter((statement) => statement.status === "approved" && (statement.subjectEntityId === entity.id || statement.objectEntityId === entity.id)).length;
          return <button type="button" className={selected?.id === entity.id ? "is-active" : ""} key={entity.id} onClick={() => onSelectEntity(entity.id)}><CircleDot size={14} /><span><strong>{entity.canonicalName}</strong><small>{entity.entityType}</small></span><em>{count}</em></button>;
        })}
      </aside>

      {selected && <article className="knowledge-wiki-article">
        <header>
          <div className="knowledge-wiki-breadcrumb"><BookOpenText size={13} /> Wiki <ChevronRight size={12} /> {selected.entityType}</div>
          <h2>{selected.canonicalName}</h2>
          <p>{selected.description || `${selected.canonicalName}에 대해 승인된 Statement를 읽기 쉽게 구성한 Wiki projection입니다.`}</p>
          <div><span><ShieldCheck size={13} /> 승인 사실 {approved.length}</span><span><FileText size={13} /> 출처 {sourceCoverage.size}</span>{pending.length > 0 && <span className="is-warning">검토 대기 {pending.length}</span>}</div>
        </header>

        <section>
          <h3>확인된 사실</h3>
          {approved.length ? <div className="knowledge-wiki-facts">{approved.map((statement) => (
            <div key={statement.id}>
              <p>{statement.subjectEntityId === selected.id ? <><strong>{selected.canonicalName}</strong>은(는) <em>{statement.predicateKey.replaceAll("_", " ").toLocaleLowerCase()}</em> <strong>{statementObject(statement, entityById)}</strong>입니다.</> : <><strong>{entityById.get(statement.subjectEntityId)?.canonicalName ?? "알 수 없는 Entity"}</strong>에서 <em>{statement.predicateKey.replaceAll("_", " ").toLocaleLowerCase()}</em> 관계로 연결됩니다.</>}</p>
              <footer><span>revision {statement.revisionNumber ?? "-"} · {formatDate(statement.recordedAt)}</span><div>{statement.evidenceSegmentIds.map((id, index) => { const info = evidence.get(id); return info ? <button className="knowledge-citation" type="button" key={id} onClick={() => onOpenEvidence(id)}><FileText size={11} /> [{index + 1}] {info.source.title}</button> : null; })}</div></footer>
            </div>
          ))}</div> : <div className="knowledge-card-empty"><ShieldCheck size={20} /><p>아직 승인된 사실이 없습니다. 검토함에서 근거를 확인하고 승인해 주세요.</p></div>}
        </section>

        {pending.length > 0 && <aside className="knowledge-wiki-notice"><ShieldCheck size={17} /><div><strong>{pending.length}개 제안은 아직 본문에 반영되지 않았습니다.</strong><p>검토가 끝난 Statement만 Wiki와 Graph의 공식 지식으로 사용됩니다.</p></div></aside>}

        <section>
          <h3>출처와 근거</h3>
          {approved.flatMap((statement) => statement.evidenceSegmentIds).filter((id, index, all) => all.indexOf(id) === index).map((id) => { const info = evidence.get(id); return info ? <button className="knowledge-source-reference" type="button" key={id} onClick={() => onOpenEvidence(id)}><FileText size={15} /><span><strong>{info.source.title}</strong><small>{info.evidence.text.slice(0, 160)}</small></span><em>원문 열기</em></button> : null; })}
        </section>
      </article>}
    </div>
  );
}
