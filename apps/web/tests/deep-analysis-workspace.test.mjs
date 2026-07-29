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
const eventStorePath = new URL(
  "../src/workspace-frontends/deep-analysis/mission-event-store.ts",
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

test("Mission event streaming coalesces refreshes and resumes immediately when visible", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /api\.deepAnalysis\.openEventStream\([\s\S]*?appendMissionEvent\(selectedMissionId, event\)/);
  assert.match(view, /const scheduleDetailRefresh = \(\) => \{[\s\S]*?window\.setTimeout\([\s\S]*?100\);/);
  assert.match(view, /if \(refreshing \|\| document\.visibilityState !== "visible"\) return;/);
  assert.match(view, /const refreshWhenVisible = \(\) => \{\s*if \(document\.visibilityState !== "visible"\) return;\s*void refreshDetail\(\);\s*void refreshProjection\(\);/);
  assert.match(view, /document\.addEventListener\("visibilitychange", refreshWhenVisible\)/);
  assert.match(view, /closeStream\(\)/);
  assert.match(view, /document\.removeEventListener\("visibilitychange", refreshWhenVisible\)/);
});

test("cached tabs use the simplified two-tab contract", async () => {
  const [view, css] = await Promise.all([readFile(viewPath, "utf8"), readFile(cssPath, "utf8")]);

  assert.match(view, /useCachedViewState<"workflow" \| "log">/);
  assert.match(view, /`deep-analysis:\$\{cacheScope\}:active-tab:v2`/);
  assert.match(view, /<header className="feature-header deep-analysis-header">[\s\S]*?<div className="feature-kind-tabs deep-analysis-view-tabs" role="tablist" aria-label="심층분석 화면">/);
  assert.match(view, /<GitBranch size=\{16\} \/> Workflow/);
  assert.match(view, /<History size=\{16\} \/> 실행 기록/);
  assert.doesNotMatch(view, /className="deep-analysis-tabs"/);
  assert.match(css, /\.deep-analysis-view-tabs \{ display: inline-flex; flex: none; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button \{ white-space: nowrap; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button > svg \{ flex: none; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button:first-child \{ width: 100px; min-width: 100px; \}/);
  assert.match(css, /\.deep-analysis-view-tabs > button:last-child \{ width: 92px; min-width: 92px; \}/);
  assert.doesNotMatch(view, /결론·근거|Claim Ledger|Quality Gate|Open Issue/);
});

test("execution log keeps only the latest output progress row for each Node", async () => {
  const [view, eventStore] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(eventStorePath, "utf8"),
  ]);

  assert.match(eventStore, /function compactMissionEvents\(events: DeepAnalysisMissionEvent\[\]\)/);
  assert.match(eventStore, /for \(let index = events\.length - 1; index >= 0; index -= 1\)/);
  assert.match(eventStore, /event\.type !== "node_output_delta"/);
  assert.match(eventStore, /event\.payload\.nodeKey \?\? event\.payload\.nodeId \?\? event\.payload\.runId/);
  assert.match(eventStore, /if \(seenOutputProgress\.has\(progressKey\)\) continue/);
  assert.match(view, /const visibleEvents = useMissionEvents\(missionId\)/);
  assert.match(view, /const newestEvents = useMemo\(\(\) => visibleEvents\.slice\(\)\.reverse\(\)/);
});

test("new Missions open an editable empty workflow without waiting for AI planning", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /void createManualMission\(\)/);
  assert.match(view, /workflowStartMode: "manual"/);
  assert.match(view, /title: "새 분석"/);
  assert.match(view, /detail\.startMode === "manual"[\s\S]*?detail\.workflow\.nodes\.length === 0/);
  assert.match(view, /api\.deepAnalysis\.createDraft\(detail\.id, detail\.revision\)/);
  assert.match(view, /setEditingWorkflow\(true\)/);
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
  assert.match(view, /from "\.\.\/\.\.\/components\/ComposerControls"/);
  assert.match(view, /<ComposerPicker[\s\S]*?ariaLabel="분석 범위 설정"/);
  assert.match(view, /<ComposerPicker[\s\S]*?ariaLabel="답변 분량 설정"/);
  assert.match(view, /<ArtifactLengthSlider[\s\S]*?outputMode=\{outputMode\}/);
  assert.match(view, /<ComposerPicker[\s\S]*?ariaLabel="모델 선택"[\s\S]*?controlClassName="model-control"/);
  assert.match(view, /<ComposerPicker[\s\S]*?ariaLabel="추론 노력도 설정"[\s\S]*?controlClassName="effort-control"/);
  assert.match(view, /execution: createExecution \?\? undefined/);
  assert.match(view, /className="composer-footer deep-analysis-create-toolbar"/);
  assert.match(view, /api\.composer\.listSuggestions/);
  assert.match(view, /api\.projectFiles\.upload/);
  assert.match(view, /analysisDepth,[\s\S]*answerLength,[\s\S]*outputMode,[\s\S]*targetOutputTokens:[\s\S]*execution:[\s\S]*promptReferences:/);
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

test("Workflow fitting keeps Nodes below the fixed canvas controls", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /ref=\{canvasControlsRef\} className="deep-analysis-canvas-controls"/);
  assert.match(view, /const controlsBottom = canvasControlsRef\.current[\s\S]*?getBoundingClientRect\(\)\.bottom - viewport\.getBoundingClientRect\(\)\.top/);
  assert.match(view, /const contentTop = Math\.max\(padding, controlsBottom \+ 12\)/);
  assert.match(view, /y: contentTop \+ Math\.max\(0, \(availableHeight - contentHeight \* fittedScale\) \/ 2\) - minY \* fittedScale/);
});

test("Workflow Canvas always keeps the Mission root before entry Nodes", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /const workflowMissionRoot = useMemo/);
  assert.match(view, /if \(!shownWorkflow\) return null/);
  assert.match(view, /const connectedNodes = nodes\.filter\(\(node\) => !targetNodeKeys\.has\(node\.nodeKey\)\)/);
  assert.match(view, /connectedNodes: \[\],[\s\S]*?position: \{ positionX: 272, positionY: 88 \}/);
  assert.match(view, /workflowMissionRoot\?\.connectedNodes\.map/);
  assert.match(view, /className=\{`deep-analysis-goal-node deep-analysis-mission-root-node/);
  assert.match(view, /mission\.startMode === "manual" \? "직접 구성" : "AI 자동 설계"/);
  assert.match(view, /fitNodesToViewport\(\[[\s\S]*?workflowMissionRoot\.position[\s\S]*?shownWorkflow\?\.nodes/);
});

test("newly added isolated Nodes keep their position and do not affect connected layout", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /const connectedNodeKeys = new Set<string>\(\)/);
  assert.match(view, /connectedNodeKeys\.add\(edge\.sourceNodeKey\)/);
  assert.match(view, /connectedNodeKeys\.add\(edge\.targetNodeKey\)/);
  assert.match(view, /if \(!connectedNodeKeys\.has\(node\.nodeKey\)\) continue/);
  assert.match(view, /if \(!connectedNodeKeys\.has\(node\.nodeKey\)\) return node/);
  assert.match(view, /setWorkflowDraft\(\{ \.\.\.workflowDraft, nodes: \[\.\.\.workflowDraft\.nodes, node\] \}\)/);
});

test("Mission root opens the existing analysis information and persists edits", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /className=\{`deep-analysis-goal-node deep-analysis-mission-root-node \$\{missionRootSelected \? "is-selected" : ""\}`\}/);
  assert.match(view, /aria-pressed=\{missionRootSelected\}/);
  assert.match(view, /setMissionTitleDraft\(mission\.title\)[\s\S]*?setMissionObjectiveDraft\(mission\.objective\)[\s\S]*?setMissionRootSelected\(true\)/);
  assert.match(view, /className="deep-analysis-inspector deep-analysis-create-inspector" aria-label="Mission 정보"/);
  assert.match(view, /분석 이름[\s\S]*?value=\{missionTitleDraft\}[\s\S]*?분석 목적[\s\S]*?value=\{missionObjectiveDraft\}/);
  assert.match(view, /aria-label="Mission 실행 설정"/);
  assert.match(view, /setAnalysisDepth\(mission\.analysisDepth\)[\s\S]*?setAnswerLength\(mission\.answerLength\)[\s\S]*?setOutputMode\(mission\.outputMode\)/);
  assert.match(view, /api\.deepAnalysis\.updateMission\(mission\.id,[\s\S]*?title: nextTitle,[\s\S]*?objective: nextObjective[\s\S]*?analysisDepth,[\s\S]*?answerLength,[\s\S]*?outputMode,[\s\S]*?targetOutputTokens:[\s\S]*?execution:[\s\S]*?promptReferences:/);
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
  assert.match(view, /aria-label="Node 추가"/);
  assert.match(view, /Node 유형<SelectMenu/);
  assert.match(view, /conversationId: null[\s\S]*?contextManifest: null/);
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
  const [view, types, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(typesPath, "utf8"),
    readFile(cssPath, "utf8"),
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
  assert.match(css, /\.deep-analysis-node-edit-field textarea \{[^}]*font-weight: 400/);
});

test("Mission settings own the final output format", async () => {
  const view = await readFile(viewPath, "utf8");
  const types = await readFile(typesPath, "utf8");

  assert.match(types, /export type DeepAnalysisOutputFormat = string/);
  assert.match(types, /outputFormat: DeepAnalysisOutputFormat/);
  assert.match(view, /<span>최종 산출물 형태<\/span>[\s\S]*?<OutputFormatInput[\s\S]*?value=\{outputFormat\}/);
  assert.match(view, /const outputFormatOptions = \[[\s\S]*?Markdown \(\.md\)[\s\S]*?HTML \(\.html\)/);
  assert.match(view, /role="combobox"[\s\S]*?placeholder="최종 산출물 형태"/);
  assert.match(view, /onChange\(event\.target\.value\)/);
  assert.match(view, /outputFormat !== mission\.outputFormat/);
  assert.match(view, /api\.deepAnalysis\.updateMission\(mission\.id,[\s\S]*?outputFormat: nextOutputFormat/);
  assert.match(view, /api\.deepAnalysis\.createMission\(projectId,[\s\S]*?outputFormat: normalizeOutputFormat\(outputFormat\)/);
});

test("Node output is one rendered document with a link to its saved file", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /className="deep-analysis-output-path"[\s\S]*?onOpenProjectFile\(selectedNode\.outputProjectFileId!?\)/);
  assert.match(view, /파일 저장소에서 열기/);
  assert.match(view, /<ArtifactPreviewActions[\s\S]*?sourceActive=\{selectedNodeShowsSource\}/);
  assert.match(view, /api\.sharing\.create\(selectedNode\.conversationId\)/);
  assert.match(view, /api\.projectFiles\.download\([\s\S]*?selectedNode\.outputProjectFileId/);
  assert.match(view, /projectFilePreviewUrl\(projectId, selectedNode\.outputProjectFileId\)/);
  assert.match(view, /className="deep-analysis-output-source"/);
  assert.match(css, /\.deep-analysis-output-actions > :is\(button, a\) \{[^}]*width: 28px;[^}]*height: 28px/);
  assert.match(view, /className=\{`deep-analysis-output-section \$\{selectedNode\.status === "running" \? "is-streaming" : ""\}`\}/);
  assert.match(view, /selectedNode\.status === "running" \? \(/);
  assert.doesNotMatch(view, /selectedNode\.status === "running" && !selectedNode\.outputSummary/);
  assert.match(view, /ref=\{liveOutputRef\} className="deep-analysis-live-output">\{displayLiveOutput\(selectedNode\.liveOutput\)\}/);
  assert.match(view, /return value\.replace\(\/\\\\r\\\\n\|\\\\n\|\\\\r\/g, "\\n"\)/);
  assert.match(view, /output\.scrollTop = output\.scrollHeight/);
  assert.match(view, /api\.deepAnalysis\.openEventStream/);
  assert.match(view, /const projectionInterval = window\.setInterval\(\(\) => \{\s*void refreshProjection\(\);\s*\}, 500\)/);
  assert.match(view, /window\.clearInterval\(projectionInterval\)/);
  assert.match(view, /className="deep-analysis-output-document conversation-response-typography"/);
  assert.doesNotMatch(css, /\.deep-analysis-output-document\s*\{[^}]*font-size:/s);
  assert.match(view, /<MarkdownResponse text=\{selectedNode\.outputMarkdown\} \/>/);
  assert.match(view, /function isCompleteHtmlDocument\(value: string\)[\s\S]*?normalized\.startsWith\("<!doctype html"\)[\s\S]*?normalized\.includes\("<html"\)[\s\S]*?normalized\.includes\("<head"\)[\s\S]*?normalized\.includes\("<body"\)/);
  assert.match(view, /selectedNode\.outputLogicalPath\?\.toLowerCase\(\)\.endsWith\("\.html"\)[\s\S]*?\|\| isCompleteHtmlDocument\(selectedNode\.outputMarkdown\)[\s\S]*?<ArtifactHtmlPreview[\s\S]*?source=\{selectedNode\.outputMarkdown\}[\s\S]*?previewUrl=\{null\}/);
  assert.match(view, /<ArtifactHtmlPreview[\s\S]*?title=\{`\$\{selectedNode\.title\} HTML 미리보기`\}[\s\S]*?autoHeight/);
  assert.match(css, /\.deep-analysis-output-html \{[^}]*overflow: hidden;[^}]*border: 1px solid var\(--line\)/);
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
  assert.match(view, /api\.deepAnalysis\.restartMission/);
  assert.match(view, /MISSION부터 처음부터 재시작/);
  assert.match(view, /restartArmed \? "한 번 더 눌러 처음부터 재시작"/);
  assert.match(view, /api\.deepAnalysis\.createExport/);
  assert.match(view, /api\.deepAnalysis\.deleteMission\(mission\.id, mission\.revision\)/);
  assert.match(view, /deleteArmed \? "한 번 더 눌러 삭제"/);
});

test("Mission research controls, steering, citations, and source refresh are explicit", async () => {
  const [view, api, types, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(typesPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /연구 범위 · 웹 출처/);
  assert.match(view, /지정 출처 우선/);
  assert.match(view, /지정 출처만/);
  assert.match(view, /researchPeriod: \{/);
  assert.match(view, /webSourcePolicy: \{/);
  assert.match(view, /새 지침·자료 추가/);
  assert.match(view, /다음에 시작되는 Node부터 적용/);
  assert.match(view, /api\.deepAnalysis\.steerMission/);
  assert.match(view, /출처·인용 검사/);
  assert.match(view, /citationReviewCandidates/);
  assert.match(view, /api\.deepAnalysis\.getResearchInspector/);
  assert.match(view, /자료 변경 확인/);
  assert.match(view, /직전 보고서 차이/);
  assert.match(view, /api\.deepAnalysis\.refreshMission/);
  assert.match(api, /\/research-inspector/);
  assert.match(api, /\/refresh-preview/);
  assert.match(api, /\/steer/);
  assert.match(api, /\/refresh/);
  assert.match(types, /interface DeepAnalysisWebSourcePolicy/);
  assert.match(types, /interface DeepAnalysisResearchInspector/);
  assert.match(types, /interface DeepAnalysisRefreshPreview/);
  assert.match(css, /\.deep-analysis-steer-panel/);
  assert.match(css, /\.deep-analysis-research-inspector/);
  assert.match(view, /deep-analysis-mission-maintenance-actions/);
  assert.match(view, /deep-analysis-refresh-run lumina-primary-action/);
  assert.match(css, /\.deep-analysis-mission-maintenance-actions > button \{ min-width: 0; flex: 1 1 220px; \}/);
  assert.match(css, /\.deep-analysis-research-inspector > button \{[^}]*font-size: var\(--conversation-font-size\)/);
  assert.doesNotMatch(css, /\.deep-analysis-refresh-section/);
});

test("Mission event streaming uses a lightweight projection for live progress", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /api\.deepAnalysis\.getProjection\(selectedMissionId\)/);
  assert.match(view, /projectedNodes = new Map/);
  assert.match(view, /DETAIL_REFRESH_EVENT_TYPES\.has\(event\.type\)/);
  assert.match(view, /else scheduleProjectionRefresh\(\)/);
  assert.match(view, /liveOutput/);
});
