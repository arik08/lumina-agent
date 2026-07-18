import {
  BookOpenText,
  CircleDot,
  FileSearch,
  FileText,
  GitBranch,
  Home,
  LoaderCircle,
  Menu,
  Plus,
  Settings,
  ShieldCheck,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import { SelectMenu } from "../../components/SelectMenu";
import type {
  KnowledgeEntity,
  KnowledgeIngestionJob,
  KnowledgeNeighborhood,
  KnowledgePage,
  KnowledgeSource,
  KnowledgeSpace,
  KnowledgeStatement,
} from "../../api-types";
import { KnowledgeExplore } from "./KnowledgeExplore";
import { KnowledgeGraph } from "./KnowledgeGraph";
import { KnowledgeHome } from "./KnowledgeHome";
import { KnowledgeReview } from "./KnowledgeReview";
import { KnowledgeSettings } from "./KnowledgeSettings";
import { KnowledgeSources } from "./KnowledgeSources";
import { KnowledgeWiki } from "./KnowledgeWiki";
import "./knowledge.css";

export type KnowledgeTab = "home" | "explore" | "sources" | "wiki" | "graph" | "review" | "settings";
type CreatePanel = "space" | "source" | "entity" | "statement" | null;

interface KnowledgeViewProps {
  onOpenNavigation: () => void;
}

const tabs = [
  { id: "home", label: "홈", icon: Home },
  { id: "explore", label: "탐색", icon: FileSearch },
  { id: "sources", label: "원문", icon: FileText },
  { id: "wiki", label: "Wiki", icon: BookOpenText },
  { id: "graph", label: "그래프", icon: GitBranch },
  { id: "review", label: "검토", icon: ShieldCheck },
  { id: "settings", label: "설정", icon: Settings },
] as const;

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
  const [pages, setPages] = useState<KnowledgePage[]>([]);
  const [statements, setStatements] = useState<KnowledgeStatement[]>([]);
  const [neighborhood, setNeighborhood] = useState<KnowledgeNeighborhood | null>(null);
  const [selectedEntityId, setSelectedEntityId] = useState<string | null>(null);
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedEvidenceId, setSelectedEvidenceId] = useState<string | null>(null);
  const [tab, setTab] = useState<KnowledgeTab>("home");
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
  const [extractAfterCreate, setExtractAfterCreate] = useState(true);
  const [entityName, setEntityName] = useState("");
  const [entityType, setEntityType] = useState("concept");
  const [subjectId, setSubjectId] = useState("");
  const [predicate, setPredicate] = useState("RELATED_TO");
  const [objectId, setObjectId] = useState("");
  const [evidenceId, setEvidenceId] = useState("");

  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;
  const entityById = useMemo(() => new Map(entities.map((entity) => [entity.id, entity])), [entities]);
  const evidenceOptions = useMemo(
    () => sources.flatMap((source) => source.evidenceSegments.map((item) => ({
      id: item.id,
      label: `${source.title} · ${item.text.slice(0, 54)}`,
    }))),
    [sources],
  );
  const entityOptions = useMemo(
    () => [{ value: "", label: "선택" }, ...entities.map((entity) => ({ value: entity.id, label: entity.canonicalName }))],
    [entities],
  );
  const objectEntityOptions = useMemo(
    () => entityOptions.filter((option) => !option.value || option.value !== subjectId),
    [entityOptions, subjectId],
  );
  const evidenceMenuOptions = useMemo(
    () => [{ value: "", label: "없음 · 검토 제안으로 저장" }, ...evidenceOptions.map((item) => ({ value: item.id, label: item.label }))],
    [evidenceOptions],
  );
  const pendingCount = statements.filter((statement) => statement.status === "proposed").length;
  const handleSettingsError = useCallback((settingsError: unknown) => {
    setError(errorMessage(settingsError));
  }, []);

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
      setPages([]);
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
      api.knowledge.listPages(selectedSpaceId, controller.signal),
      api.knowledge.listStatements(selectedSpaceId, controller.signal),
    ])
      .then(([nextSources, nextIngestions, nextEntities, nextPages, nextStatements]) => {
        setSources(nextSources);
        setIngestions(nextIngestions);
        setEntities(nextEntities);
        setPages(nextPages);
        setStatements(nextStatements);
        setSelectedEntityId((current) => nextEntities.some((item) => item.id === current) ? current : (nextEntities[0]?.id ?? null));
        setSelectedSourceId((current) => nextSources.some((item) => item.id === current) ? current : (nextSources[0]?.id ?? null));
        setSelectedEvidenceId(null);
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
        api.knowledge.listPages(selectedSpaceId),
        api.knowledge.listStatements(selectedSpaceId),
      ])
        .then(([nextIngestions, nextEntities, nextPages, nextStatements]) => {
          if (disposed) return;
          setIngestions(nextIngestions);
          setEntities(nextEntities);
          setPages(nextPages);
          setStatements(nextStatements);
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
    if (!selectedEntityId || tab !== "graph") {
      if (!selectedEntityId) setNeighborhood(null);
      return;
    }
    const controller = new AbortController();
    api.knowledge.getNeighborhood(selectedEntityId, 2, controller.signal)
      .then(setNeighborhood)
      .catch((loadError) => {
        if (!controller.signal.aborted) setError(errorMessage(loadError));
      });
    return () => controller.abort();
  }, [selectedEntityId, statements, tab]);

  async function createSpace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceName.trim() || saving) return;
    setSaving(true);
    setError(null);
    try {
      const created = await api.knowledge.createSpace({ name: spaceName.trim(), purpose: spacePurpose.trim() });
      setSpaces((current) => [created, ...current]);
      setSelectedSpaceId(created.id);
      setSpaceName("");
      setSpacePurpose("");
      setCreatePanel(null);
      setTab("home");
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
        evidenceSegments: [{ text, locator: { section: "manual" }, language: "ko", tokenCount: Math.ceil(text.length / 3) }],
      });
      setSources((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      setSelectedSourceId(created.id);
      setSourceTitle("");
      setSourceText("");
      setCreatePanel(null);
      setTab("sources");
      if (extractAfterCreate) await startIngestion(created.id, selectedSpaceId);
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
      const nextPages = await api.knowledge.listPages(selectedSpaceId);
      setPages(nextPages);
      setSelectedEntityId(created.id);
      setEntityName("");
      setCreatePanel(null);
      setTab("wiki");
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSaving(false);
    }
  }

  async function startIngestion(sourceId: string, spaceId = selectedSpaceId) {
    if (!spaceId || startingSourceId) return;
    setStartingSourceId(sourceId);
    setError(null);
    try {
      const job = await api.knowledge.startIngestion(spaceId, sourceId);
      setIngestions((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setTab("sources");
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
      if (created.status === "approved") {
        setPages(await api.knowledge.listPages(selectedSpaceId));
      }
      setSelectedEntityId(subjectId);
      setObjectId("");
      setEvidenceId("");
      setCreatePanel(null);
      setTab(created.status === "approved" ? "wiki" : "review");
    } catch (createError) {
      setError(errorMessage(createError));
    } finally {
      setSaving(false);
    }
  }

  function openEntity(entityId: string, target: KnowledgeTab = "wiki") {
    setSelectedEntityId(entityId);
    setTab(target);
  }

  function openEvidence(evidenceSegmentId: string) {
    const source = sources.find((item) => item.evidenceSegments.some((evidence) => evidence.id === evidenceSegmentId));
    if (!source) return;
    setSelectedSourceId(source.id);
    setSelectedEvidenceId(evidenceSegmentId);
    setTab("sources");
  }

  async function updateReviewedStatement(originalId: string, reviewed: KnowledgeStatement) {
    setStatements((current) => [reviewed, ...current.filter((item) => item.id !== originalId)]);
    if (reviewed.status === "approved" && selectedSpaceId) {
      try {
        setPages(await api.knowledge.listPages(selectedSpaceId));
      } catch (refreshError) {
        setError(errorMessage(refreshError));
      }
    }
  }

  function updatePage(updated: KnowledgePage) {
    setPages((current) => current.map((page) => page.id === updated.id ? updated : page));
  }

  function updateSpace(updated: KnowledgeSpace) {
    setSpaces((current) => current.map((space) => space.id === updated.id ? updated : space));
  }

  function archiveSpace(spaceId: string) {
    const next = spaces.filter((space) => space.id !== spaceId);
    setSpaces(next);
    setSelectedSpaceId(next[0]?.id ?? null);
    setTab("home");
  }

  function togglePanel(panel: Exclude<CreatePanel, null>) {
    setCreatePanel((current) => current === panel ? null : panel);
  }

  let content = null;
  if (selectedSpace) {
    const shared = { sources, entities, statements, entityById };
    if (tab === "home") content = <KnowledgeHome {...shared} ingestions={ingestions} onChangeTab={setTab} onOpenEntity={openEntity} />;
    if (tab === "explore") content = <KnowledgeExplore {...shared} onOpenEntity={openEntity} onOpenEvidence={openEvidence} />;
    if (tab === "sources") content = <KnowledgeSources sources={sources} ingestions={ingestions} selectedSourceId={selectedSourceId} selectedEvidenceId={selectedEvidenceId} startingSourceId={startingSourceId} onSelectSource={setSelectedSourceId} onSelectEvidence={setSelectedEvidenceId} onStartIngestion={startIngestion} />;
    if (tab === "wiki") content = <KnowledgeWiki {...shared} pages={pages} selectedEntityId={selectedEntityId} onSelectEntity={setSelectedEntityId} onOpenEvidence={openEvidence} onPageUpdated={updatePage} onError={(wikiError) => setError(errorMessage(wikiError))} />;
    if (tab === "graph") content = <KnowledgeGraph neighborhood={neighborhood} entities={entities} statements={statements} selectedEntityId={selectedEntityId} onSelectEntity={setSelectedEntityId} onOpenWiki={(id) => openEntity(id, "wiki")} />;
    if (tab === "review") content = <KnowledgeReview sources={sources} statements={statements} entityById={entityById} onOpenEvidence={openEvidence} onReviewed={updateReviewedStatement} onError={(reviewError) => setError(errorMessage(reviewError))} />;
    if (tab === "settings") content = <KnowledgeSettings key={selectedSpace.id} space={selectedSpace} ingestions={ingestions} onUpdated={updateSpace} onArchived={archiveSpace} onError={handleSettingsError} />;
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
                  <BookOpenText size={15} /><span><strong>{space.name}</strong><small>{space.purpose || "개인 지식 공간"}</small></span><em>개인</em>
                </button>
              ))}
            </div>
          ) : <div className="knowledge-list-empty"><p>아직 지식 공간이 없습니다.</p><button type="button" onClick={() => setCreatePanel("space")}><Plus size={14} /> 첫 공간 만들기</button></div>}
        </aside>

        <section className="knowledge-workspace">
          {!selectedSpace ? <KnowledgeEmpty /> : (
            <>
              <header className="knowledge-space-header">
                <div><small>개인 · 비공개 · revision {selectedSpace.settingsRevision}</small><h2>{selectedSpace.name}</h2><p>{selectedSpace.purpose || selectedSpace.description || "원문과 검증된 관계를 축적하는 계정 단위 공간입니다."}</p></div>
                <div className="knowledge-metrics" aria-label="지식 현황">
                  <span><b>{sources.length}</b> 원문</span><span><b>{entities.length}</b> Entity</span><span><b>{statements.filter((item) => item.status === "approved").length}</b> 승인</span><span className={pendingCount ? "has-pending" : ""}><b>{pendingCount}</b> 검토</span>
                </div>
              </header>
              <nav className="knowledge-toolbar" aria-label="지식 화면">
                <div role="tablist">
                  {tabs.map(({ id, label, icon: Icon }) => (
                    <button className={tab === id ? "is-active" : ""} type="button" role="tab" aria-selected={tab === id} key={id} onClick={() => setTab(id)}>
                      <Icon size={14} /> {label}{id === "review" && pendingCount > 0 ? <span>{pendingCount}</span> : null}
                    </button>
                  ))}
                </div>
                <div>
                  <button type="button" onClick={() => togglePanel("source")}><Plus size={13} /> 원문</button>
                  <button type="button" onClick={() => togglePanel("entity")}><Plus size={13} /> Entity</button>
                  <button type="button" disabled={entities.length < 2} onClick={() => togglePanel("statement")}><Plus size={13} /> 관계</button>
                </div>
              </nav>

              {createPanel === "source" && <form className="knowledge-inline-form knowledge-source-form" onSubmit={createSource}><label>원문 제목<input autoFocus value={sourceTitle} maxLength={500} onChange={(event) => setSourceTitle(event.target.value)} /></label><label className="is-wide">원문<textarea value={sourceText} rows={4} maxLength={2_000_000} placeholder="근거로 보존할 텍스트나 Markdown을 입력하세요." onChange={(event) => setSourceText(event.target.value)} /></label><label className="knowledge-checkbox"><input type="checkbox" checked={extractAfterCreate} onChange={(event) => setExtractAfterCreate(event.target.checked)} /> 등록 후 AI로 Entity와 Statement 추출</label><button type="submit" disabled={saving || !sourceTitle.trim() || !sourceText.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 등록</button><p>동일한 내용은 digest로 재사용하며, 한 번의 추출은 최대 40개 근거 구간·60,000자로 제한됩니다.</p></form>}
              {createPanel === "entity" && <form className="knowledge-inline-form" onSubmit={createEntity}><label>Entity 이름<input autoFocus value={entityName} maxLength={500} onChange={(event) => setEntityName(event.target.value)} /></label><label>유형<input value={entityType} maxLength={80} placeholder="concept" onChange={(event) => setEntityType(event.target.value)} /></label><button type="submit" disabled={saving || !entityName.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 등록</button></form>}
              {createPanel === "statement" && <form className="knowledge-inline-form knowledge-statement-form" onSubmit={createStatement}><label>주체<SelectMenu size="small" value={subjectId} options={entityOptions} ariaLabel="관계 주체" onChange={(value) => { setSubjectId(value); if (value === objectId) setObjectId(""); }} /></label><label>관계<input value={predicate} maxLength={160} onChange={(event) => setPredicate(event.target.value)} /></label><label>대상<SelectMenu size="small" value={objectId} options={objectEntityOptions} ariaLabel="관계 대상" onChange={setObjectId} /></label><label className="is-wide">근거<SelectMenu size="small" value={evidenceId} options={evidenceMenuOptions} ariaLabel="관계 근거" onChange={setEvidenceId} /></label><button type="submit" disabled={saving || !subjectId || !objectId || !predicate.trim()}>{saving && <LoaderCircle className="is-running" size={14} />} 저장</button></form>}

              {loadingContent ? <div className="knowledge-loading knowledge-loading-content"><LoaderCircle className="is-running" size={18} /> 지식을 불러오는 중</div> : content}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function KnowledgeEmpty() {
  return <div className="knowledge-empty"><CircleDot size={25} /><h3>Knowledge Space를 선택해 주세요.</h3><p>개인 공간의 원문, Entity와 관계는 계정 단위로 격리됩니다.</p></div>;
}
