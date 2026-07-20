import {
  AlertTriangle,
  ArrowLeft,
  BookOpenText,
  Check,
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
  Tags,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type FormEvent, type SetStateAction } from "react";
import { api, ApiError } from "../../api";
import type { KnowledgeDocument, KnowledgeDocumentSummary, KnowledgeGraphResponse, KnowledgeSpace, KnowledgeTag, ProjectSummary } from "../../api-types";
import { createClientId } from "../../client-id";
import { MarkdownResponse } from "../../components/ConversationTurn";
import { SelectMenu } from "../../components/SelectMenu";
import { KnowledgeGraph } from "./KnowledgeGraph";
import "./knowledge.css";

type KnowledgeTab = "home" | "explore" | "sources" | "wiki" | "graph" | "review" | "settings";
const emptyGraph: KnowledgeGraphResponse = { nodes: [], edges: [], truncated: false };
const knowledgeDocumentHistoryKey = "luminaKnowledgeDocument";
const tabs = [
  { id: "home", label: "홈", icon: Home },
  { id: "explore", label: "탐색", icon: FileSearch },
  { id: "wiki", label: "문서", icon: BookOpenText },
  { id: "review", label: "태그 관리", icon: Tags },
  { id: "settings", label: "설정", icon: Settings },
] as const;
const documentViews = [
  { id: "graph", label: "그래프" },
  { id: "wiki", label: "문서" },
  { id: "sources", label: "참조" },
] as const;
type KnowledgeDocumentView = typeof documentViews[number]["id"];
const isDocumentView = (tab: KnowledgeTab): tab is KnowledgeDocumentView => documentViews.some(({ id }) => id === tab);
const tagNamespaces = [
  { value: "purpose", label: "연구 목적" },
  { value: "company", label: "대상 기업" },
  { value: "industry", label: "산업" },
  { value: "topic", label: "주제" },
  { value: "technology", label: "기술" },
  { value: "region", label: "지역" },
  { value: "metric", label: "지표" },
  { value: "product", label: "제품" },
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
  const [searchedDocuments, setSearchedDocuments] = useState<KnowledgeDocumentSummary[] | null>(null);
  const [tags, setTags] = useState<KnowledgeTag[]>([]);
  const [tagLoadError, setTagLoadError] = useState<string | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<KnowledgeDocument | null>(null);
  const [selectedGraphNodeId, setSelectedGraphNodeId] = useState<string | null>(null);
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
    setSearchedDocuments(null);
    setQuery("");
  }, [selectedSpaceId]);

  useEffect(() => {
    if (!selectedSpaceId) {
      setDocuments([]);
      setTags([]);
      setTagLoadError(null);
      setSelectedDocument(null);
      setSelectedGraphNodeId(null);
      setGraph(emptyGraph);
      return;
    }
    const controller = new AbortController();
    setLoadingContent(true);
    setError(null);
    const tagsRequest = api.knowledge.listTags(selectedSpaceId, controller.signal)
      .then((loadedTags) => ({ loadedTags, tagError: null }))
      .catch(() => ({ loadedTags: [] as KnowledgeTag[], tagError: "태그 관리 데이터를 불러오지 못했습니다. Lumina를 다시 시작해 주세요." }));
    Promise.all([
      api.knowledge.listDocuments({ spaceId: selectedSpaceId, limit: 200 }, controller.signal),
      api.knowledge.getGraph(selectedSpaceId, controller.signal),
      tagsRequest,
    ]).then(([loadedDocuments, loadedGraph, tagResult]) => {
      if (controller.signal.aborted) return;
      setDocuments(loadedDocuments);
      setGraph(loadedGraph);
      setTags(tagResult.loadedTags);
      setTagLoadError(tagResult.tagError);
      const nextId = loadedDocuments.some((item) => item.id === selectedDocument?.id)
        ? selectedDocument?.id
        : loadedDocuments[0]?.id;
      setSelectedGraphNodeId(nextId ?? null);
      if (nextId) void loadDocument(nextId); else setSelectedDocument(null);
    }).catch((loadError) => {
      if (!controller.signal.aborted) setError(errorMessage(loadError));
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingContent(false);
    });
    return () => controller.abort();
  }, [loadDocument, selectedSpaceId]);

  useEffect(() => {
    if (!selectedSpaceId || !query.trim()) {
      setSearchedDocuments(null);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      void api.knowledge.listDocuments(
        { spaceId: selectedSpaceId, query: query.trim(), limit: 500 },
        controller.signal,
      ).then(setSearchedDocuments).catch((loadError) => {
        if (!(loadError instanceof DOMException && loadError.name === "AbortError")) {
          setError(errorMessage(loadError));
        }
      });
    }, 180);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [query, selectedSpaceId]);

  const filteredDocuments = useMemo(() => {
    if (!query.trim()) return documents;
    return searchedDocuments ?? documents;
  }, [documents, query, searchedDocuments]);

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

  async function deleteDocument(document: KnowledgeDocumentSummary) {
    await api.knowledge.deleteDocument(document.id);
    const deletedTagIds = new Set(document.tags.map((tag) => tag.id));
    const remainingDocuments = documents.filter((item) => item.id !== document.id);
    setDocuments((current) => current
      .filter((item) => item.id !== document.id)
      .map((item) => item.tags.some((tag) => deletedTagIds.has(tag.id))
        ? { ...item, linkedDocumentCount: Math.max(0, item.linkedDocumentCount - 1) }
        : item));
    setTags((current) => current.map((tag) => deletedTagIds.has(tag.id)
      ? { ...tag, usageCount: Math.max(0, tag.usageCount - 1) }
      : tag));
    setGraph((current) => ({
      ...current,
      nodes: current.nodes.filter((node) => node.id !== document.id),
      edges: current.edges.filter((edge) => edge.sourceDocumentId !== document.id && edge.targetDocumentId !== document.id),
    }));
    const nextDocument = remainingDocuments[0] ?? null;
    if (selectedGraphNodeId === document.id) setSelectedGraphNodeId(nextDocument?.id ?? null);
    if (selectedDocument?.id === document.id) {
      setSelectedDocument(null);
      if (nextDocument && tab !== "graph") void loadDocument(nextDocument.id);
    }
  }

  function openDocument(documentId: string, nextTab: KnowledgeTab = "wiki", returnTab?: KnowledgeTab) {
    if (returnTab) {
      try {
        const entryId = createClientId();
        const currentState = window.history.state && typeof window.history.state === "object" ? window.history.state : {};
        window.history.pushState({ ...currentState, [knowledgeDocumentHistoryKey]: entryId }, "");
        documentHistoryEntryRef.current = entryId;
        documentReturnTabRef.current = returnTab;
      } catch {
        documentHistoryEntryRef.current = null;
        documentReturnTabRef.current = null;
      }
    }
    void loadDocument(documentId).then(() => setTab(nextTab));
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
        <span>참조와 근거를 보존하면서 문서와 Knowledge Graph를 함께 관리합니다.</span>
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
            <nav className="knowledge-toolbar" aria-label="지식 화면"><div role="tablist">{tabs.map(({ id, label, icon: Icon }) => {
              const active = tab === id || (id === "wiki" && isDocumentView(tab));
              return <button key={id} className={active ? "is-active" : ""} type="button" role="tab" aria-selected={active} onClick={() => setTab(id === "wiki" ? "graph" : id)}><Icon size={14} /> {label}</button>;
            })}</div></nav>
          </header>
          {loadingContent ? <div className="knowledge-loading knowledge-loading-content"><LoaderCircle className="is-running" size={18} /> 지식을 불러오는 중</div> : <KnowledgeContent tab={tab} documents={documents} filteredDocuments={filteredDocuments} selectedDocument={selectedDocument} selectedGraphNodeId={selectedGraphNodeId} graph={graph} tags={tags} tagLoadError={tagLoadError} query={query} citationCount={citationCount} space={selectedSpace} editingSpaceField={editingSpaceField} spaceEditValue={spaceEditValue} savingSpaceDetails={savingSpaceDetails} spaceEditError={spaceEditError} setTab={setTab} setQuery={setQuery} setSpaceEditValue={setSpaceEditValue} setTags={setTags} setSelectedGraphNodeId={setSelectedGraphNodeId} beginSpaceDetailsEdit={beginSpaceDetailsEdit} cancelSpaceDetailsEdit={cancelSpaceDetailsEdit} saveSpaceDetails={saveSpaceDetails} deleteDocument={deleteDocument} openDocument={openDocument} returnToGraph={returnToGraph} />}
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
  selectedGraphNodeId: string | null;
  graph: KnowledgeGraphResponse;
  tags: KnowledgeTag[];
  tagLoadError: string | null;
  query: string;
  citationCount: number;
  space: KnowledgeSpace;
  editingSpaceField: "name" | "purpose" | null;
  spaceEditValue: string;
  savingSpaceDetails: boolean;
  spaceEditError: string | null;
  setTab: (tab: KnowledgeTab) => void;
  setQuery: (value: string) => void;
  setSpaceEditValue: (value: string) => void;
  setTags: Dispatch<SetStateAction<KnowledgeTag[]>>;
  setSelectedGraphNodeId: (documentId: string) => void;
  beginSpaceDetailsEdit: (field: "name" | "purpose") => void;
  cancelSpaceDetailsEdit: () => void;
  saveSpaceDetails: (event: FormEvent<HTMLFormElement>) => void;
  deleteDocument: (document: KnowledgeDocumentSummary) => Promise<void>;
  openDocument: (documentId: string, tab?: KnowledgeTab, returnTab?: KnowledgeTab) => void;
  returnToGraph: () => void;
}

