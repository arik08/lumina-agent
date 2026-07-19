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

test("Mission polling pauses offscreen and resumes immediately when visible", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /let refreshing = false;[\s\S]*?if \(refreshing\) return;[\s\S]*?finally \{\s*refreshing = false;/);
  assert.match(view, /const refreshWhenVisible = \(\) => \{\s*if \(document\.visibilityState === "visible"\) void refresh\(\);/);
  assert.match(view, /window\.setInterval\(refreshWhenVisible, 500\)/);
  assert.match(view, /document\.addEventListener\("visibilitychange", refreshWhenVisible\)/);
  assert.match(view, /document\.removeEventListener\("visibilitychange", refreshWhenVisible\)/);
});

test("cached tabs use the simplified two-tab contract", async () => {
  const [view, css] = await Promise.all([readFile(viewPath, "utf8"), readFile(cssPath, "utf8")]);

  assert.match(view, /useCachedViewState<"workflow" \| "log">/);
  assert.match(view, /`deep-analysis:\$\{cacheScope\}:active-tab:v2`/);
  assert.match(view, /<header className="feature-header deep-analysis-header">[\s\S]*?<div className="feature-kind-tabs deep-analysis-view-tabs" role="tablist" aria-label="심층분석 화면">/);
  assert.match(view, /<GitBranch size=\{14\} \/> Workflow/);
  assert.match(view, /<History size=\{14\} \/> 실행 기록/);
  assert.doesNotMatch(view, /className="deep-analysis-tabs"/);
  assert.match(css, /\.deep-analysis-view-tabs \{ display: inline-flex; flex: none; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button \{ white-space: nowrap; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button:first-child \{ width: 100px; min-width: 100px; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button:last-child \{ width: 92px; min-width: 92px; \}/);
  assert.doesNotMatch(view, /결론·근거|Claim Ledger|Quality Gate|Open Issue/);
});

test("new Missions automatically create a workflow without preset controls", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /목표를 바탕으로 Node와 Edge를 한 번 자동 설계/);
  assert.match(view, /Workflow 자동 만들기/);
  assert.match(view, /autonomyMode: "balanced"/);
  assert.doesNotMatch(view, /preset_|listPatterns|savePattern|Pattern 저장/);
});

test("new Mission setup exposes source references and execution controls", async () => {
  const [view, types, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(typesPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /aria-label="분석 자료 첨부"/);
  assert.match(view, /aria-label="기존 문서 연결"/);
  assert.match(view, /aria-label="Skill 및 MCP 연결"/);
  assert.match(view, /label="분석 범위"/);
  assert.match(view, /label="답변 분량"/);
  assert.match(view, /label="출력 방식"/);
  assert.match(view, /label="출력 토큰"/);
  assert.match(view, /api\.composer\.listSuggestions/);
  assert.match(view, /api\.projectFiles\.upload/);
  assert.match(view, /analysisDepth,[\s\S]*answerLength,[\s\S]*outputMode,[\s\S]*targetOutputTokens:[\s\S]*promptReferences:/);
  assert.match(types, /analysisDepth: "auto" \| "brief" \| "standard" \| "deep"/);
  assert.match(types, /promptReferences: PromptReference\[\]/);
  assert.match(css, /\.deep-analysis-create-toolbar/);
  assert.match(css, /\.deep-analysis-create-reference-menu/);
});

test("deep-analysis header prevents selection and native dragging across tabs", async () => {
  const css = await readFile(cssPath, "utf8");

  assert.match(
    css,
    /\.deep-analysis-header,\s*\.deep-analysis-header :where\(\*\) \{ user-select: none; -webkit-user-drag: none; \}/,
  );
});

test("Canvas blank space supports pointer dragging and refits without closing the inspector", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /className=\{`deep-analysis-canvas-scroll/);
  assert.match(view, /onPointerDown=\{beginCanvasPan\}/);
  assert.match(view, /onPointerMove=\{moveCanvasPan\}/);
  assert.match(view, /onPointerUp=\{endCanvasPan\}/);
  assert.match(view, /viewport\.setPointerCapture\(event\.pointerId\)/);
  assert.match(view, /pan\.offsetX \+ event\.clientX - pan\.clientX/);
  assert.match(view, /onDoubleClick=\{\(event\) => \{\s*if \(\(event\.target as Element\)\.closest\("button"\)\) return;\s*fitCanvasToViewport\(\);/);
  assert.doesNotMatch(view, /onDoubleClick=\{\(event\) => \{[^}]*closeInspectorAndFit\(\);/);
  assert.doesNotMatch(view, /aria-label="(?:Mission 정보|노드 상세) 닫기"/);
  assert.doesNotMatch(view, /function closeInspectorAndFit\(/);
});

test("Workflow Canvas keeps the Mission root before every start Node", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /const workflowMissionRoot = useMemo/);
  assert.match(view, /const startNodes = nodes\.filter\(\(node\) => !targetNodeKeys\.has\(node\.nodeKey\)\)/);
  assert.match(view, /workflowMissionRoot\?\.connectedNodes\.map/);
  assert.match(view, /className=\{`deep-analysis-goal-node deep-analysis-mission-root-node/);
  assert.match(view, /<span><Target size=\{14\} \/>MISSION<\/span>[\s\S]*?<strong>작업 흐름<\/strong>[\s\S]*?<small>AI 자동 설계<\/small>/);
  assert.match(view, /fitNodesToViewport\(\[[\s\S]*?workflowMissionRoot\.position[\s\S]*?shownWorkflow\?\.nodes/);
});

test("Mission root opens the existing analysis information and persists edits", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /className=\{`deep-analysis-goal-node deep-analysis-mission-root-node \$\{missionRootSelected \? "is-selected" : ""\}`\}/);
  assert.match(view, /aria-pressed=\{missionRootSelected\}/);
  assert.match(view, /setMissionTitleDraft\(mission\.title\)[\s\S]*?setMissionObjectiveDraft\(mission\.objective\)[\s\S]*?setMissionRootSelected\(true\)/);
  assert.match(view, /className="deep-analysis-inspector deep-analysis-create-inspector" aria-label="Mission 정보"/);
  assert.match(view, /분석 이름[\s\S]*?value=\{missionTitleDraft\}[\s\S]*?분석 목적[\s\S]*?value=\{missionObjectiveDraft\}/);
  assert.match(view, /api\.deepAnalysis\.updateMission\(mission\.id,[\s\S]*?title: nextTitle,[\s\S]*?objective: nextObjective/);
  assert.match(view, /Mission 정보 저장/);
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
  assert.match(view, /missionRootSelected && \([\s\S]*\{shownWorkflow\?\.reason && \([\s\S]*\{shownWorkflow\.reason\}/);
  assert.match(view, /<header>[\s\S]*\{shownWorkflow\?\.reason && \([\s\S]*\{shownWorkflow\.reason\}[\s\S]*<\/header>\s*<form className="deep-analysis-create"/);
  assert.doesNotMatch(view, /selectedNode\.config\.reason/);
  assert.match(types, /conversationId: UUID \| null/);
  assert.match(types, /executionPrompt: string \| null/);
});

test("Node output is one rendered Markdown document with its filename", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /className="deep-analysis-output-path"/);
  assert.match(view, /className=\{`deep-analysis-output-section \$\{selectedNode\.status === "running" \? "is-streaming" : ""\}`\}/);
  assert.match(view, /selectedNode\.status === "running" \? \(/);
  assert.doesNotMatch(view, /selectedNode\.status === "running" && !selectedNode\.outputSummary/);
  assert.match(view, /ref=\{liveOutputRef\} className="deep-analysis-live-output">\{displayLiveOutput\(selectedNode\.liveOutput\)\}/);
  assert.match(view, /return value\.replace\(\/\\\\r\\\\n\|\\\\n\|\\\\r\/g, "\\n"\)/);
  assert.match(view, /output\.scrollTop = output\.scrollHeight/);
  assert.match(view, /setInterval\(refreshWhenVisible, 500\)/);
  assert.match(view, /className="deep-analysis-output-document"/);
  assert.match(view, /<MarkdownResponse text=\{selectedNode\.outputMarkdown\} \/>/);
  assert.match(css, /\.deep-analysis-inspector > \.deep-analysis-output-section \{[^}]*display: flex;[^}]*flex-direction: column;[^}]*\}/);
  assert.match(css, /\.deep-analysis-inspector > \.deep-analysis-output-section\.is-streaming \{[^}]*flex: 1 1 0;[^}]*overflow: auto/);
  assert.match(css, /\.deep-analysis-live-output \{[^}]*min-height: 0;[^}]*flex: 1 1 0;[^}]*overflow: auto/);
  assert.doesNotMatch(view, /문서 전체 보기/);
});

