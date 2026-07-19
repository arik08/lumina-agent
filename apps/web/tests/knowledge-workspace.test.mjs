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

test("Knowledge Wiki reuses the default chat Markdown renderer", async () => {
  const [view, styles, globalStyles, turn] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(stylesPath, "utf8"),
    readFile(globalStylesPath, "utf8"),
    readFile(turnPath, "utf8"),
  ]);
  assert.match(view, /import \{ MarkdownResponse \} from "\.\.\/\.\.\/components\/ConversationTurn"/);
  assert.match(view, /<MarkdownResponse text=\{document\.body\} \/>/);
  assert.doesNotMatch(view, /ReactMarkdown|remarkGfm/);
  assert.match(turn, /table: \(\{ children \}\) => <div className="markdown-table-scroll"><table>\{children\}<\/table><\/div>/);
  assert.doesNotMatch(styles, /\.knowledge-markdown (?:img|pre)/);
  assert.match(globalStyles, /\.assistant-content, \.feature-view\.feature-view \.knowledge-markdown \{ min-width: 0; font-size: calc\(var\(--conversation-font-size\) \+ \.5px\); line-height: 1\.68; \}/);
  assert.match(globalStyles, /\.chat-pane\.view-chat :is\(\.chat-header, \.conversation-scroll, \.dock-area\) \*,[\s\S]*?\.feature-view\.feature-view \.knowledge-markdown,[\s\S]*?\.feature-view\.feature-view \.knowledge-markdown \* \{[\s\S]*?font-size: var\(--conversation-font-size\);/);
  assert.match(styles, /\.knowledge-wiki-navigation button \{[^}]*border: 0;[^}]*background: transparent;[^}]*color: var\(--cobalt\);/);
});

test("Knowledge keeps the full workspace navigation around the document model", async () => {
  const [view, styles] = await Promise.all([readFile(viewPath, "utf8"), readFile(stylesPath, "utf8")]);
  assert.doesNotMatch(view, /knowledge-mobile-menu|onOpenNavigation|knowledge-spaces|knowledge-pane-title|knowledge-space-list/);
  for (const label of ["홈", "탐색", "문서", "검토", "설정"]) {
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
  assert.match(view, /<DocumentList[\s\S]*?label=\{`\$\{documents\.length\}개 지식 문서`\}[\s\S]*?activeView=\{tab\}/);
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

test("answer action places Knowledge save immediately before branch", async () => {
  const turn = await readFile(turnPath, "utf8");
  const savePosition = turn.indexOf('aria-label="지식 그래프 등록"');
  const branchPosition = turn.indexOf('data-tooltip="여기서 분기"');
  assert.ok(savePosition > 0 && branchPosition > savePosition);
  assert.match(turn, /api\.knowledge\.saveMessage\(finalMessage\.id\)/);
});

test("legacy approval, ingestion, and entity workspaces are absent", async () => {
  const [view, api] = await Promise.all([readFile(viewPath, "utf8"), readFile(apiPath, "utf8")]);
  assert.doesNotMatch(view, /KnowledgeReview|KnowledgeSources|KnowledgeWiki|KnowledgeEntity/);
  assert.doesNotMatch(api, /listKnowledgeEntities|listKnowledgeStatements|decideKnowledgeStatement|startKnowledgeIngestion/);
});