function KnowledgeContent(props: KnowledgeContentProps) {
  const { tab, documents, filteredDocuments, selectedDocument, selectedGraphNodeId, graph, tags, tagLoadError, query, citationCount, space, editingSpaceField, spaceEditValue, savingSpaceDetails, spaceEditError, setTab, setQuery, setSpaceEditValue, setTags, setSelectedGraphNodeId, beginSpaceDetailsEdit, cancelSpaceDetailsEdit, saveSpaceDetails, deleteDocument, openDocument, returnToGraph } = props;
  const switchDocumentView = (view: KnowledgeDocumentView) => {
    if (tab === "graph" && view !== "graph" && selectedGraphNodeId) {
      openDocument(selectedGraphNodeId, view, "graph");
      return;
    }
    setTab(view);
  };
  if (tab === "home") return <div className="knowledge-page knowledge-home">
    <section className="knowledge-hero-card"><div><small>DOCUMENT KNOWLEDGE</small><h3>답변은 문서로, 관계는 태그로</h3><p>AI 답변을 문서 단위로 저장하고 citation을 그대로 보존하며, 공통 태그를 통해 문서 사이의 연결을 탐색합니다.</p></div><div className="knowledge-hero-metrics" aria-label="지식 현황"><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "wiki")}><BookOpenText size={14} /><span><b>{documents.length}</b><small>문서</small></span></button><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "sources")}><FileText size={14} /><span><b>{citationCount}</b><small>참조</small></span></button><button type="button" onClick={() => setTab("review")}><Tags size={14} /><span><b>{tags.length}</b><small>태그</small></span></button><button type="button" onClick={() => documents[0] && openDocument(documents[0].id, "graph")}><GitBranch size={14} /><span><b>{graph.edges.length}</b><small>연결</small></span></button></div></section>
    <section className="knowledge-card"><header><div><strong>최근 문서</strong><small>최근 조사한 AI 답변 문서입니다.</small></div></header><DocumentRows documents={documents.slice(0, 6)} onOpen={openDocument} /></section>
  </div>;

  if (tab === "explore") return <div className="knowledge-page knowledge-explore"><label className="knowledge-search-box"><Search size={17} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="문서 제목, 본문 또는 태그 검색" /></label><p className="knowledge-search-caption">{filteredDocuments.length}개의 문서를 찾았습니다.</p><section className="knowledge-card"><DocumentRows documents={filteredDocuments} onOpen={openDocument} /></section></div>;

  if (isDocumentView(tab)) return <div className="knowledge-master-detail">
    <DocumentList documents={documents} selectedId={tab === "graph" ? selectedGraphNodeId : selectedDocument?.id ?? null} onOpen={(id) => tab === "graph" ? setSelectedGraphNodeId(id) : openDocument(id, tab)} onRead={tab === "graph" ? (id) => openDocument(id, "wiki", "graph") : undefined} onDelete={deleteDocument} label={`${documents.length}개 지식 문서`} activeView={tab} onViewChange={switchDocumentView} />
    {tab === "graph" && <section className="knowledge-graph-detail">{graph.truncated && <p className="knowledge-graph-limit-note">그래프는 최근 문서 200개를 표시합니다. 오래된 문서는 탐색 검색에서 찾을 수 있습니다.</p>}<KnowledgeGraph graph={graph} layoutKey={space.id} selectedNodeId={selectedGraphNodeId} onSelectDocument={(id) => openDocument(id, "wiki", "graph")} /></section>}
    {tab === "wiki" && <WikiDocument document={selectedDocument} onBackToGraph={returnToGraph} />}
    {tab === "sources" && <section className="knowledge-source-detail">{selectedDocument ? <><header><small>보존된 citation</small><h3>{selectedDocument.title}</h3><p>{selectedDocument.citations.length}개의 참조가 답변과 함께 저장되어 있습니다.</p></header><div className="knowledge-source-cards">{selectedDocument.citations.map((citation, index) => <a key={`${citation.sourceId}-${index}`} href={citation.url || undefined} target="_blank" rel="noreferrer"><span>[{citation.markerNumber ?? index + 1}]</span><strong>{citation.title}</strong><small>{citation.domain || citation.url || "참조 정보"}</small>{citation.excerpt && <p>{citation.excerpt}</p>}</a>)}{!selectedDocument.citations.length && <EmptyState text="이 문서에는 참조가 없습니다." />}</div></> : <EmptyState text="문서를 선택해 주세요." />}</section>}
  </div>;

  if (tab === "review") return <TagManagement space={space} tags={tags} loadError={tagLoadError} setTags={setTags} />;

  return <div className="knowledge-page knowledge-settings"><section className="knowledge-card"><header><div><strong>지식 그래프</strong><small>현재 지식 그래프의 저장 정책과 범위입니다.</small></div></header><dl><div><dt>이름</dt><dd>{editingSpaceField === "name" ? <form className="knowledge-settings-inline-form" onSubmit={saveSpaceDetails}><input autoFocus aria-label="지식 그래프 이름" maxLength={240} value={spaceEditValue} onChange={(event) => setSpaceEditValue(event.target.value)} /><button type="submit" aria-label="이름 저장" disabled={!spaceEditValue.trim() || savingSpaceDetails}>{savingSpaceDetails ? <LoaderCircle className="is-running" size={13} /> : <Check size={13} />}</button><button type="button" aria-label="이름 편집 취소" disabled={savingSpaceDetails} onClick={cancelSpaceDetailsEdit}><X size={13} /></button>{spaceEditError && <span role="alert">{spaceEditError}</span>}</form> : <button className="knowledge-settings-inline-value" type="button" aria-label={`${space.name} 이름 편집`} onClick={() => beginSpaceDetailsEdit("name")}><span>{space.name}</span><Pencil size={12} /></button>}</dd></div><div><dt>목적</dt><dd>{editingSpaceField === "purpose" ? <form className="knowledge-settings-inline-form" onSubmit={saveSpaceDetails}><input autoFocus aria-label="지식 그래프 설명" maxLength={10_000} value={spaceEditValue} placeholder="설정되지 않음" onChange={(event) => setSpaceEditValue(event.target.value)} /><button type="submit" aria-label="설명 저장" disabled={savingSpaceDetails}>{savingSpaceDetails ? <LoaderCircle className="is-running" size={13} /> : <Check size={13} />}</button><button type="button" aria-label="설명 편집 취소" disabled={savingSpaceDetails} onClick={cancelSpaceDetailsEdit}><X size={13} /></button>{spaceEditError && <span role="alert">{spaceEditError}</span>}</form> : <button className="knowledge-settings-inline-value" type="button" aria-label="지식 그래프 설명 편집" onClick={() => beginSpaceDetailsEdit("purpose")}><span>{space.purpose || "설정되지 않음"}</span><Pencil size={12} /></button>}</dd></div><div><dt>공개 범위</dt><dd>{space.visibility === "private" ? "개인 · 비공개" : "조직 공유"}</dd></div><div><dt>저장 단위</dt><dd>AI 답변 1개 = 지식 문서 1개</dd></div><div><dt>연결 규칙</dt><dd>Canonical 태그를 공유하는 문서끼리 연결</dd></div><div><dt>태그 정책</dt><dd>태그 사전에서 이름·정의·별칭과 계층을 직접 관리</dd></div></dl></section></div>;
}