test("Running and completed Nodes keep evenly spaced elapsed time below the title", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /if \(totalMinutes < 60\) return `\$\{totalMinutes\}분 \$\{totalSeconds % 60\}초`/);
  assert.doesNotMatch(view, /초째|분째/);
  assert.match(view, /node\.status === "completed" && node\.finishedAt/);
  assert.match(view, /Date\.parse\(normalizeUtcDateTime\(node\.finishedAt\)\)/);
  assert.match(view, /<span>\{statusLabel\(node\.status\)\}<\/span>/);
  assert.match(view, /<strong>\{node\.title\}<\/strong>\s*\{showCost[\s\S]*: elapsedTime && <time className="deep-analysis-node-elapsed"/);
  assert.match(css, /\.deep-analysis-node-meta > \.node-status \{[^}]*justify-self: end/);
  assert.match(css, /\.deep-analysis-node \{[^}]*height: 86px;[^}]*grid-auto-rows: 1\.2em;[^}]*align-content: center;[^}]*gap: 4px/);
  assert.match(css, /\.deep-analysis-view\.deep-analysis-view \.deep-analysis-node-meta > span,[\s\S]*\.deep-analysis-node > \.deep-analysis-node-elapsed,[\s\S]*\.deep-analysis-node > \.deep-analysis-node-cost \{ font-size: inherit; line-height: 1\.2; \}/);
});

