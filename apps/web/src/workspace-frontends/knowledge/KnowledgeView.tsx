import {
  ArrowLeft,
  BookOpenText,
  Check,
  CheckCircle2,
  ChevronDown,
  FileSearch,
  FileText,
  Folder,
  GitBranch,
  Home,
  LoaderCircle,
  Pencil,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Tags,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { api, ApiError } from "../../api";
import type { KnowledgeDocument, KnowledgeDocumentSummary, KnowledgeGraphResponse, KnowledgeSpace, KnowledgeTag, ProjectSummary } from "../../api-types";
import { MarkdownResponse } from "../../components/ConversationTurn";
import { KnowledgeGraph } from "./KnowledgeGraph";
import "./knowledge.css";

type KnowledgeTab = "home" | "explore" | "sources" | "wiki" | "graph" | "review" | "settings";
const emptyGraph: KnowledgeGraphResponse = { nodes: [], edges: [], truncated: false };
const knowledgeDocumentHistoryKey = "luminaKnowledgeDocument";
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
  return error instanceof ApiError ? error.message : "지식 그래프를 불러오지 못했습니다.";
}

function researchedDate(value: string) {
  return new Intl.DateTimeFormat("ko-KR", { year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date(value));
}

export function KnowledgeView() {
  const [spaces, setSpaces] = useState<KnowledgeSpace[]>([]);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocumentSummary[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument | null>(null);
  const [graph, setGraph] = useState<KnowledgeGraphResponse>(emptyGraph);
  const [tab, setTab] = useState<KnowledgeTab>("home");
  const [query, setQuery] = useState("");
  const [loadingContent, setLoadingContent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showCreateSpace, setShowCreateSpace] = useState(false);
  const [spaceName, setSpaceName] = useState("");
  const [spacePurpose, setSpacePurpose] = useState("");
  const [savingSpace, setSavingSpace] = useState(false);
  const [openPicker, setOpenPicker] = useState<"graph" | "projects" | null>(null);
  const [projectDraft, setProjectDraft] = useState<Set<string>>(new Set());
  const [savingProjects, setSavingProjects] = useState(false);
  const [editingSpaceField, setEditingSpaceField] = useState<"name" | "purpose" | null>(null);
  const [spaceEditValue, setSpaceEditValue] = useState("");
  const [savingSpaceDetails, setSavingSpaceDetails] = useState(false);
  const [spaceEditError, setSpaceEditError] = useState<string | null>(null);
  const productActionsRef = useRef<HTMLDivElement>(null);
  const documentHistoryEntryRef = useRef<string | null>(null);
  const documentReturnTabRef = useRef<KnowledgeTab | null>(null);

  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? null;

  const loadDocument = useCallback(async (documentId: string) => {
    setError(null);
    try { setSelectedDocument(await api.knowledge.getDocument(documentId)); }
    catch (loadError) { setError(errorMessage(loadError)); }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.knowledge.listSpaces(controller.signal), api.projects.list(controller.signal)])
      .then(([items, projectItems]) => {
        setSpaces(items);
        setProjects(projectItems);
        setSelectedSpaceId((current) => items.some((item) => item.id === current) ? current : (items[0]?.id ?? null));
      })
      .catch((loadError) => { if (!controller.signal.aborted) setError(errorMessage(loadError)); });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!openPicker) return;
    const closeOnOutsidePointer = (event: PointerEvent) => {
      if (event.target instanceof Node && !productActionsRef.current?.contains(event.target)) setOpenPicker(null);
    };
    document.addEventListener("pointerdown", closeOnOutsidePointer);
    return () => document.removeEventListener("pointerdown", closeOnOutsidePointer);
  }, [openPicker]);

  useEffect(() => {
    const returnFromDocument = () => {
      const returnTab = documentReturnTabRef.current;
      if (!returnTab) return;
      documentHistoryEntryRef.current = null;
      documentReturnTabRef.current = null;
      setTab(returnTab);
    };
    window.addEventListener("popstate", returnFromDocument);
    return () => window.removeEventListener("popstate", returnFromDocument);
  }, []);

  useEffect(() => {
    setEditingSpaceField(null);
    setSpaceEditError(null);
  }, [selectedSpaceId]);

  useEffect(() => {
    if (!selectedSpaceId) {
      setDocuments([]);
      setSelectedDocument(null);
      setGraph(emptyGraph);
      return;
    }
    const controller = new AbortController();
    setLoadingContent(true);
    setError(null);
    Promise.all([
      api.knowledge.listDocuments({ spaceId: selectedSpaceId }, controller.signal),
      api.knowledge.getGraph(selectedSpaceId, controller.signal),
    ]).then(([loadedDocuments, loadedGraph]) => {
      if (controller.signal.aborted) return;
      setDocuments(loadedDocuments);
      setGraph(loadedGraph);
      const nextId = loadedDocuments.some((item) => item.id === selectedDocument?.id)
        ? selectedDocument?.id
        : loadedDocuments[0]?.id;
      if (nextId) void loadDocument(nextId); else setSelectedDocument(null);
    }).catch((loadError) => {
      if (!controller.signal.aborted) setError(errorMessage(loadError));
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingContent(false);
    });
    return () => controller.abort();
  }, [loadDocument, selectedSpaceId]);

  const filteredDocuments = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase("ko-KR");
    if (!needle) return documents;
    return documents.filter((document) => `${document.title} ${document.bodyPreview} ${document.tags.map((tag) => tag.name).join(" ")}`.toLocaleLowerCase("ko-KR").includes(needle));
  }, [documents, query]);

  const tags = useMemo(() => {
    const byId = new Map<string, KnowledgeTag & { count: number }>();
    for (const document of documents) for (const tag of document.tags) {
      const current = byId.get(tag.id);
      byId.set(tag.id, { ...tag, count: (current?.count ?? 0) + 1 });
    }
    return [...byId.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name, "ko"));
  }, [documents]);

  const citationCount = documents.reduce((sum, document) => sum + document.citationCount, 0);

  async function createSpace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!spaceName.trim() || savingSpace) return;
    setSavingSpace(true);
    setError(null);
    try {
      const created = await api.knowledge.createSpace({ name: spaceName.trim(), purpose: spacePurpose.trim() });
      setSpaces((current) => [created, ...current]);
      setSelectedSpaceId(created.id);
      setSpaceName("");
      setSpacePurpose("");
      setShowCreateSpace(false);
      setTab("home");
    } catch (createError) { setError(errorMessage(createError)); }
    finally { setSavingSpace(false); }
  }

  function openProjectPicker() {
    if (!selectedSpace) return;
    setProjectDraft(new Set(selectedSpace.projectIds));
    setOpenPicker((current) => current === "projects" ? null : "projects");
  }

  function toggleProject(projectId: string) {
    setProjectDraft((current) => {
      const next = new Set(current);
      if (next.has(projectId)) next.delete(projectId); else next.add(projectId);
      return next;
    });
  }

  async function saveProjectLinks() {
    if (!selectedSpace || savingProjects) return;
    setSavingProjects(true);
    setError(null);
    try {
      const updated = await api.knowledge.updateSpace(selectedSpace.id, {
        expectedRevision: selectedSpace.settingsRevision,
        projectIds: [...projectDraft],
      });
      setSpaces((current) => current.map((space) => space.id === updated.id ? updated : space));
      setOpenPicker(null);
    } catch (saveError) { setError(errorMessage(saveError)); }
    finally { setSavingProjects(false); }
  }

  function beginSpaceDetailsEdit(field: "name" | "purpose") {
    if (!selectedSpace) return;
    setSpaceEditValue(field === "name" ? selectedSpace.name : selectedSpace.purpose);
    setSpaceEditError(null);
    setEditingSpaceField(field);
  }

  function cancelSpaceDetailsEdit() {
    setEditingSpaceField(null);
    setSpaceEditError(null);
  }

  async function saveSpaceDetails(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSpace || !editingSpaceField || (editingSpaceField === "name" && !spaceEditValue.trim()) || savingSpaceDetails) return;
    setSavingSpaceDetails(true);
    setSpaceEditError(null);
    try {
      const updated = await api.knowledge.updateSpace(selectedSpace.id, {
        expectedRevision: selectedSpace.settingsRevision,
        [editingSpaceField]: spaceEditValue.trim(),
      });
      setSpaces((current) => current.map((space) => space.id === updated.id ? updated : space));
      setEditingSpaceField(null);
    } catch (saveError) { setSpaceEditError(errorMessage(saveError)); }
    finally { setSavingSpaceDetails(false); }
  }

  function openDocument(documentId: string, nextTab: KnowledgeTab = "wiki", returnTab?: KnowledgeTab) {
    if (returnTab) {
      const entryId = crypto.randomUUID();
      const currentState = window.history.state && typeof window.history.state === "object" ? window.history.state : {};
      window.history.pushState({ ...currentState, [knowledgeDocumentHistoryKey]: entryId }, "");
      documentHistoryEntryRef.current = entryId;
      documentReturnTabRef.current = returnTab;
    }
    setTab(nextTab);
    void loadDocument(documentId);
  }

  function returnToGraph() {
    const entryId = documentHistoryEntryRef.current;
    if (entryId && window.history.state?.[knowledgeDocumentHistoryKey] === entryId) {
      window.history.back();
      return;
    }
    documentHistoryEntryRef.current = null;
    documentReturnTabRef.current = null;
    setTab("graph");
  }

  return <main className="feature-view knowledge-view" aria-label="지식">
    <header className="feature-header knowledge-product-header">
      <div>
        <BookOpenText size={17} />
        <h1>지식 그래프</h1>
        <span>원문과 근거를 보존하면서 Wiki와 Knowledge Graph를 함께 관리합니다.</span>
      </div>
      <div className="knowledge-product-actions" ref={productActionsRef}>
        <div className="knowledge-picker-control">
          <button type="button" aria-haspopup="menu" aria-expanded={openPicker === "graph"} onClick={() => setOpenPicker((current) => current === "graph" ? null : "graph")}>{selectedSpace?.name ?? "그래프 선택"} <ChevronDown size={13} /></button>
          {openPicker === "graph" && <div className="knowledge-picker-menu knowledge-graph-picker" role="menu" aria-label="지식 그래프 선택">
            {spaces.map((space) => <button key={space.id} type="button" role="menuitemradio" aria-checked={space.id === selectedSpaceId} onClick={() => { setSelectedSpaceId(space.id); setOpenPicker(null); }}><BookOpenText size={14} /><span>{space.name}</span><Check size={13} /></button>)}
          </div>}
        </div>
        <div className="knowledge-picker-control">
          <button className="knowledge-project-picker-trigger" type="button" aria-haspopup="dialog" aria-expanded={openPicker === "projects"} disabled={!selectedSpace} onClick={openProjectPicker}><Folder size={14} /> 프로젝트 연결{selectedSpace?.projectIds.length ? ` ${selectedSpace.projectIds.length}` : ""} <ChevronDown size={13} /></button>
          {openPicker === "projects" && <div className="project-options knowledge-project-picker" role="listbox" aria-label="프로젝트 연결" aria-multiselectable="true">
            <div className="knowledge-project-option-list">{projects.length ? projects.map((project) => <button key={project.id} type="button" role="option" aria-selected={projectDraft.has(project.id)} onClick={(event) => { toggleProject(project.id); if (event.detail > 0) event.currentTarget.blur(); }}><span className="knowledge-project-checkbox" aria-hidden="true">{projectDraft.has(project.id) && <Check size={11} strokeWidth={2.5} />}</span><span className="knowledge-project-option-label">{project.name}</span></button>) : <p>연결할 수 있는 프로젝트가 없습니다.</p>}</div>
            <footer><span>{projectDraft.size}개 선택</span><button className="lumina-primary-action" type="button" disabled={savingProjects} onClick={() => void saveProjectLinks()}>{savingProjects && <LoaderCircle className="is-running" size={13} />} 저장</button></footer>
          </div>}
        </div>
        <button className="knowledge-create-button" type="button" onClick={() => setShowCreateSpace((current) => !current)}>{showCreateSpace ? <X size={15} /> : <Plus size={15} />}{showCreateSpace ? "닫기" : "새 지식 그래프"}</button>
      </div>
    </header>

    {error && <div className="knowledge-error" role="alert"><span>{error}</span><button type="button" onClick={() => setError(null)}><X size={14} /> 닫기</button></div>}
    {showCreateSpace && <form className="knowledge-space-form" onSubmit={createSpace}>
      <label>지식 그래프 이름<input autoFocus value={spaceName} maxLength={240} placeholder="예: 제품 설계 지식" onChange={(event) => setSpaceName(event.target.value)} /></label>
      <label>목적<input value={spacePurpose} maxLength={20_000} placeholder="이 지식 그래프에서 축적할 지식의 범위" onChange={(event) => setSpacePurpose(event.target.value)} /></label>
      <button type="submit" disabled={!spaceName.trim() || savingSpace}>{savingSpace && <LoaderCircle className="is-running" size={14} />} 만들기</button>
    </form>}

    <div className="knowledge-layout">
      <section className="knowledge-workspace">
        {selectedSpace ? <>
          <header className="knowledge-space-header">
            <nav className="knowledge-toolbar" aria-label="지식 화면"><div role="tablist">{tabs.map(({ id, label, icon: Icon }) => <button key={id} className={tab === id ? "is-active" : ""} type="button" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}><Icon size={14} /> {label}</button>)}</div></nav>
          </header>
          {loadingContent ? <div className="knowledge-loading knowledge-loading-content"><LoaderCircle className="is-running" size={18} /> 지식을 불러오는 중</div> : <KnowledgeContent tab={tab} documents={documents} filteredDocuments={filteredDocuments} selectedDocument={selectedDocument} graph={graph} tags={tags} query={query} citationCount={citationCount} space={selectedSpace} editingSpaceField={editingSpaceField} spaceEditValue={spaceEditValue} savingSpaceDetails={savingSpaceDetails} spaceEditError={spaceEditError} setQuery={setQuery} setSpaceEditValue={setSpaceEditValue} beginSpaceDetailsEdit={beginSpaceDetailsEdit} cancelSpaceDetailsEdit={cancelSpaceDetailsEdit} saveSpaceDetails={saveSpaceDetails} openDocument={openDocument} returnToGraph={returnToGraph} />}
        </> : <div className="knowledge-empty"><BookOpenText size={25} /><h3>새 지식 그래프를 만들어 주세요.</h3><p>저장한 AI 답변이 문서 단위로 이 그래프에 쌓입니다.</p></div>}
      </section>
    </div>
  </main>;
}

