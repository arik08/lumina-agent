import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const viewPath = new URL(
  "../src/workspace-frontends/deep-analysis/DeepAnalysisView.tsx",
  import.meta.url,
);
const apiPath = new URL("../src/api.ts", import.meta.url);
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
  assert.match(api, /code: "invalid_api_response"/);
  assert.match(api, /!contentType\.includes\("application\/json"\)/);
  assert.match(api, /cache: requestInit\.cache \?\? "no-store"/);
});

test("Mission navigation lives in the shared sidebar instead of a duplicate content pane", async () => {
  const [app, view, css] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(app, /deepAnalysisMissions\.map\(\(missionSummary\)/);
  assert.match(app, /<Workflow size=\{14\} \/>/);
  assert.match(app, /requestedMissionId=\{deepAnalysisSelectedMissionId\}/);
  assert.doesNotMatch(view, /className="deep-analysis-missions"/);
  assert.doesNotMatch(css, /\.deep-analysis-missions/);
  assert.match(css, /\.deep-analysis-workspace \{[^}]*flex: 1;/);
});

test("new analysis action uses the shared sidebar and opens creation in the workspace", async () => {
  const [app, view] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(viewPath, "utf8"),
  ]);

  assert.match(app, /sidebarView === "deep-analysis"[\s\S]*?startNewDeepAnalysis[\s\S]*?<span>새 분석<\/span>/);
  assert.match(view, /className="deep-analysis-create-shell"/);
  assert.match(view, /onCreateRequestHandled\(\)/);
  assert.doesNotMatch(view, /deep-analysis-new-button/);
});

test("project selection preserves the active top-level feature", async () => {
  const app = await readFile(appPath, "utf8");
  const projectSelection = app.match(/workspace\.projects\.map\(\(project\) => \([\s\S]*?workspace\.setActiveProjectId\(project\.id\);[\s\S]*?setProjectMenuOpen\(false\);/)?.[0] ?? "";

  assert.ok(projectSelection);
  assert.doesNotMatch(projectSelection, /setMainView\("chat"\)/);
});

test("project settings preserve the active deep-analysis sidebar", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /const sidebarView = mainView === "project-settings" \? projectSettingsReturnView : mainView;/);
  assert.match(app, /setProjectSettingsReturnView\(mainView\);[\s\S]*?setMainView\("project-settings"\);/);
  assert.match(app, /sidebarView === "deep-analysis"[\s\S]*?<span>새 분석<\/span>/);
  assert.match(app, /sidebarView === "deep-analysis" \? \([\s\S]*?deepAnalysisMissions\.map/);
  assert.match(app, /className=\{sidebarView === id \? "is-active" : ""\}/);
  assert.match(app, /mainView === "project-settings"\) setMainView\(projectSettingsReturnView\);/);
});

test("Mission header keeps the title and objective on one row", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);
  const missionHeader = view.match(/<header className="deep-analysis-mission-header">([\s\S]*?)<div className="deep-analysis-mission-actions">/)?.[1] ?? "";

  assert.match(missionHeader, /<h2>\{mission\.title\}<\/h2>/);
  assert.match(missionHeader, /mission\.objective/);
  assert.match(css, /\.deep-analysis-mission-header > div:first-child \{[^}]*display: flex;[^}]*align-items: baseline;/);
  assert.doesNotMatch(missionHeader, /statusLabel\(mission\.status\)/);
  assert.doesNotMatch(css, /\.deep-analysis-mission-header \{[^}]*min-height:/);
});

test("Workflow keeps cost detail opt-in and exposes selectable Node inspection", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /aria-expanded=\{costDetailsOpen\}/);
  assert.match(view, /비용 상세/);
  assert.match(view, /setSelectedNodeKey\(node\.nodeKey\)/);
  assert.match(view, /deep-analysis-inspector/);
});