test("Workflow connections only use top and bottom node ports", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /const workflowPortSides = \["north", "south"\] as const/);
  assert.doesNotMatch(view, /\["north", "east", "south", "west"\]/);
  assert.doesNotMatch(view, /return deltaX >= 0 \? \["east", "west"\]/);
  assert.doesNotMatch(css, /\.deep-analysis-connection-port\.port-(?:east|west)/);
});

test("Accumulated cost mode survives submenu dismissal and only the button restores elapsed time", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /className=\{`deep-analysis-cost tooltip-control \$\{costModeActive \? "is-active" : ""\}`\}/);
  assert.match(view, /aria-expanded=\{costDetailsOpen\}/);
  assert.match(view, /aria-pressed=\{costModeActive\}/);
  assert.match(view, /showCost=\{costModeActive\}/);
  assert.match(view, /const nextActive = !costModeActive;\s*setCostModeActive\(nextActive\);\s*setCostDetailsOpen\(nextActive\);/);
  assert.match(view, /document\.addEventListener\("pointerdown", closeCostDetailsOutside\)/);
  assert.match(view, /costDetailsRef\.current\?\.contains\(event\.target as Node\)/);
  assert.match(view, /document\.removeEventListener\("pointerdown", closeCostDetailsOutside\)/);
  assert.match(view, /<div ref=\{costDetailsRef\} className="deep-analysis-cost-wrap">/);
  assert.match(view, /showCost\s*\? <span className="deep-analysis-node-cost">\{formatCost\(node\.actualCostMicrousd, usdKrwRate\)\}<\/span>\s*:\s*elapsedTime && <time className="deep-analysis-node-elapsed"/);
  assert.match(css, /\.deep-analysis-cost\.is-active \{[^}]*border-color: var\(--cobalt\);[^}]*background: var\(--cobalt-pale\);[^}]*color: var\(--cobalt\);/);
  assert.match(css, /\.deep-analysis-node > \.deep-analysis-node-elapsed,[\s\S]*\.deep-analysis-node > \.deep-analysis-node-cost \{ font-size: inherit; line-height: 1\.2; \}/);
});

test("Active run feedback keeps only the completion count on the right", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /<span>\{completedNodeCount\}\/\{mission\.workflow\.nodes\.length\} Node 완료<\/span>/);
  assert.doesNotMatch(view, /실제 Lumina Run/);
  assert.doesNotMatch(view, /실행 Run을 준비하고 있습니다/);
  assert.match(css, /\.deep-analysis-run-feedback\.is-active > div \{[^}]*justify-content: space-between/);
  assert.match(css, /\.deep-analysis-run-feedback\.is-active span \{[^}]*text-align: right/);
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
  assert.match(view, /const maximumInspectorWidthRatio = 0\.84/);
  assert.match(view, /available \* maximumInspectorWidthRatio/);
  assert.doesNotMatch(view, /const maximumInspectorWidth = 1040/);
  assert.doesNotMatch(view, /available \* 0\.68/);
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
