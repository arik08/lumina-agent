import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/workspace-frontends/knowledge/KnowledgeView.tsx", import.meta.url);
const stylesPath = new URL("../src/workspace-frontends/knowledge/knowledge.css", import.meta.url);
const globalStylesPath = new URL("../src/styles.css", import.meta.url);
const apiPath = new URL("../src/api.ts", import.meta.url);
const typesPath = new URL("../src/api-types.ts", import.meta.url);
const turnPath = new URL("../src/components/ConversationTurn.tsx", import.meta.url);

test("Knowledge stores and displays one node per AI answer document", async () => {
  const [view, api, types] = await Promise.all([readFile(viewPath, "utf8"), readFile(apiPath, "utf8"), readFile(typesPath, "utf8")]);
  assert.match(view, /<h1>지식 그래프<\/h1>/);
  assert.match(view, /AI 답변을 문서 단위로 저장/);
  assert.match(view, /조사일/);
  assert.match(view, /<WikiDocument document=\{selectedDocument\}/);
  assert.match(view, /\{document\.body\}/);
  assert.match(view, /document\.citations\.map/);
  assert.match(api, /\/knowledge\/documents\/from-message/);
  assert.match(api, /\/knowledge\/graph/);
  assert.match(types, /interface KnowledgeDocument/);
  assert.doesNotMatch(types, /KnowledgeEntity|KnowledgeStatement|KnowledgeReviewDecision/);
});

test("Knowledge document rows show linked document counts and support inline deletion", async () => {
  const [view, api, types, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(typesPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);
  assert.match(types, /linkedDocumentCount: number/);
  assert.match(view, />\{document\.linkedDocumentCount\}<\/em>/);
  assert.doesNotMatch(view, />\{document\.citationCount\}<\/em>/);
  assert.match(api, /method: "DELETE"/);
  assert.match(view, /deleteArmedId !== document\.id/);
  assert.match(view, /한 번 더 눌러 삭제/);
  assert.match(styles, /\.knowledge-document-delete\.is-delete-armed/);
});

test("Knowledge Wiki reuses the default chat Markdown renderer", async () => {
  const [view, styles, globalStyles, turn] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(stylesPath, "utf8"),
    readFile(globalStylesPath, "utf8"),
    readFile(turnPath, "utf8"),
  ]);
  assert.match(view, /import \{ MarkdownResponse \} from "\.\.\/\.\.\/components\/ConversationTurn"/);
  assert.match(view, /<MarkdownResponse text=\{document\.body\} \/>/);
  assert.match(view, /className="knowledge-markdown conversation-response-typography"/);
  assert.doesNotMatch(view, /ReactMarkdown|remarkGfm/);
  assert.match(turn, /table: \(\{ children \}\) => <div className="markdown-table-scroll"><table>\{children\}<\/table><\/div>/);
  assert.doesNotMatch(styles, /\.knowledge-markdown (?:img|pre)/);
  assert.match(globalStyles, /\.conversation-response-typography \{ min-width: 0; font-family: inherit; font-size: var\(--conversation-font-size\); line-height: 1\.68; \}/);
  assert.match(globalStyles, /\.conversation-response-typography,\s*\.conversation-response-typography \*,\s*\.feature-view\.feature-view \.conversation-response-typography,\s*\.feature-view\.feature-view \.conversation-response-typography \* \{\s*font-size: var\(--conversation-font-size\);/);
  assert.match(styles, /\.knowledge-wiki-navigation button \{[^}]*border: 0;[^}]*background: transparent;[^}]*color: var\(--cobalt\);/);
});