test("Node status shares the identity row in cards and the inspector", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /<div className="deep-analysis-node-meta">[\s\S]*?\{node\.nodeKey\}[\s\S]*?status-\$\{node\.status\}[\s\S]*?<strong>\{node\.title\}<\/strong>/);
  assert.match(view, /<span>\{selectedNode\.nodeKey\}<\/span>[\s\S]*?status-\$\{selectedNode\.status\}[\s\S]*?aria-label="노드 상세 닫기"/);
  assert.match(css, /\.deep-analysis-node-meta \{[^}]*justify-content: space-between;/);
  assert.match(css, /\.deep-analysis-inspector > header > div \{[^}]*grid-template-columns: minmax\(0, 1fr\) auto auto;/);
});

test("Workflow starts through the backend and supports pan and pointer-centered zoom", async () => {
  const [view, api] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  assert.match(view, /Workflow 시작/);
  assert.match(view, /api\.deepAnalysis\.startMission/);
  assert.match(api, /\/deep-analysis\/missions\/\$\{encodeURIComponent\(missionId\)\}\/start/);
  assert.match(view, /onPointerDown=\{beginCanvasPan\}/);
  assert.match(view, /onPointerMove=\{moveCanvasPan\}/);
  assert.match(view, /onWheel=\{handleCanvasWheel\}/);
  assert.match(view, /event\.clientX - rect\.left/);
  assert.match(view, /minimumCanvasScale = 0\.4/);
  assert.match(view, /maximumCanvasScale = 1\.8/);
});

test("Workflow exposes cancellation, icon cost detail, and a collapsible inspector column", async () => {
  const [view, api] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  assert.match(view, /api\.deepAnalysis\.cancelMission/);
  assert.match(api, /\/deep-analysis\/missions\/\$\{encodeURIComponent\(missionId\)\}\/cancel/);
  assert.match(view, /data-tooltip=\{`누적 비용 \$\{formatCost\(mission\.spentMicrousd\)\}`\}/);
  assert.match(view, /className=\{`deep-analysis-workflow-layout \$\{selectedNode \? "has-inspector" : ""\}`\}/);
  assert.match(view, /cancellingMission \? "중단 중" : "중단"/);
});

test("Workflow reports live Run progress and pans with transform at every zoom", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /!mission\.executionAvailable/);
  assert.match(view, /실제 Lumina Run \$\{activeNode\.runStatus/);
  assert.match(view, /window\.setInterval\(\(\) => void refresh\(\), 1_500\)/);
  assert.match(view, /selectedNode\.liveOutput/);
  assert.match(view, /\$\{completedNodeCount\}\/\$\{mission\.workflow\.nodes\.length\} Node 완료/);
  assert.match(view, /selectedNode\.outputMarkdown/);
  assert.match(view, /translate3d\(\$\{canvasOffset\.x\}px, \$\{canvasOffset\.y\}px, 0\) scale\(\$\{canvasScale\}\)/);
  assert.match(view, /setCanvasOffset\(\{\s*x: pan\.offsetX \+ event\.clientX - pan\.clientX,/);
  assert.match(view, /if \(wasBlankClick\) closeNodeInspectorAndFit\(\)/);
  assert.match(view, /function fitCanvasToViewport\(\)/);
  assert.match(view, /window\.requestAnimationFrame\(\(\) => window\.requestAnimationFrame\(fitCanvasToViewport\)\)/);
  assert.match(view, /aria-label="실행 과정"/);
  assert.match(view, /missionEvents\.slice\(-12\)/);
  assert.match(view, /onKeyDown=\{onKeyDown\}/);
  assert.match(view, /event\.shiftKey \? 40 : 10/);
  assert.match(css, /\.deep-analysis-canvas-stage \{[^}]*overflow: clip;/);
  assert.match(view, /aria-label="확대"[\s\S]*?Math\.round\(canvasScale \* 100\)[\s\S]*?aria-label="축소"/);
});

test("adaptive Workflow changes retain graph semantics and refit on updates", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.doesNotMatch(view, /deep-analysis-workflow-change/);
  assert.doesNotMatch(css, /\.deep-analysis-workflow-change/);
  assert.match(view, /결과에 따라 남은 Workflow가 확장되거나 축소될 수 있습니다/);
  assert.match(view, /\[shownWorkflow\?\.graphDigest\]/);
  assert.match(view, /typeof selectedNode\.config\.reason === "string"/);
  assert.match(view, /branchCount: branchNodeKeys\.size/);
  assert.match(view, /mergeCount: mergeNodeKeys\.size/);
  assert.match(view, /분기 \{workflowTopology\.branchCount\} · 합류 \{workflowTopology\.mergeCount\}/);
  assert.match(view, /workflowTopology\.branchNodeKeys\.has\(edge\.sourceNodeKey\)/);
  assert.match(view, /workflowTopology\.mergeNodeKeys\.has\(edge\.targetNodeKey\)/);
  assert.match(css, /path\.is-branch/);
  assert.match(css, /path\.is-merge/);
});