interface KnowledgeContentProps {
  tab: KnowledgeTab;
  documents: KnowledgeDocumentSummary[];
  filteredDocuments: KnowledgeDocumentSummary[];
  selectedDocument: KnowledgeDocument | null;
  graph: KnowledgeGraphResponse;
  tags: Array<KnowledgeTag & { count: number }>;
  query: string;
  citationCount: number;
  space: KnowledgeSpace;
  editingSpaceField: "name" | "purpose" | null;
  spaceEditValue: string;
  savingSpaceDetails: boolean;
  spaceEditError: string | null;
  setQuery: (value: string) => void;
  setSpaceEditValue: (value: string) => void;
  beginSpaceDetailsEdit: (field: "name" | "purpose") => void;
  cancelSpaceDetailsEdit: () => void;
  saveSpaceDetails: (event: FormEvent<HTMLFormElement>) => void;
  openDocument: (documentId: string, tab?: KnowledgeTab, returnTab?: KnowledgeTab) => void;
  returnToGraph: () => void;
}

function KnowledgeContent(props: KnowledgeContentProps) {
  const { tab, documents, filteredDocuments, selectedDocument, graph, tags, query, citationCount, space, editingSpaceField, spaceEditValue, savingSpaceDetails, spaceEditError, setQuery, setSpaceEditValue, beginSpaceDetailsEdit, cancelSpaceDetailsEdit, saveSpaceDetails, openDocument, returnToGraph } = props;
  if (tab === "home") return <div className="knowledge-page knowledge-home">
    <section className="knowledge-hero-card"><div><small>DOCUMENT KNOWLEDGE</small><h3>답변은 문서로, 관계는 태그로</h3><p>AI 답변을 문서 단위로 저장하고 citation을 그대로 보존하며, 공통 태그를 통해 문서 사이의 연결을 탐색합니다.</p></div><div className="knowledge-hero-metrics" aria-label="지식 현황"><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "wiki")}><BookOpenText size={14} /><span><b>{documents.length}</b><small>문서</small></span></button><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "sources")}><FileText size={14} /><span><b>{citationCount}</b><small>원문</small></span></button><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "review")}><Tags size={14} /><span><b>{tags.length}</b><small>태그</small></span></button><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "graph")}><GitBranch size={14} /><span><b>{graph.edges.length}</b><small>연결</small></span></button></div></section>
    <section className="knowledge-card"><header><div><strong>최근 문서</strong><small>최근 조사한 AI 답변 문서입니다.</small></div></header><DocumentRows documents={documents.slice(0, 6)} onOpen={openDocument} /></section>
  </div>;

  if (tab === "explore") return <div className="knowledge-page knowledge-explore"><label className="knowledge-search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="문서 제목, 본문 또는 태그 검색" /></label><p className="knowledge-search-caption">{filteredDocuments.length}개의 문서를 찾았습니다.</p><section className="knowledge-card"><DocumentRows documents={filteredDocuments} onOpen={openDocument} /></section></div>;

  if (tab === "sources") return <div className="knowledge-master-detail"><DocumentList documents={documents} selectedId={selectedDocument?.id ?? null} onOpen={(id) => openDocument(id, "sources")} label="원문이 포함된 문서" />
    <section className="knowledge-source-detail">{selectedDocument ? <><header><small>보존된 citation</small><h3>{selectedDocument.title}</h3><p>{selectedDocument.citations.length}개의 출처가 답변과 함께 저장되어 있습니다.</p></header><div className="knowledge-source-cards">{selectedDocument.citations.map((citation, index) => <a key={`${citation.sourceId}-${index}`} href={citation.url || undefined} target="_blank" rel="noreferrer"><span>[{citation.markerNumber ?? index + 1}]</span><strong>{citation.title}</strong><small>{citation.domain || citation.url || "출처 정보"}</small>{citation.excerpt && <p>{citation.excerpt}</p>}</a>)}{!selectedDocument.citations.length && <EmptyState text="이 문서에는 citation이 없습니다." />}</div></> : <EmptyState text="문서를 선택해 주세요." />}</section>
  </div>;

  if (tab === "wiki") return <div className="knowledge-master-detail"><DocumentList documents={documents} selectedId={selectedDocument?.id ?? null} onOpen={(id) => openDocument(id, "wiki")} label={`${documents.length}개 지식 문서`} /><WikiDocument document={selectedDocument} onBackToGraph={returnToGraph} /></div>;

  if (tab === "graph") return <KnowledgeGraph graph={graph} layoutKey={space.id} onSelectDocument={(id) => openDocument(id, "wiki", "graph")} />;

  if (tab === "review") return <div className="knowledge-page knowledge-review"><section className="knowledge-review-summary"><CheckCircle2 size={22} /><div><h3>승인 대기 지식이 없습니다.</h3><p>문서 본문은 그대로 저장되며, 이곳에서는 동의어·동음이의어로 의심되는 태그만 검토합니다.</p></div></section><section className="knowledge-card"><header><div><strong>Canonical 태그 사전</strong><small>현재 문서에서 사용 중인 정규화 태그입니다.</small></div><span>{tags.length}</span></header><div className="knowledge-tag-registry">{tags.map((tag) => <article key={tag.id}><Tags size={14} /><div><strong>#{tag.name}</strong><small>{tag.scopeNote || tag.namespace}</small></div><em>{tag.count}개 문서</em></article>)}{!tags.length && <EmptyState text="아직 생성된 태그가 없습니다." />}</div></section></div>;

  return <div className="knowledge-page knowledge-settings"><section className="knowledge-card"><header><div><strong>지식 그래프</strong><small>현재 지식 그래프의 저장 정책과 범위입니다.</small></div></header><dl><div><dt>이름</dt><dd>{editingSpaceField === "name" ? <form className="knowledge-settings-inline-form" onSubmit={saveSpaceDetails}><input autoFocus aria-label="지식 그래프 이름" maxLength={240} value={spaceEditValue} onChange={(event) => setSpaceEditValue(event.target.value)} /><button type="submit" aria-label="이름 저장" disabled={!spaceEditValue.trim() || savingSpaceDetails}>{savingSpaceDetails ? <LoaderCircle className="is-running" size={13} /> : <Check size={13} />}</button><button type="button" aria-label="이름 편집 취소" disabled={savingSpaceDetails} onClick={cancelSpaceDetailsEdit}><X size={13} /></button>{spaceEditError && <span role="alert">{spaceEditError}</span>}</form> : <button className="knowledge-settings-inline-value" type="button" aria-label={`${space.name} 이름 편집`} onClick={() => beginSpaceDetailsEdit("name")}><span>{space.name}</span><Pencil size={12} /></button>}</dd></div><div><dt>목적</dt><dd>{editingSpaceField === "purpose" ? <form className="knowledge-settings-inline-form" onSubmit={saveSpaceDetails}><input autoFocus aria-label="지식 그래프 설명" maxLength={10_000} value={spaceEditValue} placeholder="설정되지 않음" onChange={(event) => setSpaceEditValue(event.target.value)} /><button type="submit" aria-label="설명 저장" disabled={savingSpaceDetails}>{savingSpaceDetails ? <LoaderCircle className="is-running" size={13} /> : <Check size={13} />}</button><button type="button" aria-label="설명 편집 취소" disabled={savingSpaceDetails} onClick={cancelSpaceDetailsEdit}><X size={13} /></button>{spaceEditError && <span role="alert">{spaceEditError}</span>}</form> : <button className="knowledge-settings-inline-value" type="button" aria-label="지식 그래프 설명 편집" onClick={() => beginSpaceDetailsEdit("purpose")}><span>{space.purpose || "설정되지 않음"}</span><Pencil size={12} /></button>}</dd></div><div><dt>공개 범위</dt><dd>{space.visibility === "private" ? "개인 · 비공개" : "조직 공유"}</dd></div><div><dt>저장 단위</dt><dd>AI 답변 1개 = Wiki 문서 1개</dd></div><div><dt>연결 규칙</dt><dd>Canonical 태그를 공유하는 문서끼리 연결</dd></div><div><dt>검토 정책</dt><dd>본문 승인은 생략하고 태그 중복 후보만 검토</dd></div></dl></section></div>;
}

function DocumentRows({ documents, onOpen }: { documents: KnowledgeDocumentSummary[]; onOpen: (id: string, tab?: KnowledgeTab) => void }) {
  if (!documents.length) return <EmptyState text="저장된 문서가 없습니다. AI 답변 아래의 지식 그래프 저장 버튼으로 추가할 수 있습니다." />;
  return <div className="knowledge-document-rows">{documents.map((document) => <button key={document.id} type="button" onClick={() => onOpen(document.id, "wiki")}><BookOpenText size={14} /><span><strong>{document.title}</strong><small>{document.bodyPreview}</small></span><em>{researchedDate(document.researchedAt)}</em></button>)}</div>;
}

function DocumentList({ documents, selectedId, onOpen, label }: { documents: KnowledgeDocumentSummary[]; selectedId: string | null; onOpen: (id: string) => void; label: string }) {
  return <aside className="knowledge-master-list"><header><strong>{label}</strong></header>{documents.map((document) => <button key={document.id} className={document.id === selectedId ? "is-active" : ""} type="button" onClick={() => onOpen(document.id)}><BookOpenText size={14} /><span><strong>{document.title}</strong><small>조사일 {researchedDate(document.researchedAt)}</small></span><em>{document.citationCount}</em></button>)}</aside>;
}

function WikiDocument({ document, onBackToGraph }: { document: KnowledgeDocument | null; onBackToGraph: () => void }) {
  if (!document) return <EmptyState text="답변 하단의 지식 그래프 저장 버튼을 눌러 문서를 추가해 주세요." />;
  return <article className="knowledge-wiki-article"><header><div className="knowledge-wiki-navigation"><button type="button" onClick={onBackToGraph}><ArrowLeft size={13} /> 그래프로 돌아가기</button><span>Wiki › 문서</span></div><h2>{document.title}</h2><p>{document.bodyPreview}</p><div className="knowledge-wiki-metrics"><span>조사일 {researchedDate(document.researchedAt)}</span><span>태그 {document.tags.length}</span><span>citation {document.citations.length}</span></div><div className="knowledge-tag-row">{document.tags.map((tag) => <span key={tag.id}>#{tag.name}</span>)}</div></header><div className="knowledge-markdown"><MarkdownResponse text={document.body} /></div>{!!document.citations.length && <footer className="knowledge-citations">{document.citations.map((citation, index) => <a key={`${citation.sourceId}-${index}`} href={citation.url || undefined} target="_blank" rel="noreferrer">[{citation.markerNumber ?? index + 1}] {citation.title}</a>)}</footer>}</article>;
}

function EmptyState({ text }: { text: string }) { return <div className="knowledge-empty-state"><BookOpenText size={22} /><p>{text}</p></div>; }