test("Knowledge keeps the full workspace navigation around the document model", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);
  assert.doesNotMatch(view, /knowledge-mobile-menu|onOpenNavigation|knowledge-spaces|knowledge-pane-title|knowledge-space-list/);
  for (const label of ["홈", "탐색", "문서", "태그 관리", "설정"]) {
    assert.match(view, new RegExp(`label: "${label}"`));
  }
  assert.doesNotMatch(view.match(/const tabs = \[[\s\S]*?\] as const;/)?.[0] ?? "", /label: "(?:원문|Wiki|그래프)"/);
  assert.match(view, /새 지식 그래프/);
  assert.match(view, /참조와 근거를 보존하면서 문서와 Knowledge Graph를 함께 관리/);
  assert.match(view, />\{selectedSpace\?\.name \?\? "그래프 선택"\} /);
  assert.match(view, /프로젝트 연결/);
  assert.match(view, /className="project-options knowledge-project-picker" role="listbox"[^>]*aria-multiselectable="true"/);
  assert.match(view, /role="option" aria-selected=\{projectDraft\.has\(project\.id\)\}/);
  assert.match(view, /if \(event\.detail > 0\) event\.currentTarget\.blur\(\)/);
  assert.match(view, /className="knowledge-project-checkbox"[^>]*>\{projectDraft\.has\(project\.id\) && <Check size=\{11\}/);
  assert.doesNotMatch(view, /type="checkbox" checked=\{projectDraft\.has\(project\.id\)\}/);
  assert.match(styles, /\.knowledge-project-picker\.project-options \.knowledge-project-option-list > button \{[^}]*height: 32px;[^}]*gap: 9px;[^}]*padding: 0 8px;[^}]*font-size: 13px;/);
  assert.match(styles, /\.knowledge-project-picker\.project-options \.knowledge-project-option-list > button:hover \{[^}]*background: color-mix\(in srgb, var\(--ink\) 6%, var\(--menu-surface\)\)/);
  assert.match(styles, /\.knowledge-project-picker\.project-options \.knowledge-project-checkbox \{[^}]*width: 14px;[^}]*border: 1px solid var\(--line-strong\);/);
  assert.match(styles, /\[aria-selected="true"\] > \.knowledge-project-checkbox \{[^}]*background: var\(--surface\);[^}]*color: var\(--cobalt\);/);
  assert.match(styles, /\.knowledge-picker-control > \.knowledge-project-picker-trigger\[aria-expanded="true"\] \{[^}]*background: rgba\(63, 102, 201, 0\.075\);/);
  assert.match(view, /api\.knowledge\.updateSpace\(selectedSpace\.id/);
  assert.match(view, /projectIds: \[\.\.\.projectDraft\]/);
  assert.match(view, /<header className="knowledge-space-header">[\s\S]*?<nav className="knowledge-toolbar"/);
  assert.doesNotMatch(view, /knowledge-space-context/);
  assert.doesNotMatch(view, /<\/header>\s*<nav className="knowledge-toolbar"/);
  assert.match(styles, /\.knowledge-space-header \{[^}]*height: 39px;[^}]*min-height: 39px;/);
  assert.match(styles, /\.knowledge-toolbar button \{[^}]*height: 39px;/);
  assert.match(styles, /\.knowledge-space-header \{[^}]*padding: 0;/);
  assert.match(styles, /\.knowledge-toolbar \{[^}]*padding: 0 16px;/);
  assert.match(styles, /\.knowledge-toolbar button \{[^}]*padding: 0 8px;/);
  assert.doesNotMatch(styles, /\.knowledge-space-header \{[^}]*min-height: 54px;/);
  assert.match(view, /const documentViews = \[[\s\S]*?label: "그래프"[\s\S]*?label: "문서"[\s\S]*?label: "참조"/);
  assert.match(view, /onClick=\{\(\) => setTab\(id === "wiki" \? "graph" : id\)\}/);
  assert.match(view, /<DocumentList[\s\S]*?label=\{`\$\{documents\.length\}개 문서`\}[\s\S]*?activeView=\{tab\}/);
  assert.match(view, /className="knowledge-document-view-toggle" role="tablist" aria-label="지식 문서 보기"/);
  assert.match(styles, /\.knowledge-master-list > header \{[^}]*justify-content: space-between;/);
  assert.match(styles, /\.knowledge-document-view-toggle \{[^}]*border: 1px solid var\(--line\);[^}]*border-radius: var\(--radius-control\);/);
  assert.match(styles, /\.knowledge-document-view-toggle button\.is-active \{[^}]*background: var\(--surface\);[^}]*color: var\(--cobalt\);/);
  assert.match(view, /className="knowledge-settings-inline-value"[\s\S]*?이름 편집/);
  assert.match(view, /className="knowledge-settings-inline-value"[\s\S]*?지식 그래프 설명 편집/);
  assert.match(view, /editingSpaceField === "name"[\s\S]*?className="knowledge-settings-inline-form"/);
  assert.match(view, /editingSpaceField === "purpose"[\s\S]*?className="knowledge-settings-inline-form"/);
  assert.match(view, /api\.knowledge\.updateSpace\(selectedSpace\.id, \{[\s\S]*?\[editingSpaceField\]: spaceEditValue\.trim\(\)/);
  assert.doesNotMatch(view, /className="knowledge-metrics"/);
  assert.match(view, /className="knowledge-hero-metrics"/);
  assert.doesNotMatch(view, /className="knowledge-stat-grid"/);
  assert.doesNotMatch(view, /Wiki 열기/);
});