test("Workflow Draft supports node drag, dependency connect, save and atomic activation", async () => {
  const [view, api, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);
  assert.doesNotMatch(view, /Workflow 구조 편집/);
  assert.match(view, /api\.deepAnalysis\.createDraft/);
  assert.match(view, /api\.deepAnalysis\.updateDraft/);
  assert.match(view, /api\.deepAnalysis\.activateDraft/);
  assert.match(view, /function beginNodeDrag/);
  assert.match(view, /event\.clientX - drag\.clientX\) \/ canvasScale/);
  assert.match(view, /function toggleDependency/);
  assert.match(view, /선행 Node 연결/);
  assert.match(view, /Node 추가/);
  assert.match(view, /Draft 활성화/);
  assert.match(api, /createDraft: createDeepAnalysisWorkflowDraft/);
  assert.match(api, /updateDraft: updateDeepAnalysisWorkflowDraft/);
  assert.match(api, /activateDraft: activateDeepAnalysisWorkflowDraft/);
  assert.match(css, /\.deep-analysis-node\.is-editable/);
  assert.doesNotMatch(css, /\.deep-analysis-workflow-editor/);
  assert.match(view, /deep-analysis-pattern-wrap[\s\S]*?deep-analysis-workflow-action is-primary[\s\S]*?편집 시작/);
  assert.match(css, /\.deep-analysis-canvas-controls \{[^}]*top: 12px;[^}]*right: 12px;/);
  assert.doesNotMatch(css, /\.deep-analysis-workflow-layout:has\(\+ \.deep-analysis-execution-log\.is-open\) \.deep-analysis-canvas-controls/);
});

test("Project Pattern Library stays optional and publishes immutable reviewed versions", async () => {
  const [view, api, types, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(new URL("../src/api-types.ts", import.meta.url), "utf8"),
    readFile(cssPath, "utf8"),
  ]);
  assert.match(view, /제로베이스 · 질문에 맞춰 새로 설계/);
  assert.match(view, /Pattern 없이도 동일한 실행·기록·복구 기능/);
  assert.match(view, /검토용 Draft 만들기/);
  assert.match(view, /검토 완료 · Publish/);
  assert.match(view, /파일 ID·수치·답변·출력은 제외/);
  assert.match(view, /patternVersionId: selectedPatternVersionId \|\| null/);
  assert.match(api, /listPatterns: listDeepAnalysisPatterns/);
  assert.match(api, /createPatternVersion: createDeepAnalysisPatternVersion/);
  assert.match(api, /publishPatternVersion: publishDeepAnalysisPatternVersion/);
  assert.match(types, /interface DeepAnalysisWorkflowPatternVersion/);
  assert.match(css, /\.deep-analysis-pattern-popover \{/);
});

