import {
  BookOpenText,
  CircleDot,
  FileText,
  GitBranch,
  LoaderCircle,
  Menu,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { SelectMenu } from "../../components/SelectMenu";
import type {
  KnowledgeEntity,
  KnowledgeIngestionJob,
  KnowledgeNeighborhood,
  KnowledgeSource,
  KnowledgeSpace,
  KnowledgeStatement,
} from "../../api-types";
import "./knowledge.css";

type KnowledgeTab = "graph" | "records";
type CreatePanel = "space" | "source" | "entity" | "statement" | null;

interface KnowledgeViewProps {
  onOpenNavigation: () => void;
}

function errorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "지식 데이터를 처리하지 못했습니다.";
}

async function sha256Hex(value: string) {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function KnowledgeView({ onOpenNavigation }: KnowledgeViewProps) {
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [ingestions, setIngestions] = useState<KnowledgeIngestionJob[]>([]);
  const [entities, setEntities] = useState<KnowledgeEntity[]>([]);
  const [statements, setStatements] = useState<KnowledgeStatement[]>([]);
  const [neighborhood, setNeighborhood] = useState<KnowledgeNeighborhood | null>(null);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [tab, setTab] = useState<KnowledgeTab>("graph");
  const [createPanel, setCreatePanel] = useState<CreatePanel>(null);
  const [loadingSpaces, setLoadingSpaces] = useState(true);
  const [loadingContent, setLoadingContent] = useState(false);
  const [saving, setSaving] = useState(false);
  const [startingSourceId, setStartingSourceId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [spaceName, setSpaceName] = useState("");
  const [spacePurpose, setSpacePurpose] = useState("");
  const [sourceTitle, setSourceTitle] = useState("");
  const [sourceText, setSourceText] = useState("");
  const [entityName, setEntityName] = useState("");
  const [entityType, setEntityType] = useState("concept");
  const [subjectId, setSubjectId] = useState("");
  const [predicate, setPredicate] = useState("RELATED_TO");
  const [objectId, setObjectId] = useState("");
  const [evidenceId, setEvidenceId] = useState("");

  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
  const entityById = useMemo(
    () => new Map(entities.map((entity) => [entity.id, entity])),
    [entities],
  );
  const evidenceOptions = useMemo(
    () => sources.flatMap((source) => source.evidenceSegments.map((item) => ({
      id: item.id,
      label: `${source.title} · ${item.text.slice(0, 54)}`,
    }))),
    [sources],
  );
  const entityOptions = useMemo(
    () => [{ value: "", label: "선택" }, ...entities.map((entity) => ({
      value: entity.id,
      label: entity.canonicalName,
    }))],
    [entities],
  );
  const objectEntityOptions = useMemo(
    () => entityOptions.filter((option) => !option.value || option.value !== subjectId),
    [entityOptions, subjectId],
  );
  const evidenceMenuOptions = useMemo(
    () => [{ value: "", label: "없음 · 검토 제안으로 저장" }, ...evidenceOptions.map((item) => ({
      value: item.id,
      label: item.label,
    }))],
    [evidenceOptions],
  );

  useEffect(() => {
    const controller = new AbortController();
    setLoadingSpaces(true);
    api.knowledge.listSpaces(controller.signal)
      .then((items) => {
        setSpaces(items);
        setSelectedSpaceId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id ?? null));
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingSpaces(false);
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!selectedSpaceId) {
      setSources([]);
      setIngestions([]);
      setEntities([]);
      setStatements([]);
      setNeighborhood(null);
      return;
    }
    const controller = new AbortController();
    setLoadingContent(true);
    setError(null);
    Promise.all([
      api.knowledge.listSources(selectedSpaceId, controller.signal),
      api.knowledge.listIngestions(selectedSpaceId, controller.signal),
      api.knowledge.listEntities(selectedSpaceId, controller.signal),
      api.knowledge.listStatements(selectedSpaceId, controller.signal),
    ])
      .then(([nextSources, nextIngestions, nextEntities, nextStatements]) => {
        setSources(nextSources);
        setIngestions(nextIngestions);
        setEntities(nextEntities);
        setStatements(nextStatements);
        setSelectedEntityId((current) => nextEntities.some((item) => item.id === current) ? current : (nextEntities[0]?.id ?? null));
      })
      .catch((loadError) => {
        if (!controller.signal.aborted) setError(errorMessage(loadError));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadingContent(false);
      });
    return () => controller.abort();
  }, [selectedSpaceId]);

  useEffect(() => {
    if (!selectedSpaceId || !ingestions.some((job) => job.status === "queued" || job.status === "running")) return;
    let disposed = false;
    const timer = window.setInterval(() => {
      Promise.all([
        api.knowledge.listIngestions(selectedSpaceId),
        api.knowledge.listEntities(selectedSpaceId),
        api.knowledge.listStatements(selectedSpaceId),
      ])
        .then(([nextIngestions, nextEntities, nextStatements]) => {
          if (disposed) return;
          setIngestions(nextIngestions);
          setEntities(nextEntities);
          setStatements(nextStatements);
          setSelectedEntityId((current) => nextEntities.some((item) => item.id === current) ? current : (nextEntities[0]?.id ?? null));
        })
        .catch((loadError) => {
          if (!disposed) setError(errorMessage(loadError));
        });
    }, 1_200);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [ingestions, selectedSpaceId]);

  useEffect(() => {
    if (!selectedEntityId) {
      setNeighborhood(null);
      return;
    }
    const controller = new AbortController();
    api.knowledge.getNeighborhood(selectedEntityId, 2, controller.signal)
      .then(setNeighborhood)
      .catch((loadError) => {
        if (!controller.signal.aborted) setError(errorMessage(loadError));
      });
    return () => controller.abort();
  }, [selectedEntityId, statements]);

  async function createSpace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceName.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.knowledge.createSpace({
        name: spaceName.trim(),
        purpose: spacePurpose.trim(),
      });
      setSpaces((current) => [created, ...current]);
      setSelectedSpaceId(created.id);
      setSpaceName("");
      setSpacePurpose("");
      setCreatePanel(null);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSaving(false);
    }
  }

  async function createSource(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSpaceId || !sourceTitle.trim() || !sourceText.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const text = sourceText.trim();
      const encoded = new TextEncoder().encode(text);
      const created = await api.knowledge.createSource(selectedSpaceId, {
        sourceType: "text",
        title: sourceTitle.trim(),
        contentDigest: await sha256Hex(text),
        mediaType: "text/plain",
        byteSize: encoded.byteLength,
        capturedText: text,
        evidenceSegments: [{
          text,
          locator: { section: "manual" },
          language: "ko",
          tokenCount: Math.ceil(text.length / 3),
        }],
      });
      setSources((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSourceTitle("");
      setSourceText("");
      setCreatePanel(null);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSaving(false);
    }
  }

  async function createEntity(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSpaceId || !entityName.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.knowledge.createEntity(selectedSpaceId, {
        canonicalName: entityName.trim(),
        entityType: entityType.trim() || "concept",
      });
      setEntities((current) => [...current.filter((item) => item.id !== created.id), created]
        .sort((left, right) => left.canonicalName.localeCompare(right.canonicalName)));
      setSelectedEntityId(created.id);
      setEntityName("");
      setCreatePanel(null);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSaving(false);
    }
  }

  async function startIngestion(sourceId: string) {
    if (!selectedSpaceId || startingSourceId) return;
    setStartingSourceId(sourceId);
    setError(null);
    try {
      const job = await api.knowledge.startIngestion(selectedSpaceId, sourceId);
      setIngestions((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setTab("records");
    } catch (startError) {
      setError(errorMessage(startError));
    } finally {
      setStartingSourceId(null);
    }
  }

  async function createStatement(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSpaceId || !subjectId || !objectId || !predicate.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.knowledge.createStatement(selectedSpaceId, {
        subjectEntityId: subjectId,
        predicateKey: predicate.trim().toUpperCase().replace(/\s+/g, "_"),
        objectKind: "entity",
        objectEntityId: objectId,
        evidenceSegmentIds: evidenceId ? [evidenceId] : [],
        status: evidenceId ? "approved" : "proposed",
        changeSummary: "Knowledge 화면에서 관계 등록",
      });
      setStatements((current) => [created, ...current]);
      setSelectedEntityId(subjectId);
      setObjectId("");
      setEvidenceId("");
      setCreatePanel(null);
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSaving(false);
    }
  }

  function togglePanel(panel: Exclude<CreatePanel, null>) {
    setCreatePanel((current) => current === panel ? null : panel);
  }

  return (
    <main className="feature-view knowledge-view" aria-label="지식">
      <header className="feature-header knowledge-header">
        <div>
          <button className="knowledge-mobile-menu" type="button" aria-label="메뉴 열기" onClick={onOpenNavigation}><Menu size={17} /></button>
          <BookOpenText size={17} />
          <h1>지식</h1>
          <span>원문과 근거를 보존하면서 Wiki와 Knowledge Graph를 함께 관리합니다.</span>
        </div>
        <button type="button" onClick={() => togglePanel("space")}>
          {createPanel === "space" ? <X size={15} /> : <Plus size={15} />}
          {createPanel === "space" ? "닫기" : "새 공간"}
        </button>
      </header>

      {error && <div className="knowledge-error" role="alert"><span>{error}</span><button type="button" onClick={() => setError(null)}><X size={14} /> 닫기</button></div>}

      {createPanel === "space" && (
        <form className="knowledge-inline-form knowledge-space-form" onSubmit={createSpace}>
          <label>공간 이름<input autoFocus value={spaceName} maxLength={240} placeholder="예: 제품 설계 지식" onChange={(event) => setSpaceName(event.target.value)} /></label>
          <label>목적<input value={spacePurpose} maxLength={20_000} placeholder="이 공간에서 축적할 지식의 범위" onChange={(event) => setSpacePurpose(event.target.value)} /></label>
          <button type="submit" disabled={saving || !spaceName.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 만들기</button>
        </form>
      )}

      <div className="knowledge-layout">
        <aside className="knowledge-spaces" aria-label="Knowledge Space 목록">
          <div className="knowledge-pane-title"><strong>Knowledge Space</strong><span>{spaces.length}</span></div>
          {loadingSpaces ? <div className="knowledge-loading"><LoaderCircle className="is-running" size={16} /> 불러오는 중</div> : spaces.length ? (
            <div className="knowledge-space-list">
              {spaces.map((space) => (
                <button className={selectedSpaceId === space.id ? "is-active" : ""} type="button" key={space.id} onClick={() => setSelectedSpaceId(space.id)}>
                  <BookOpenText size={15} /><span><strong>{space.name}</strong><small>{space.purpose || "개인 지식 공간"}</small></span>
                </button>
              ))}
            </div>
          ) : <div className="knowledge-list-empty"><p>아직 지식 공간이 없습니다.</p><button type="button" onClick={() => setCreatePanel("space")}><Plus size={14} /> 첫 공간 만들기</button></div>}
        </aside>

        <section className="knowledge-workspace">
          {!selectedSpace ? <KnowledgeEmpty /> : (
            <>
              <header className="knowledge-space-header">
                <div><small>개인 · 비공개</small><h2>{selectedSpace.name}</h2><p>{selectedSpace.purpose || selectedSpace.description || "원문과 검증된 관계를 축적하는 계정 단위 공간입니다."}</p></div>
                <div className="knowledge-metrics" aria-label="지식 현황">
                  <span><b>{sources.length}</b> 원문</span><span><b>{entities.length}</b> Entity</span><span><b>{statements.length}</b> Statement</span>
                </div>
              </header>
              <div className="knowledge-toolbar">
                <div role="tablist" aria-label="지식 화면">
                  <button className={tab === "graph" ? "is-active" : ""} type="button" role="tab" aria-selected={tab === "graph"} onClick={() => setTab("graph")}><GitBranch size={14} /> 그래프</button>
                  <button className={tab === "records" ? "is-active" : ""} type="button" role="tab" aria-selected={tab === "records"} onClick={() => setTab("records")}><FileText size={14} /> 원문·사실</button>
                </div>
                <div>
                  <button type="button" onClick={() => togglePanel("source")}><Plus size={13} /> 원문</button>
                  <button type="button" onClick={() => togglePanel("entity")}><Plus size={13} /> Entity</button>
                  <button type="button" disabled={entities.length < 2} onClick={() => togglePanel("statement")}><Plus size={13} /> 관계</button>
                </div>
              </div>

              {createPanel === "source" && <form className="knowledge-inline-form" onSubmit={createSource}><label>원문 제목<input autoFocus value={sourceTitle} maxLength={500} onChange={(event) => setSourceTitle(event.target.value)} /></label><label className="is-wide">원문<textarea value={sourceText} rows={4} maxLength={2_000_000} placeholder="근거로 보존할 텍스트를 입력하세요." onChange={(event) => setSourceText(event.target.value)} /></label><button type="submit" disabled={saving || !sourceTitle.trim() || !sourceText.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 등록</button></form>}
              {createPanel === "entity" && <form className="knowledge-inline-form" onSubmit={createEntity}><label>Entity 이름<input autoFocus value={entityName} maxLength={500} onChange={(event) => setEntityName(event.target.value)} /></label><label>유형<input value={entityType} maxLength={80} placeholder="concept" onChange={(event) => setEntityType(event.target.value)} /></label><button type="submit" disabled={saving || !entityName.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 등록</button></form>}
              {createPanel === "statement" && <form className="knowledge-inline-form knowledge-statement-form" onSubmit={createStatement}><label>주체<SelectMenu size="small" value={subjectId} options={entityOptions} ariaLabel="관계 주체" onChange={(value) => { setSubjectId(value); if (value === objectId) setObjectId(""); }} /></label><label>관계<input value={predicate} maxLength={160} onChange={(event) => setPredicate(event.target.value)} /></label><label>대상<SelectMenu size="small" value={objectId} options={objectEntityOptions} ariaLabel="관계 대상" onChange={setObjectId} /></label><label className="is-wide">근거<SelectMenu size="small" value={evidenceId} options={evidenceMenuOptions} ariaLabel="관계 근거" onChange={setEvidenceId} /></label><button type="submit" disabled={saving || !subjectId || !objectId || !predicate.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 저장</button></form>}

              {loadingContent ? <div className="knowledge-loading"><LoaderCircle className="is-running" size={18} /> 지식을 불러오는 중</div> : tab === "graph" ? (
                <KnowledgeGraph neighborhood={neighborhood} entities={entities} selectedEntityId={selectedEntityId} onSelectEntity={setSelectedEntityId} />
              ) : (
                <KnowledgeRecords
                  sources={sources}
                  ingestions={ingestions}
                  statements={statements}
                  entityById={entityById}
                  startingSourceId={startingSourceId}
                  onStartIngestion={startIngestion}
                />
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function KnowledgeGraph({ neighborhood, entities, selectedEntityId, onSelectEntity }: { neighborhood: KnowledgeNeighborhood | null; entities: KnowledgeEntity[]; selectedEntityId: string | null; onSelectEntity: (entityId: string) => void }) {
  const nodes = neighborhood?.nodes ?? [];
  const positions = useMemo(() => new Map(nodes.map((node, index) => {
    const angle = nodes.length <= 1 ? 0 : (Math.PI * 2 * index) / nodes.length - Math.PI / 2;
    return [node.id, { x: 360 + Math.cos(angle) * 225, y: 210 + Math.sin(angle) * 135 }];
  })), [nodes]);
  if (!entities.length) return <div className="knowledge-empty"><CircleDot size={24} /><h3>Entity를 먼저 등록해 주세요.</h3><p>Entity 두 개 이상을 관계로 연결하면 Knowledge Graph가 만들어집니다.</p></div>;
  return <div className="knowledge-graph-layout"><aside className="knowledge-entity-list"><strong>Entity</strong>{entities.map((entity) => <button className={selectedEntityId === entity.id ? "is-active" : ""} type="button" key={entity.id} onClick={() => onSelectEntity(entity.id)}><CircleDot size={13} /><span>{entity.canonicalName}</span><small>{entity.entityType}</small></button>)}</aside><div className="knowledge-graph-scroll"><div className="knowledge-graph-canvas"><svg aria-hidden="true">{(neighborhood?.edges ?? []).map((edge) => { const source = positions.get(edge.subjectEntityId); const target = edge.objectEntityId ? positions.get(edge.objectEntityId) : null; return source && target ? <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} /> : null; })}</svg>{nodes.map((node) => { const position = positions.get(node.id)!; return <button className={node.id === neighborhood?.rootEntityId ? "is-root" : ""} style={{ left: position.x, top: position.y }} type="button" key={node.id} onClick={() => onSelectEntity(node.id)}><strong>{node.canonicalName}</strong><small>{node.entityType} · {node.depth ?? 0} hop</small></button>; })}{neighborhood?.truncated && <span className="knowledge-truncated">표시 한도에 맞춰 일부 관계만 보여줍니다.</span>}</div></div></div>;
}

function KnowledgeRecords({ sources, ingestions, statements, entityById, startingSourceId, onStartIngestion }: {
  sources: KnowledgeSource[];
  ingestions: KnowledgeIngestionJob[];
  statements: KnowledgeStatement[];
  entityById: Map<string, KnowledgeEntity>;
  startingSourceId: string | null;
  onStartIngestion: (sourceId: string) => void;
}) {
  const latestBySource = new Map<string, KnowledgeIngestionJob>();
  for (const job of ingestions) {
    if (!latestBySource.has(job.sourceId)) latestBySource.set(job.sourceId, job);
  }
  return (
    <div className="knowledge-records">
      <section>
        <header><FileText size={15} /><strong>원문</strong><span>{sources.length}</span></header>
        {sources.length ? sources.map((source) => {
          const job = latestBySource.get(source.id);
          const active = job?.status === "queued" || job?.status === "running";
          return (
            <article key={source.id}>
              <div><strong>{source.title}</strong><small>{source.sourceType} · revision {source.revision.revisionNumber}</small></div>
              <p>{source.evidenceSegments[0]?.text ?? "보존된 텍스트가 없습니다."}</p>
              <div className="knowledge-source-actions">
                <span>{source.evidenceSegments.length}개 근거 구간</span>
                {job && <small className={`is-${job.status}`} role="status">{ingestionLabel(job)}</small>}
                <button
                  type="button"
                  disabled={active || job?.status === "completed" || startingSourceId !== null}
                  onClick={() => onStartIngestion(source.id)}
                >
                  {(active || startingSourceId === source.id) && <RefreshCw className="is-running" size={12} />}
                  {job?.status === "completed" ? "추출 완료" : job?.status === "failed" ? "다시 추출" : active ? "AI 추출 중" : "AI 추출"}
                </button>
              </div>
            </article>
          );
        }) : <p className="knowledge-section-empty">등록된 원문이 없습니다.</p>}
      </section>
      <section>
        <header><GitBranch size={15} /><strong>Statement</strong><span>{statements.length}</span></header>
        {statements.length ? statements.map((statement) => (
          <article key={statement.id}>
            <div><strong>{entityById.get(statement.subjectEntityId)?.canonicalName ?? "Unknown"} <em>{statement.predicateKey}</em> {statement.objectEntityId ? entityById.get(statement.objectEntityId)?.canonicalName ?? "Unknown" : String(statement.objectValue)}</strong><small>revision {statement.revisionNumber ?? "-"} · {statement.status === "approved" ? "승인" : "검토 제안"}</small></div>
            <span>{statement.evidenceSegmentIds.length ? `${statement.evidenceSegmentIds.length}개 근거` : "근거 없음"}</span>
          </article>
        )) : <p className="knowledge-section-empty">등록된 Statement가 없습니다.</p>}
      </section>
    </div>
  );
}

function ingestionLabel(job: KnowledgeIngestionJob) {
  if (job.status === "queued") return "추출 대기";
  if (job.status === "running") return "근거 기반 추출 중";
  if (job.status === "failed") return job.errorMessage ?? "추출 실패";
  return `${job.entityCount}개 Entity · ${job.statementCount}개 검토 제안`;
}

function KnowledgeEmpty() {
  return <div className="knowledge-empty"><BookOpenText size={25} /><h3>Knowledge Space를 선택해 주세요.</h3><p>개인 공간의 원문, Entity와 관계는 계정 단위로 격리됩니다.</p></div>;
}