test("Knowledge document list sorts by research date, missing tags, or connected edges", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);
  assert.match(view, /\{ id: "researchedAt", label: "조사일 \(최근순\)" \}/);
  assert.match(view, /\{ id: "tagCount", label: "태그 개수 \(적은순\)" \}/);
  assert.match(view, /\{ id: "linkedDocumentCount", label: "엣지 연결 \(많은순\)" \}/);
  assert.match(view, /left\.tags\.length - right\.tags\.length \|\| researchedDifference/);
  assert.match(view, /right\.linkedDocumentCount - left\.linkedDocumentCount \|\| researchedDifference/);
  assert.match(view, /aria-label="정렬기준" aria-haspopup="menu" aria-expanded=\{sortMenuOpen\} data-tooltip="정렬기준"/);
  assert.match(view, /className="knowledge-document-view-toggle"[\s\S]*?<div className="knowledge-document-sort"/);
  assert.match(styles, /\.knowledge-document-sort-trigger \{[^}]*width: 28px;[^}]*height: 28px;/);
  assert.match(styles, /\.knowledge-document-sort-menu \{[^}]*position: absolute;[^}]*right: 0;/);
});

test("answer action places Knowledge save immediately before branch", async () => {
  const turn = await readFile(turnPath, "utf8");
  const savePosition = turn.indexOf('aria-label="지식 그래프 등록"');
  const branchPosition = turn.indexOf('data-tooltip="여기서 분기"');
  assert.ok(savePosition > 0 && branchPosition > savePosition);
  assert.match(turn, /saveKnowledgeDocumentFromMessage\(finalMessage\.id\)/);
});

test("Knowledge keeps batch tagging out of the graph workspace", async () => {
  const [view, api, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(apiPath, "utf8"), readFile(stylesPath, "utf8")]);
  assert.match(api, /\/knowledge\/documents\/tag-batch/);
  assert.doesNotMatch(view, /일괄 태깅 모델|미태깅 .*일괄 태깅|batchTagDocuments|taggingModels/);
  assert.doesNotMatch(styles, /knowledge-graph-tag-actions|knowledge-tagging-model/);
});