type TagDraft = {
  namespace: string;
  name: string;
  definition: string;
  aliases: string;
  parentTagId: string;
};

function namespaceLabel(namespace: string) {
  return tagNamespaces.find((item) => item.value === namespace)?.label ?? namespace;
}

function namespaceExample(namespace: string) {
  return {
    purpose: "경쟁사 분석",
    company: "포스코",
    industry: "철강",
    topic: "탈탄소",
    technology: "수소환원제철",
    region: "북미",
    metric: "생산능력",
    product: "열연강판",
  }[namespace] ?? "새 태그";
}

function orderedTagRows(tags: KnowledgeTag[]) {
  const result: Array<{ tag: KnowledgeTag; depth: number }> = [];
  const namespaces = [...new Set(tags.map((tag) => tag.namespace))].sort((a, b) => {
    const aIndex = tagNamespaces.findIndex((item) => item.value === a);
    const bIndex = tagNamespaces.findIndex((item) => item.value === b);
    return (aIndex < 0 ? 99 : aIndex) - (bIndex < 0 ? 99 : bIndex) || a.localeCompare(b);
  });
  for (const namespace of namespaces) {
    const group = tags.filter((tag) => tag.namespace === namespace);
    const groupIds = new Set(group.map((tag) => tag.id));
    const children = new Map<string, KnowledgeTag[]>();
    for (const tag of group) {
      if (!tag.parentTagId || !groupIds.has(tag.parentTagId)) continue;
      children.set(tag.parentTagId, [...(children.get(tag.parentTagId) ?? []), tag]);
    }
    const visited = new Set<string>();
    const visit = (tag: KnowledgeTag, depth: number) => {
      if (visited.has(tag.id)) return;
      visited.add(tag.id);
      result.push({ tag, depth });
      for (const child of (children.get(tag.id) ?? []).sort((a, b) => a.name.localeCompare(b.name, "ko"))) visit(child, depth + 1);
    };
    for (const root of group.filter((tag) => !tag.parentTagId || !groupIds.has(tag.parentTagId)).sort((a, b) => a.name.localeCompare(b.name, "ko"))) visit(root, 0);
    for (const tag of group) visit(tag, 0);
  }
  return result;
}