test("durable Decision requests pause inline and resume through the revision-checked API", async () => {
  const [view, api, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /mission\?\.decisions\.find\(\(decision\) => decision\.status === "pending"\)/);
  assert.match(view, /사용자 판단이 필요합니다/);
  assert.match(view, /AI 권고/);
  assert.match(view, /api\.deepAnalysis\.answerDecision/);
  assert.match(view, /expectedRevision: mission\.revision/);
  assert.match(view, /selectedOptionId: decisionOptionId/);
  assert.match(view, /이 결정으로 계속/);
  assert.match(view, /mission\.status === "running" \|\| mission\.status === "paused" \|\| mission\.status === "awaiting_input"/);
  assert.match(api, /decisions\/\$\{encodeURIComponent\(decisionId\)\}\/answer/);
  assert.match(api, /answerDecision: answerDeepAnalysisDecision/);
  assert.match(css, /\.deep-analysis-decision \{/);
  assert.match(css, /\.deep-analysis-decision-options > button\.is-selected/);
});

test("Mission Charter is editable before start and immutable Quality Gates remain visible", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, /목표·완료 기준/);
  assert.match(view, /aria-controls="deep-analysis-goal-completion"/);
  assert.match(view, /function toggleGoalCompletionPanel\(\)[\s\S]*?setExecutionLogOpen\(false\)/);
  assert.match(view, /function toggleExecutionLog\(\)[\s\S]*?setContractOpen\(false\)/);
  assert.match(view, /className=\{`deep-analysis-workspace \$\{contractOpen \? "is-contract-open" : ""\}`\}/);
  assert.match(view, /className="deep-analysis-contract-primary"/);
  assert.match(view, /분석 목표<textarea/);
  assert.match(view, /핵심 질문<textarea/);
  assert.match(view, /보고서 구성<textarea/);
  assert.match(view, /placeholder="예: 2025년 4분기 대비 2026년 4분기 영업이익 감소 원인 분석"/);
  assert.match(view, /placeholder=\{"예:\\n영업이익은 전년 동기 대비 얼마나 감소했는가\?\\n감소에 가장 크게 기여한 요인은 무엇인가\?"\}/);
  assert.match(view, /placeholder=\{"예:\\n요약\\n주요 변동 요인\\n근거와 한계"\}/);
  assert.match(view, /placeholder="예: 2025년 4분기 대비 2026년 4분기"/);
  assert.match(view, /placeholder="예: 경영진용 Markdown 보고서"/);
  assert.match(view, /대상 기간<input[^>]*comparisonBasis/);
  assert.match(view, /산출물 형태<input[^>]*deliverables/);
  assert.doesNotMatch(view, /<summary>상세 설정/);
  assert.doesNotMatch(view, /최소 근거 충족률/);
  assert.doesNotMatch(view, /허용 미해결 항목 수/);
  assert.match(css, /\.deep-analysis-workspace\.is-contract-open > :is\([^}]*\.deep-analysis-workflow-layout[^}]*\.deep-analysis-execution-log[^}]*\) \{ display: none; \}/);
  assert.match(css, /\.deep-analysis-contract \{[^}]*flex: 1;[^}]*grid-template-rows: minmax\(0, 1fr\) auto;/);
  assert.match(css, /\.deep-analysis-contract-content \{[^}]*width: min\(1120px, calc\(100% - 64px\)\)/);
  assert.match(css, /\.deep-analysis-contract-primary \{[^}]*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(view, /api\.deepAnalysis\.updateMission/);
  assert.match(view, /charter: \{/);
  assert.match(view, /completionContract: \{/);
  assert.match(view, /function normalizeMissionCharter\(/);
  assert.match(view, /Array\.isArray\(charter\.keyQuestions\)/);
  assert.match(view, /function normalizeCompletionContract\(/);
  assert.match(view, /Array\.isArray\(contract\.requiredSections\)/);
  assert.match(view, /setCharterDraft\(normalizeMissionCharter\(mission\.charter, mission\.objective\)\)/);
  assert.match(view, /setCompletionDraft\(normalizeCompletionContract\(mission\.completionContract\)\)/);
  assert.match(view, /실행을 시작하면 이 계약이 해당 Mission revision에 고정됩니다/);
  assert.match(view, /mission\?\.qualityGates\.at\(-1\)/);
  assert.match(view, /Quality Gate ·/);
  assert.match(view, /검사 결과 보기/);
  assert.match(view, /api\.deepAnalysis\.runQualityGate/);
  assert.match(view, /Quality Gate 다시 검사/);
  assert.match(css, /\.deep-analysis-contract-scroll \{[^}]*overflow-y: auto;/);
  assert.doesNotMatch(css, /\.deep-analysis-contract-advanced/);
  assert.match(css, /\.deep-analysis-quality-gate\.is-failed/);
});

test("Claim Evidence lineage is available as a dedicated ledger tab", async () => {
  const [view, api, types, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(new URL("../src/api-types.ts", import.meta.url), "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.match(view, />결론·근거</);
  assert.match(view, /function EvidenceLedger/);
  assert.match(view, /Claim Ledger/);
  assert.match(view, /stance === "support"/);
  assert.match(view, /재검토 필요/);
  assert.match(api, /missions\/\$\{missionId\}\/claims/);
  assert.match(api, /getClaims: getDeepAnalysisClaims/);
  assert.match(types, /interface DeepAnalysisClaim/);
  assert.match(types, /openIssues: DeepAnalysisOpenIssue\[\]/);
  assert.match(css, /\.deep-analysis-ledger \{/);
});

test("Mission export selects scope and downloads a checksum ZIP", async () => {
  const [view, api, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);
  assert.match(view, /Mission 내보내기/);
  assert.match(view, /과거 version 포함 감사본/);
  assert.match(view, /Project 원본 자료 포함/);
  assert.match(view, /api\.deepAnalysis\.createExport/);
  assert.match(view, /api\.deepAnalysis\.downloadExport/);
  assert.match(api, /createExport: createDeepAnalysisMissionExport/);
  assert.match(api, /downloadExport: downloadDeepAnalysisMissionExport/);
  assert.match(css, /\.deep-analysis-export-popover \{/);
});

test("failed or cancelled Nodes can retry with visible attempts and calculation files", async () => {
  const [view, api] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  assert.match(view, /api\.deepAnalysis\.retryMission/);
  assert.match(view, /이 Node부터 다시 실행/);
  assert.match(view, /selectedNode\.runHistory/);
  assert.match(view, /selectedNode\.generatedFiles/);
  assert.match(view, /입력 자료 \{mission\.sourceManifest\.length\}개/);
  assert.match(api, /\/deep-analysis\/missions\/\$\{encodeURIComponent\(missionId\)\}\/retry/);
});

test("Node details omit the internal context manifest", async () => {
  const [view, css] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(cssPath, "utf8"),
  ]);

  assert.doesNotMatch(view, /Context Manifest|Exact item|Token 추정|Tool profile|Mission context/);
  assert.doesNotMatch(view, /selectedNode\.contextManifest/);
  assert.doesNotMatch(css, /deep-analysis-prefix-hash|deep-analysis-inspector (?:dl|dt|dd)/);
});
test("Mission deletion uses revision-checked API and same-button confirmation", async () => {
  const [view, api] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  assert.match(view, /api\.deepAnalysis\.deleteMission\(mission\.id, mission\.revision\)/);
  assert.match(view, /deleteArmed \? "한 번 더 눌러 삭제" : "삭제"/);
  assert.match(view, /심층분석 삭제 확인, 한 번 더 누르면 삭제/);
  assert.match(view, /setDeleteArmed\(false\)/);
  assert.match(api, /method: "DELETE", query: \{ expected_revision: expectedRevision \}/);
  assert.match(api, /deleteMission: deleteDeepAnalysisMission/);
});
