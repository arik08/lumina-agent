import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const viewPath = new URL(
  "../src/workspace-frontends/deep-analysis/DeepAnalysisView.tsx",
  import.meta.url,
);
const apiPath = new URL("../src/api.ts", import.meta.url);
const typesPath = new URL("../src/api-types.ts", import.meta.url);
const cssPath = new URL(
  "../src/workspace-frontends/deep-analysis/deep-analysis.css",
  import.meta.url,
);

test("deep analysis is an independent lazy Workspace view", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /lazy\(\(\) => import\("\.\/workspace-frontends\/deep-analysis"\)/);
  assert.match(app, /id: "deep-analysis", label: "심층분석"/);
  assert.match(app, /mainView === "deep-analysis" && <DeepAnalysisView/);
});

test("Mission creation and restoration use the typed deep-analysis API", async () => {
  const [view, api] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  assert.match(view, /api\.deepAnalysis\.createMission/);
  assert.match(view, /api\.deepAnalysis\s*\.listMissions/);
  assert.match(view, /api\.deepAnalysis\s*\.getMission/);
  assert.match(view, /lumina:deep-analysis:selected:/);
  assert.match(api, /\/projects\/\$\{encodeURIComponent\(projectId\)\}\/deep-analysis\/missions/);
  assert.match(api, /\/deep-analysis\/missions\/\$\{encodeURIComponent\(missionId\)\}/);
});

test("Mission switching keeps the last stable workspace until the next snapshot arrives", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.doesNotMatch(view, /useEffect\(\(\) => \{\s*setMission\(null\);[\s\S]*?if \(!projectId \|\| !selectedMissionId\) return;/);
  assert.match(view, /\.getMission\(selectedMissionId, controller\.signal\)[\s\S]*?\.then\(\(detail\) => \{[\s\S]*?setMission\(detail\)/);
  assert.match(view, /loadingMission && !hasCachedMission && !mission \? \(/);
  assert.match(view, /mission\.id !== selectedMissionId/);
});

test("cached tabs use the simplified two-tab contract", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /useCachedViewState<"workflow" \| "log">/);
  assert.match(view, /`deep-analysis:\$\{cacheScope\}:active-tab:v2`/);
  assert.match(view, /<header className="feature-header deep-analysis-header">[\s\S]*?<div className="feature-kind-tabs deep-analysis-view-tabs" role="tablist" aria-label="심층분석 화면">/);
  assert.match(view, /<GitBranch size=\{14\} \/> Workflow/);
  assert.match(view, /<History size=\{14\} \/> 실행 기록/);
  assert.doesNotMatch(view, /className="deep-analysis-tabs"/);
  assert.doesNotMatch(view, /결론·근거|Claim Ledger|Quality Gate|Open Issue/);
});

test("new Missions automatically create a workflow without preset controls", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /목표를 바탕으로 Node와 Edge를 한 번 자동 설계/);
  assert.match(view, /Workflow 자동 만들기/);
  assert.match(view, /autonomyMode: "balanced"/);
  assert.doesNotMatch(view, /preset_|listPatterns|savePattern|Pattern 저장/);
});