test("Knowledge tag management creates and edits typed hierarchical tags", async () => {
  const [view, api, featureApi, types, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(new URL("../src/feature-api.ts", import.meta.url), "utf8"),
    readFile(typesPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);
  assert.match(view, /label: "태그 관리"/);
  assert.match(view, /<strong>태그 사전<\/strong>/);
  assert.match(view, /> 새 태그<\/button>/);
  assert.match(view, /태그 이름, 정의 또는 별칭 검색/);
  assert.doesNotMatch(view, /승인 대기 태그가 없습니다/);
  assert.match(view, /initialNamespace=\{createNamespace\}/);
  assert.match(view, /company: "포스코"/);
  assert.match(view, /parentTagId: draft\.parentTagId \|\| null/);
  assert.match(view, /expectedRevision: tag\.revision/);
  assert.match(api, /\/knowledge\/tags/);
  assert.match(featureApi, /createTag: createKnowledgeTag/);
  assert.match(featureApi, /updateTag: updateKnowledgeTag/);
  assert.match(types, /interface KnowledgeTag extends KnowledgeDocumentTag/);
  assert.match(types, /definition: string/);
  assert.match(types, /parentTagId: UUID \| null/);
  assert.match(styles, /\.knowledge-tag-editor-grid/);
  assert.match(styles, /\.knowledge-review \{[^}]*display: flex;[^}]*overflow: hidden;/);
  assert.match(styles, /\.knowledge-tag-card \{[^}]*min-height: 0;[^}]*flex: 1;[^}]*overflow: hidden;/);
  assert.match(styles, /\.knowledge-tag-registry \{[^}]*min-height: 0;[^}]*overflow-y: auto;/);
  assert.match(styles, /\.knowledge-tag-management-row \{[^}]*border: 0;[^}]*background: transparent;/);
  assert.match(styles, /\.knowledge-tag-editor input \{[^}]*height: var\(--control-height-md\);[^}]*font-size: var\(--conversation-font-size\);/);
  assert.match(styles, /\.knowledge-tag-management-row strong \{[^}]*font-size: var\(--conversation-font-size\);/);
});

test("Knowledge keeps documents available when the optional tag-management API is stale", async () => {
  const view = await readFile(viewPath, "utf8");
  assert.match(view, /const tagsRequest = api\.knowledge\.listTags/);
  assert.match(view, /\.catch\(\(\) => \(\{ loadedTags: \[\] as KnowledgeTag\[\], tagError:/);
  assert.match(view, /Promise\.all\(\[[\s\S]*?listDocuments[\s\S]*?getGraph[\s\S]*?tagsRequest/);
  assert.match(view, /className="knowledge-inline-error" role="alert"/);
});

test("Knowledge document and graph views do not silently stop at 200 documents", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);
  assert.match(view, /listDocuments\(\{ spaceId: selectedSpaceId \}/);
  assert.match(view, /\{ spaceId: selectedSpaceId, query: query\.trim\(\) \}/);
  assert.doesNotMatch(view, /listDocuments\([^\n]*limit:\s*(?:200|500)/);
  assert.doesNotMatch(view, /graph\.truncated|최근 문서 200개/);
  assert.doesNotMatch(styles, /knowledge-graph-limit-note/);
});

test("Knowledge document tags keep their chip layout separate from tag-management rows", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);
  assert.match(view, /className="knowledge-tag-management-row"/);
  assert.match(view, /className="knowledge-tag-row">\{document\.tags\.map/);
  assert.match(styles, /\.knowledge-wiki-metrics, \.knowledge-tag-row \{ display: flex; flex-wrap: wrap; gap: 6px; \}/);
  assert.match(styles, /\.knowledge-tag-management-row \{ display: grid; width: 100%;/);
  assert.doesNotMatch(styles, /\.knowledge-tag-row \{ display: grid;/);
});

test("legacy approval, ingestion, and entity workspaces are absent", async () => {
  const [view, api] = await Promise.all([readFile(viewPath, "utf8"), readFile(apiPath, "utf8")]);
  assert.doesNotMatch(view, /KnowledgeReview|KnowledgeSources|KnowledgeWiki|KnowledgeEntity/);
  assert.doesNotMatch(api, /listKnowledgeEntities|listKnowledgeStatements|decideKnowledgeStatement|startKnowledgeIngestion/);
});