function TagManagement({ space, tags, loadError, setTags }: { space: KnowledgeSpace; tags: KnowledgeTag[]; loadError: string | null; setTags: Dispatch<SetStateAction<KnowledgeTag[]>> }) {
  const [search, setSearch] = useState("");
  const [namespace, setNamespace] = useState("all");
  const [creating, setCreating] = useState(false);
  const [editingTagId, setEditingTagId] = useState<string | null>(null);
  const needle = search.trim().toLocaleLowerCase("ko-KR");
  const filteredTags = tags.filter((tag) => {
    if (namespace !== "all" && tag.namespace !== namespace) return false;
    if (!needle) return true;
    return `${tag.name} ${tag.definition} ${tag.aliases.join(" ")}`.toLocaleLowerCase("ko-KR").includes(needle);
  });
  const rows = orderedTagRows(filteredTags);
  const createNamespace = namespace === "all" ? "topic" : namespace;
  const availableNamespaces: Array<{ value: string; label: string }> = [...tagNamespaces];
  for (const value of new Set(tags.map((tag) => tag.namespace))) {
    if (!availableNamespaces.some((item) => item.value === value)) availableNamespaces.push({ value, label: value });
  }
  const upsertTag = (nextTag: KnowledgeTag) => setTags((current) => {
    const exists = current.some((tag) => tag.id === nextTag.id);
    return exists ? current.map((tag) => tag.id === nextTag.id ? nextTag : tag) : [...current, nextTag];
  });

  return <div className="knowledge-page knowledge-review">
    {loadError && <p className="knowledge-inline-error" role="alert">{loadError}</p>}
    <section className="knowledge-card knowledge-tag-card">
      <header className="knowledge-tag-card-header"><div><strong>태그 사전</strong><small>유형별로 이름, 정의, 별칭과 상위 개념을 관리합니다.</small></div><div><span>{tags.length}개 태그</span><button type="button" onClick={() => { setCreating(true); setEditingTagId(null); }}><Plus size={14} /> 새 태그</button></div></header>
      <div className="knowledge-tag-toolbar">
        <label><Search size={14} /><input value={search} placeholder="태그 이름, 정의 또는 별칭 검색" aria-label="태그 검색" onChange={(event) => setSearch(event.target.value)} /></label>
        <SelectMenu className="knowledge-tag-filter-select" menuClassName="knowledge-tag-select-menu" size="small" width="auto" value={namespace} options={[{ value: "all", label: "모든 유형" }, ...availableNamespaces]} ariaLabel="태그 유형 필터" onChange={(value) => { setNamespace(value); setCreating(false); setEditingTagId(null); }} />
      </div>
      {creating && <TagEditor key={`new-tag-${createNamespace}`} initialNamespace={createNamespace} tags={tags} onCancel={() => setCreating(false)} onSave={async (draft) => {
        const created = await api.knowledge.createTag({
          spaceId: space.id,
          namespace: draft.namespace,
          canonicalName: draft.name.trim(),
          definition: draft.definition.trim(),
          aliases: draft.aliases.split(",").map((value) => value.trim()).filter(Boolean),
          parentTagId: draft.parentTagId || null,
        });
        upsertTag(created);
        setCreating(false);
      }} />}
      <div className="knowledge-tag-registry">
        {rows.map(({ tag, depth }) => <div className="knowledge-tag-entry" key={tag.id}>
          <button type="button" className="knowledge-tag-management-row" style={{ paddingLeft: 13 + Math.min(depth, 4) * 18 }} aria-label={`${tag.name} 태그 편집`} onClick={() => { setEditingTagId(tag.id); setCreating(false); }}>
            <Tags size={16} /><div><span><strong>#{tag.name}</strong><small>{namespaceLabel(tag.namespace)}</small></span><p>{tag.definition || tag.scopeNote || "정의가 없습니다."}</p>{tag.aliases.length > 0 && <em>별칭 {tag.aliases.join(" · ")}</em>}</div><span className="knowledge-tag-usage">{tag.usageCount}개 문서</span><Pencil size={14} />
          </button>
          {editingTagId === tag.id && <TagEditor key={tag.id} tag={tag} tags={tags} onCancel={() => setEditingTagId(null)} onSave={async (draft) => {
            const updated = await api.knowledge.updateTag(tag.id, {
              expectedRevision: tag.revision,
              namespace: draft.namespace,
              canonicalName: draft.name.trim(),
              definition: draft.definition.trim(),
              aliases: draft.aliases.split(",").map((value) => value.trim()).filter(Boolean),
              parentTagId: draft.parentTagId || null,
            });
            upsertTag(updated);
            setEditingTagId(null);
          }} />}
        </div>)}
        {!rows.length && <EmptyState text={tags.length ? "조건에 맞는 태그가 없습니다." : "새 태그를 추가해 태그 사전을 시작하세요."} />}
      </div>
    </section>
  </div>;
}

