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

test("Workflow keeps cost detail opt-in and exposes selectable Node inspection", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /aria-expanded=\{costDetailsOpen\}/);
  assert.match(view, /노드별 비용/);
  assert.match(view, /setSelectedNodeKey\(node\.nodeKey\)/);
  assert.match(view, /deep-analysis-inspector/);
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
  assert.match(view, /window\.setInterval\(refresh, 1_500\)/);
  assert.match(view, /selectedNode\.liveOutput/);
  assert.match(view, /\$\{completedNodeCount\}\/\$\{mission\.workflow\.nodes\.length\} Node 완료/);
  assert.match(view, /selectedNode\.outputMarkdown/);
  assert.match(view, /translate3d\(\$\{canvasOffset\.x\}px, \$\{canvasOffset\.y\}px, 0\) scale\(\$\{canvasScale\}\)/);
  assert.match(view, /setCanvasOffset\(\{\s*x: pan\.offsetX \+ event\.clientX - pan\.clientX,/);
  assert.match(view, /if \(wasBlankClick\) closeNodeInspectorAndFit\(\)/);
  assert.match(view, /function fitCanvasToViewport\(\)/);
  assert.match(view, /window\.requestAnimationFrame\(\(\) => window\.requestAnimationFrame\(fitCanvasToViewport\)\)/);
  assert.match(css, /\.deep-analysis-canvas-stage \{[^}]*overflow: clip;/);
  assert.match(view, /aria-label="확대"[\s\S]*?Math\.round\(canvasScale \* 100\)[\s\S]*?aria-label="축소"/);
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