test("Canvas blank space supports pointer dragging", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /className=\{`deep-analysis-canvas-scroll/);
  assert.match(view, /onPointerDown=\{beginCanvasPan\}/);
  assert.match(view, /onPointerMove=\{moveCanvasPan\}/);
  assert.match(view, /onPointerUp=\{endCanvasPan\}/);
  assert.match(view, /viewport\.setPointerCapture\(event\.pointerId\)/);
  assert.match(view, /pan\.offsetX \+ event\.clientX - pan\.clientX/);
});

test("Canvas zoom value reserves enough width for triple-digit percentages", async () => {
  const [view, css] = await Promise.all([readFile(viewPath, "utf8"), readFile(cssPath, "utf8")]);

  assert.match(view, /className="deep-analysis-canvas-zoom-value"[^>]*aria-label="배율 초기화"/);
  assert.match(css, /\.deep-analysis-canvas-controls \.deep-analysis-canvas-zoom-value \{[^}]*width: 44px; min-width: 44px;[^}]*font-variant-numeric: tabular-nums;/);
});

test("Workflow editing supports Node movement and Edge connections", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /function beginNodeDrag/);
  assert.match(view, /function moveNodeDrag/);
  assert.match(view, /function beginConnectionDrag/);
  assert.match(view, /data-connection-input=\{node\.nodeKey\}/);
  assert.match(view, /api\.deepAnalysis\.updateDraft/);
  assert.match(view, /노드 편집/);
});

test("Workflow regeneration is a separate icon control with a prompt", async () => {
  const [view, api, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /className=\{workflowRegenerateOpen \? "deep-analysis-workflow-regenerate-trigger is-active"/);
  assert.match(view, /aria-label="workflow 재생성"/);
  assert.match(view, /data-tooltip="workflow 재생성"/);
  assert.match(view, /aria-label="workflow 재생성 프롬프트"/);
  assert.match(view, /api\.deepAnalysis\.regenerateWorkflow/);
  const regenerateControlIndex = view.indexOf('className="deep-analysis-workflow-regenerate-control"');
  const editControlsIndex = view.indexOf('className="deep-analysis-canvas-edit-controls"');
  assert.ok(regenerateControlIndex >= 0 && regenerateControlIndex < editControlsIndex);
  assert.match(view, /const width = Math\.min\(400, window\.innerWidth - 24\)/);
  assert.match(view, /"--conversation-font-size": workflowRegenerateFontSize/);
  assert.match(api, /\/workflow\/regenerate/);
  assert.match(css, /\.deep-analysis-workflow-regenerate-trigger \{[^}]*border: 1px solid var\(--line\)/);
  assert.match(css, /\.deep-analysis-workflow-regenerate-popover \{[^}]*width: min\(400px, calc\(100vw - 24px\)\)/);
  assert.match(css, /\.deep-analysis-workflow-regenerate-heading strong \{[^}]*font-size: calc\(var\(--conversation-font-size\) - 1px\)/);
  assert.match(css, /\.deep-analysis-workflow-regenerate-popover label \{[^}]*font-size: calc\(var\(--conversation-font-size\) - 1px\)/);
  assert.match(css, /\.deep-analysis-workflow-regenerate-popover textarea \{[^}]*font-size: calc\(var\(--conversation-font-size\) - 1px\)/);
  assert.match(css, /\.deep-analysis-workflow-regenerate-actions button \{[^}]*font-size: calc\(var\(--conversation-font-size\) - 1px\)/);
});

test("Node details expose the configured and actual execution prompts", async () => {
  const [view, types] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(typesPath, "utf8"),
  ]);

  assert.match(view, /<h3>작업 프롬프트<\/h3>/);
  assert.match(view, /프롬프트<textarea rows=\{6\} value=\{selectedNode\.purpose\}/);
  assert.match(view, /<h3>실행 프롬프트<\/h3>/);
  assert.match(view, /실제 입력 프롬프트 보기/);
  assert.match(view, /<pre>\{selectedNode\.executionPrompt\}<\/pre>/);
  assert.match(types, /conversationId: UUID \| null/);
  assert.match(types, /executionPrompt: string \| null/);
});

test("Node output is one rendered Markdown document with its filename", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /className="deep-analysis-output-path"/);
  assert.match(view, /className="deep-analysis-output-document"/);
  assert.match(view, /<MarkdownResponse text=\{selectedNode\.outputMarkdown\} \/>/);
  assert.doesNotMatch(view, /문서 전체 보기/);
});

test("Node inspector width is pointer and keyboard resizable and persisted", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /className="deep-analysis-inspector-resizer"/);
  assert.match(view, /role="separator"/);
  assert.match(view, /onPointerDown=\{beginInspectorResize\}/);
  assert.match(view, /onKeyDown=\{resizeInspectorWithKeyboard\}/);
  assert.match(view, /localStorage\.setItem\(inspectorWidthStorageKey/);
  assert.match(css, /--deep-analysis-inspector-width/);
  assert.match(css, /\.deep-analysis-inspector-resizer/);
});

test("Mission execution, retry, export, and deletion stay explicit", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /api\.deepAnalysis\.startMission/);
  assert.match(view, /api\.deepAnalysis\.retryMission/);
  assert.match(view, /api\.deepAnalysis\.createExport/);
  assert.match(view, /api\.deepAnalysis\.deleteMission\(mission\.id, mission\.revision\)/);
  assert.match(view, /deleteArmed \? "한 번 더 눌러 삭제"/);
});