function TagEditor({ tag, initialNamespace = "topic", tags, onSave, onCancel }: { tag?: KnowledgeTag; initialNamespace?: string; tags: KnowledgeTag[]; onSave: (draft: TagDraft) => Promise<void>; onCancel: () => void }) {
  const [draft, setDraft] = useState<TagDraft>({
    namespace: tag?.namespace ?? initialNamespace,
    name: tag?.name ?? "",
    definition: tag?.definition ?? "",
    aliases: tag?.aliases.join(", ") ?? "",
    parentTagId: tag?.parentTagId ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const parentOptions = tags.filter((candidate) => candidate.id !== tag?.id && candidate.namespace === draft.namespace);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft.name.trim() || saving) return;
    setSaving(true);
    setError(null);
    try { await onSave(draft); }
    catch (saveError) { setError(errorMessage(saveError)); }
    finally { setSaving(false); }
  };
  return <form className="knowledge-tag-editor" onSubmit={submit}>
    <div className="knowledge-tag-editor-grid">
      <div className="knowledge-tag-editor-field"><span>유형</span><SelectMenu className="knowledge-tag-editor-select" menuClassName="knowledge-tag-select-menu" size="small" width="fill" value={draft.namespace} options={[...tagNamespaces]} ariaLabel="태그 유형" onChange={(nextNamespace) => {
        setDraft((current) => ({ ...current, namespace: nextNamespace, parentTagId: tags.some((item) => item.id === current.parentTagId && item.namespace === nextNamespace) ? current.parentTagId : "" }));
      }} /></div>
      <label><span>태그 이름</span><input autoFocus value={draft.name} maxLength={160} placeholder={`예: ${namespaceExample(draft.namespace)}`} onChange={(event) => setDraft((current) => ({ ...current, name: event.target.value }))} /></label>
      <div className="knowledge-tag-editor-field"><span>상위 태그</span><SelectMenu className="knowledge-tag-editor-select" menuClassName="knowledge-tag-select-menu" size="small" width="fill" value={draft.parentTagId} options={[{ value: "", label: "최상위" }, ...parentOptions.map((item) => ({ value: item.id, label: `#${item.name}` }))]} ariaLabel="상위 태그" onChange={(parentTagId) => setDraft((current) => ({ ...current, parentTagId }))} /></div>
      <label className="is-wide"><span>정의</span><input value={draft.definition} maxLength={1_000} placeholder="이 태그를 사용하는 범위를 짧게 적어 주세요." onChange={(event) => setDraft((current) => ({ ...current, definition: event.target.value }))} /></label>
      <label className="is-wide"><span>별칭</span><input value={draft.aliases} placeholder="쉼표로 구분 · 예: POSCO, 포스코홀딩스" onChange={(event) => setDraft((current) => ({ ...current, aliases: event.target.value }))} /></label>
    </div>
    <footer><span>{error && <em role="alert">{error}</em>}</span><button type="button" disabled={saving} onClick={onCancel}>취소</button><button className="lumina-primary-action" type="submit" disabled={!draft.name.trim() || saving}>{saving && <LoaderCircle className="is-running" size={13} />}{tag ? "변경 저장" : "태그 추가"}</button></footer>
  </form>;
}

