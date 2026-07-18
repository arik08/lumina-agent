import {
  BookOpenText,
  Check,
  ChevronRight,
  CircleDot,
  FileText,
  History,
  LoaderCircle,
  Pencil,
  ShieldCheck,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api";
import type {
  KnowledgeEntity,
  KnowledgePage,
  KnowledgePageRevision,
  KnowledgeSource,
  KnowledgeStatement,
} from "../../api-types";
import { evidenceById, formatDate, statementObject } from "./knowledge-utils";

interface KnowledgeWikiProps {
  sources: KnowledgeSource[];
  entities: KnowledgeEntity[];
  pages: KnowledgePage[];
  statements: KnowledgeStatement[];
  entityById: Map<string, KnowledgeEntity>;
  selectedEntityId: string | null;
  onSelectEntity: (entityId: string) => void;
  onOpenEvidence: (evidenceId: string) => void;
  onPageUpdated: (page: KnowledgePage) => void;
  onError: (error: unknown) => void;
}

export function KnowledgeWiki({
  sources,
  entities,
  pages,
  statements,
  entityById,
  selectedEntityId,
  onSelectEntity,
  onOpenEvidence,
  onPageUpdated,
  onError,
}: KnowledgeWikiProps) {
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState(false);
  const [manualDraft, setManualDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [revisions, setRevisions] = useState<KnowledgePageRevision[]>([]);
  const [selectedRevisionId, setSelectedRevisionId] = useState<string | null>(null);

  const selected = entities.find((entity) => entity.id === selectedEntityId) ?? entities[0] ?? null;
  const pageByEntity = useMemo(() => new Map(pages.map((item) => [item.entityId, item])), [pages]);
  const page = selected ? pageByEntity.get(selected.id) ?? null : null;
  const evidence = useMemo(() => evidenceById(sources), [sources]);
  const filtered = entities.filter((entity) => entity.canonicalName.toLocaleLowerCase().includes(filter.trim().toLocaleLowerCase()));
  const related = selected ? statements.filter((statement) => statement.subjectEntityId === selected.id || statement.objectEntityId === selected.id) : [];
  const approved = related.filter((statement) => statement.status === "approved");
  const pending = related.filter((statement) => statement.status === "proposed");
  const sourceCoverage = new Set(approved.flatMap((statement) => statement.evidenceSegmentIds.map((id) => evidence.get(id)?.source.id).filter(Boolean)));
  const selectedRevision = revisions.find((revision) => revision.id === selectedRevisionId) ?? null;

  useEffect(() => {
    setEditing(false);
    setManualDraft(page?.currentRevision.manualMarkdown ?? "");
    setHistoryOpen(false);
    setRevisions([]);
    setSelectedRevisionId(null);
  }, [page?.id, page?.currentRevision.revisionNumber]);

  async function saveManualMarkdown() {
    if (!page || saving) return;
    setSaving(true);
    try {
      const updated = await api.knowledge.updatePage(page.id, {
        expectedRevision: page.currentRevision.revisionNumber,
        manualMarkdown: manualDraft,
      });
      onPageUpdated(updated);
      setEditing(false);
      setRevisions([]);
      setSelectedRevisionId(null);
    } catch (error) {
      onError(error);
    } finally {
      setSaving(false);
    }
  }

  async function toggleHistory() {
    if (!page) return;
    if (historyOpen) {
      setHistoryOpen(false);
      return;
    }
    setHistoryOpen(true);
    if (revisions.length) return;
    setLoadingHistory(true);
    try {
      const items = await api.knowledge.listPageRevisions(page.id);
      setRevisions(items);
      setSelectedRevisionId(items.find((item) => item.revisionNumber !== page.currentRevision.revisionNumber)?.id ?? items[0]?.id ?? null);
    } catch (error) {
      setHistoryOpen(false);
      onError(error);
    } finally {
      setLoadingHistory(false);
    }
  }

  if (!entities.length) return <div className="knowledge-empty"><BookOpenText size={25} /><h3>Wiki로 표시할 Entity가 없습니다.</h3><p>원문에서 Entity를 추출하거나 상단에서 직접 등록해 주세요.</p></div>;

  return (
    <div className="knowledge-master-detail knowledge-wiki-page">
      <aside className="knowledge-master-list">
        <header><div><strong>Wiki</strong><small>{entities.length}개 지식 문서</small></div><input value={filter} aria-label="Wiki Entity 필터" placeholder="Entity 찾기" onChange={(event) => setFilter(event.target.value)} /></header>
        {filtered.map((entity) => {
          const count = statements.filter((statement) => statement.status === "approved" && (statement.subjectEntityId === entity.id || statement.objectEntityId === entity.id)).length;
          const entityPage = pageByEntity.get(entity.id);
          return <button type="button" className={selected?.id === entity.id ? "is-active" : ""} key={entity.id} onClick={() => onSelectEntity(entity.id)}><CircleDot size={14} /><span><strong>{entity.canonicalName}</strong><small>{entity.entityType} · revision {entityPage?.currentRevision.revisionNumber ?? 1}</small></span><em>{count}</em></button>;
        })}
      </aside>

      {selected && <article className="knowledge-wiki-article">
        <header>
          <div className="knowledge-wiki-breadcrumb"><BookOpenText size={13} /> Wiki <ChevronRight size={12} /> {selected.entityType}</div>
          <div className="knowledge-wiki-title-row">
            <h2>{selected.canonicalName}</h2>
            {page && <div className="knowledge-wiki-actions">
              <button type="button" onClick={() => setEditing((current) => !current)}>{editing ? <X size={13} /> : <Pencil size={13} />}{editing ? "편집 취소" : "메모 편집"}</button>
              <button className={historyOpen ? "is-active" : ""} type="button" onClick={toggleHistory}><History size={13} /> 변경 이력</button>
            </div>}
          </div>
          <p>{selected.description || `${selected.canonicalName}에 대해 승인된 Statement와 사용자가 작성한 메모를 함께 보존하는 Wiki 문서입니다.`}</p>
          <div className="knowledge-wiki-metrics"><span><ShieldCheck size={13} /> 승인 사실 {approved.length}</span><span><FileText size={13} /> 출처 {sourceCoverage.size}</span>{page && <span><History size={13} /> revision {page.currentRevision.revisionNumber}</span>}{pending.length > 0 && <span className="is-warning">검토 대기 {pending.length}</span>}</div>
        </header>

        {page && (editing || page.currentRevision.manualMarkdown) && <section className="knowledge-wiki-manual">
          <div className="knowledge-wiki-section-heading"><h3>사용자 메모</h3>{!editing && <span>AI 재생성 시에도 유지됩니다.</span>}</div>
          {editing ? <div className="knowledge-wiki-editor">
            <textarea autoFocus value={manualDraft} maxLength={200_000} rows={8} aria-label="Wiki 사용자 메모" placeholder="분석 과정에서 얻은 해석, 결정, 후속 확인 사항을 Markdown으로 남겨 주세요." onChange={(event) => setManualDraft(event.target.value)} />
            <div><small>{manualDraft.length.toLocaleString()} / 200,000</small><button type="button" onClick={() => { setEditing(false); setManualDraft(page.currentRevision.manualMarkdown); }}><X size={13} /> 취소</button><button className="is-primary" type="button" disabled={saving} onClick={saveManualMarkdown}>{saving ? <LoaderCircle className="is-running" size={13} /> : <Check size={13} />} 저장</button></div>
          </div> : <div className="knowledge-wiki-manual-content">{page.currentRevision.manualMarkdown}</div>}
        </section>}

        {historyOpen && page && <section className="knowledge-wiki-history" aria-label="Wiki 변경 이력">
          <div className="knowledge-wiki-section-heading"><h3>변경 이력</h3><span>생성 지식과 사용자 메모를 하나의 revision으로 추적합니다.</span></div>
          {loadingHistory ? <div className="knowledge-loading"><LoaderCircle className="is-running" size={15} /> 이력을 불러오는 중</div> : <div className="knowledge-wiki-history-layout">
            <div className="knowledge-wiki-revision-list">{revisions.map((revision) => <button className={selectedRevision?.id === revision.id ? "is-active" : ""} type="button" key={revision.id} onClick={() => setSelectedRevisionId(revision.id)}><span><strong>revision {revision.revisionNumber}</strong>{revision.revisionNumber === page.currentRevision.revisionNumber && <em>현재</em>}</span><small>{formatDate(revision.createdAt)}</small></button>)}</div>
            {selectedRevision && <div className="knowledge-wiki-compare">
              <div><header><strong>revision {selectedRevision.revisionNumber}</strong><span>{formatDate(selectedRevision.createdAt)}</span></header><pre>{selectedRevision.markdownBody}</pre></div>
              <div><header><strong>현재 revision {page.currentRevision.revisionNumber}</strong><span>{formatDate(page.currentRevision.createdAt)}</span></header><pre>{page.currentRevision.markdownBody}</pre></div>
            </div>}
          </div>}
        </section>}

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