function DocumentRows({ documents, onOpen }: { documents: KnowledgeDocumentSummary[]; onOpen: (id: string, tab?: KnowledgeTab) => void }) {
  if (!documents.length) return <EmptyState text="저장된 문서가 없습니다. AI 답변 아래의 지식 그래프 저장 버튼으로 추가할 수 있습니다." />;
  return <div className="knowledge-document-rows">{documents.map((document) => <button key={document.id} type="button" onClick={() => onOpen(document.id, "wiki")}><BookOpenText size={14} /><span><strong>{document.title}</strong><small>{document.bodyPreview}</small></span><em>{researchedDate(document.researchedAt)}</em></button>)}</div>;
}

function DocumentList({ documents, selectedId, onOpen, onRead, onDelete, label, activeView, onViewChange }: { documents: KnowledgeDocumentSummary[]; selectedId: string | null; onOpen: (id: string) => void; onRead?: (id: string) => void; onDelete: (document: KnowledgeDocumentSummary) => Promise<void>; label: string; activeView: KnowledgeDocumentView; onViewChange: (view: KnowledgeDocumentView) => void }) {
  const [deleteArmedId, setDeleteArmedId] = useState<string | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<{ id: string; message: string } | null>(null);

  useEffect(() => {
    setDeleteArmedId(null);
    setDeleteError(null);
  }, [activeView, selectedId]);

  async function remove(document: KnowledgeDocumentSummary) {
    if (deleteArmedId !== document.id) {
      setDeleteArmedId(document.id);
      setDeleteError(null);
      return;
    }
    setDeleteBusyId(document.id);
    setDeleteError(null);
    try {
      await onDelete(document);
      setDeleteArmedId(null);
    } catch (deleteFailure) {
      setDeleteError({ id: document.id, message: errorMessage(deleteFailure) });
    } finally {
      setDeleteBusyId(null);
    }
  }

  return <aside className="knowledge-master-list"><header><strong>{label}</strong><div className="knowledge-document-view-toggle" role="tablist" aria-label="지식 문서 보기">{documentViews.map(({ id, label: viewLabel }) => <button key={id} className={activeView === id ? "is-active" : ""} type="button" role="tab" aria-selected={activeView === id} onClick={() => onViewChange(id)}>{viewLabel}</button>)}</div></header>{documents.map((document) => <div key={document.id} className={`knowledge-document-list-row ${document.id === selectedId ? "is-active" : ""}`}><button className="knowledge-document-open" type="button" onClick={() => { setDeleteArmedId(null); setDeleteError(null); onOpen(document.id); }} onDoubleClick={() => onRead?.(document.id)}><BookOpenText size={14} /><span><strong>{document.title}</strong><small>조사일 {researchedDate(document.researchedAt)}</small></span></button><div className="knowledge-document-row-actions"><em aria-label={`${document.linkedDocumentCount}개 문서와 연결`}>{document.linkedDocumentCount}</em><button className={`knowledge-document-delete tooltip-control ${deleteArmedId === document.id ? "is-delete-armed" : ""}`} type="button" aria-label={deleteArmedId === document.id ? `${document.title} 삭제 확인, 한 번 더 누르면 삭제` : `${document.title} 삭제`} data-tooltip={deleteArmedId === document.id ? "한 번 더 눌러 삭제" : "삭제"} disabled={deleteBusyId !== null} onClick={() => void remove(document)}>{deleteBusyId === document.id ? <LoaderCircle className="is-running" size={13} /> : deleteArmedId === document.id ? <AlertTriangle size={13} /> : <Trash2 size={13} />}</button></div>{deleteError?.id === document.id && <small className="knowledge-document-delete-error" role="alert">{deleteError.message}</small>}</div>)}</aside>;
}

function WikiDocument({ document, onBackToGraph }: { document: KnowledgeDocument | null; onBackToGraph: () => void }) {
  if (!document) return <EmptyState text="답변 하단의 지식 그래프 저장 버튼을 눌러 문서를 추가해 주세요." />;
  return <article className="knowledge-wiki-article"><header><div className="knowledge-wiki-navigation"><button type="button" onClick={onBackToGraph}><ArrowLeft size={13} /> 그래프로 돌아가기</button><span>지식 문서</span></div><h2>{document.title}</h2><p>{document.bodyPreview}</p><div className="knowledge-wiki-metrics"><span>조사일 {researchedDate(document.researchedAt)}</span><span>태그 {document.tags.length}</span><span>참조 {document.citations.length}</span></div><div className="knowledge-tag-row">{document.tags.map((tag) => <span key={tag.id}>#{tag.name}</span>)}</div></header><div className="knowledge-markdown conversation-response-typography"><MarkdownResponse text={document.body} /></div>{!!document.citations.length && <footer className="knowledge-citations">{document.citations.map((citation, index) => <a key={`${citation.sourceId}-${index}`} href={citation.url || undefined} target="_blank" rel="noreferrer">[{citation.markerNumber ?? index + 1}] {citation.title}</a>)}</footer>}</article>;
}

function EmptyState({ text }: { text: string }) { return <div className="knowledge-empty-state"><BookOpenText size={22} /><p>{text}</p></div>; }
