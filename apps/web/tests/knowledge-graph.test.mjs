import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const graphPath = new URL("../src/workspace-frontends/knowledge/KnowledgeGraph.tsx", import.meta.url);
const viewPath = new URL("../src/workspace-frontends/knowledge/KnowledgeView.tsx", import.meta.url);
const workerPath = new URL("../src/workspace-frontends/knowledge/knowledge-layout.worker.ts", import.meta.url);
const viteConfigPath = new URL("../vite.config.ts", import.meta.url);

test("Knowledge graph runs the coupled D3 force simulation in a worker", async () => {
  const [graph, worker, viteConfig] = await Promise.all([
    readFile(graphPath, "utf8"),
    readFile(workerPath, "utf8"),
    readFile(viteConfigPath, "utf8"),
  ]);
  assert.doesNotMatch(graph, /from "d3-force"/);
  assert.match(graph, /new Worker\(\s*new URL\("\.\/knowledge-layout\.worker\.ts", import\.meta\.url\)/);
  assert.match(worker, /from "d3-force"/);
  assert.match(viteConfig, /optimizeDeps:\s*\{\s*include:\s*\["d3-force"\]/);
  assert.match(worker, /forceSimulation<LayoutNode>\(nodes\)/);
  assert.match(worker, /forceLink<LayoutNode, LayoutLink>\(links\)/);
  assert.match(worker, /forceManyBody<LayoutNode>\(\)/);
  assert.match(worker, /forceX<LayoutNode>\(0\)/);
  assert.match(worker, /forceY<LayoutNode>\(0\)/);
  assert.match(worker, /forceCollide<LayoutNode>\(\)/);
  assert.match(worker, /\.velocityDecay\(0\.36\)/);
  assert.match(worker, /new Float32Array\(nodes\.length \* 2\)/);
  assert.match(worker, /const positionPublishIntervalMs = 16;/);
  assert.match(worker, /now - lastPublishedAt < positionPublishIntervalMs/);
  assert.match(graph, /data-force-engine="d3-worker"/);
  assert.match(graph, /centerStrength: 0\.032/);
  assert.match(graph, /<ForceControl label="중력" value=\{forceSettings\.centerStrength\}/);
});

test("Knowledge graph sends drag and release work to the layout worker", async () => {
  const [graph, worker] = await Promise.all([readFile(graphPath, "utf8"), readFile(workerPath, "utf8")]);
  assert.match(graph, /layoutWorkerRef\.current\?\.postMessage\(\{ type: "heat", alpha \}\)/);
  assert.match(graph, /node\.fx = node\.x/);
  assert.match(graph, /node\.fy = node\.y/);
  assert.match(graph, /dragState\.node\.fx = world\.x/);
  assert.match(graph, /dragState\.node\.fy = world\.y/);
  assert.match(graph, /node\.fx = null/);
  assert.match(graph, /node\.fy = null/);
  assert.match(graph, /type: "pin"/);
  assert.match(graph, /type: "release"/);
  assert.match(graph, /if \(dragState\?\.node === node\) return;/);
  assert.match(graph, /let dragSyncFrame: number \| null = null;/);
  assert.match(graph, /function requestDraggedNodeSync\(\)[\s\S]*?dragSyncFrame = requestAnimationFrame/);
  assert.match(graph, /function flushDraggedNodeSync\(node: GraphNode\)[\s\S]*?cancelAnimationFrame\(dragSyncFrame\)/);
  assert.match(graph, /requestDraggedNodeSync\(\);/);
  assert.ok(
    graph.indexOf("flushDraggedNodeSync(completedDrag.node)") < graph.indexOf("releaseNode(completedDrag.node)"),
    "the latest coalesced drag position must reach the worker before release",
  );
  assert.match(worker, /simulation\.alphaTarget\(0\)/);
  assert.match(graph, /if \(openDocument && !completedDrag\.moved\) documentToOpen = completedDrag\.node/);
  assert.doesNotMatch(graph, /canvas\.addEventListener\("click"/);
  assert.ok(
    graph.indexOf("captureTarget.releasePointerCapture(event.pointerId)") < graph.indexOf("onSelectDocumentRef.current(documentToOpen.id)"),
    "document navigation must run after pointer capture is released",
  );
});

test("Knowledge graph opens documents from the node circle and its visible label", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const hitRadius = node\.radius \+ 6 \/ viewport\.scale/);
  assert.match(graph, /\(world\.x - node\.x\) \*\* 2 \+ \(world\.y - node\.y\) \*\* 2 <= hitRadius \*\* 2/);
  assert.match(graph, /button\.className = "knowledge-graph-node-hit-target"/);
  assert.match(graph, /button\.setAttribute\("aria-label", `\$\{node\.name\} 문서 열기 · 대표 태그 \$\{node\.categoryLabel\}`\)/);
  assert.match(graph, /const labelWidth = showLabel \? context\.measureText\(label\)\.width \* viewport\.scale : 0/);
  assert.match(graph, /const hitWidth = showLabel \?/);
  assert.match(graph, /button\.style\.width = `\$\{hitWidth\}px`/);
  assert.match(graph, /button\.style\.transform = `translate\(/);
  assert.match(graph, /const onNodePointerDown = \(event: PointerEvent\) => onPointerDown\(event, node, button\)/);
  assert.match(graph, /if \(documentToOpen\) onSelectDocumentRef\.current\(documentToOpen\.id\)/);
});

test("Knowledge graph labels use an Obsidian-like readable size", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const graphLabelFontSize = 14/);
  assert.match(graph, /const graphLabelGap = 7/);
  assert.match(graph, /context\.font = `\$\{graphLabelFontSize \/ viewport\.scale\}px \$\{colors\.font\}`/);
  assert.match(graph, /node\.x \+ node\.radius \+ graphLabelGap \/ viewport\.scale/);
});

test("Knowledge graph exposes the four Obsidian-style force controls", async () => {
  const [graph, worker] = await Promise.all([readFile(graphPath, "utf8"), readFile(workerPath, "utf8")]);
  assert.match(graph, /label="중력"/);
  assert.match(graph, /label="반발력"/);
  assert.match(graph, /label="링크 장력"/);
  assert.match(graph, /label="링크 거리"/);
  assert.match(graph, /postMessage\(\{ type: "settings", settings: forceSettings \}\)/);
  assert.match(worker, /forces\.x\.strength\(settings\.centerStrength\)/);
  assert.match(worker, /forces\.charge\.strength\(-settings\.repulsion\)/);
  assert.match(worker, /forces\.link\.strength\(settings\.linkStrength\)\.distance\(settings\.linkDistance\)/);
  assert.match(graph, /setForceSettings\(defaultForceSettings\)/);
});

test("Knowledge graph shows only shared tags when the pointer is near an edge", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const nextHoveredNode = findNode\(point\)/);
  assert.match(graph, /const nextHoveredNode = findNode\(canvasPoint\(event\)\)/);
  assert.match(graph, /const edgeHitRadius = 10/);
  assert.match(graph, /distanceToSegment\(point, start, end\) <= edgeHitRadius/);
  assert.match(graph, /tagNames: edge\.sharedTagIds\.flatMap/);
  assert.match(graph, /link\.tagNames\.map\(\(name\) => `#\$\{name\}`\)/);
  assert.match(graph, /canvas\.style\.cursor = hoveredNode \? "grab" : "move"/);
  assert.match(graph, /className="knowledge-graph-edge-tooltip" role="tooltip" hidden/);
  assert.match(graph, /let focusLevel = 0/);
  assert.doesNotMatch(graph, /let focusLevel = hoveredLink/);
  assert.doesNotMatch(graph, /link === hoveredLink \? 1 : 0/);
  assert.doesNotMatch(graph, /tooltip\.textContent\s*=\s*["'`]공통 태그/);
});

test("Knowledge graph keeps idle edges visible and highlights active edges in ink", async () => {
  const [graph, styles] = await Promise.all([
    readFile(graphPath, "utf8"),
    readFile(new URL("../src/workspace-frontends/knowledge/knowledge.css", import.meta.url), "utf8"),
  ]);
  assert.match(graph, /edgeHighlight: token\("--ink", "#20242c"\)/);
  assert.match(graph, /const baseLineWidth = 1\.35 \+ Math\.min\(0\.3, link\.weight \* 0\.08\)/);
  assert.match(graph, /context\.globalAlpha = lerp\(0\.68, 0\.16, focusLevel\)/);
  assert.match(graph, /context\.lineWidth = lerp\(baseLineWidth, 1\.65, activeLevel\)/);
  assert.match(graph, /context\.strokeStyle = colors\.edgeHighlight/);
  assert.match(graph, /context\.globalAlpha = 0\.95 \* activeLevel/);
  assert.doesNotMatch(styles, /--knowledge-graph-edge-highlight/);
});

test("Knowledge graph eases node hover emphasis over a short animation", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const hoverTransitionDuration = 160/);
  assert.match(graph, /const animateHover = \(timestamp: number\) =>/);
  assert.match(graph, /1 - Math\.exp\(\(-5 \* delta\) \/ hoverTransitionDuration\)/);
  assert.match(graph, /hoverFrame = requestAnimationFrame\(animateHover\)/);
  assert.match(graph, /const nodeAlpha = selected \? 1 : 1 - 0\.84 \* Math\.max\(0, focusLevel - relatedLevel\)/);
  assert.match(graph, /0\.84 - 0\.74 \* Math\.max\(0, focusLevel - relatedLevel\) \+ 0\.16 \* ownLevel/);
  assert.match(graph, /node\.radius \* \(selected \? 1\.32 : 1 \+ 0\.2 \* ownLevel\)/);
  assert.match(graph, /if \(reducedMotion\) \{\s*nodeHoverLevels\.clear\(\)/);
  assert.match(graph, /if \(hoverFrame !== null\) cancelAnimationFrame\(hoverFrame\)/);
});

test("Knowledge graph eases wheel zoom across animation frames", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const animateZoom = \(\) =>/);
  assert.match(graph, /Math\.exp\(Math\.log\(scaleRatio\) \* 0\.128\)/);
  assert.match(graph, /targetScale = clamp\(targetScale \* Math\.exp\(-normalizedDelta \* 0\.0015\), 0\.28, 3\.5\)/);
  assert.match(graph, /zoomFrame = requestAnimationFrame\(animateZoom\)/);
  assert.match(graph, /if \(reducedMotion\)/);
  assert.match(graph, /nodeLayer\.addEventListener\("wheel", onWheel, \{ passive: false \}\)/);
  assert.match(graph, /nodeLayer\.removeEventListener\("wheel", onWheel\)/);
  assert.match(graph, /if \(zoomFrame !== null\) cancelAnimationFrame\(zoomFrame\)/);
});

test("Knowledge graph restores the last layout when its tab remounts", async () => {
  const [graph, view] = await Promise.all([readFile(graphPath, "utf8"), readFile(viewPath, "utf8")]);
  assert.match(view, /<KnowledgeGraph graph=\{graph\} layoutKey=\{space\.id\}/);
  assert.match(graph, /const graphLayouts = new Map<string, GraphLayout>\(\)/);
  assert.match(graph, /const savedLayout = graphLayouts\.get\(layoutKey\)/);
  assert.match(graph, /const restoresCompleteLayout = savedLayout\?\.graphSignature === graphSignature/);
  assert.match(graph, /canvas\.dataset\.layoutRestored = restoresCompleteLayout \? "true" : "false"/);
  assert.match(graph, /settled: restoresCompleteLayout/);
  const worker = await readFile(workerPath, "utf8");
  assert.match(worker, /if \(request\.settled\) \{\s*simulation\.alpha\(0\)\.stop\(\)/);
  assert.match(graph, /rememberGraphLayout\(layoutKey, \{/);
  assert.match(graph, /viewport: \{ \.\.\.viewport \}/);
});

test("Graph nodes use representative-tag colors while selection keeps the category color", async () => {
  const [graph, view] = await Promise.all([readFile(graphPath, "utf8"), readFile(viewPath, "utf8")]);
  assert.match(view, /tab === "graph" \? setSelectedGraphNodeId\(id\) : openDocument\(id, tab\)/);
  assert.match(view, /onRead=\{tab === "graph" \? \(id\) => openDocument\(id, "wiki", "graph"\) : undefined\}/);
  assert.match(view, /onDoubleClick=\{\(\) => onRead\?\.\(document\.id\)\}/);
  assert.match(view, /tab === "graph" && view !== "graph" && selectedGraphNodeId/);
  assert.match(view, /openDocument\(selectedGraphNodeId, view, "graph"\)/);
  assert.match(view, /loadDocument\(documentId\)\.then\(\(\) => setTab\(nextTab\)\)/);
  assert.match(view, /selectedNodeId=\{selectedGraphNodeId\}/);
  assert.match(graph, /function buildNodeColorGroups/);
  assert.match(graph, /\(tagUsage\.get\(right\.id\) \?\? 0\) - \(tagUsage\.get\(left\.id\) \?\? 0\)/);
  assert.match(graph, /context\.fillStyle = colors\.nodePalette\[node\.colorIndex\]/);
  assert.match(graph, /context\.strokeStyle = selected \? colors\.cobalt : colors\.ink/);
  assert.match(graph, /className="knowledge-graph-legend" aria-label="노드 색상: 대표 태그"/);
  assert.match(graph, /if \(selected\) button\.setAttribute\("aria-current", "true"\)/);
  assert.match(graph, /else button\.removeAttribute\("aria-current"\)/);
});

test("Graph documents provide visible and browser-history return paths", async () => {
  const view = await readFile(viewPath, "utf8");
  assert.match(view, /import \{ createClientId \} from "\.\.\/\.\.\/client-id"/);
  assert.match(view, /const entryId = createClientId\(\)/);
  assert.doesNotMatch(view, /crypto\.randomUUID\(\)/);
  assert.match(view, /window\.history\.pushState/);
  assert.match(view, /window\.addEventListener\("popstate", returnFromDocument\)/);
  assert.match(view, /openDocument\(id, "wiki", "graph"\)/);
  assert.match(view, /window\.history\.back\(\)/);
  assert.match(view, /그래프로 돌아가기/);
});

test("Knowledge graph layout memory is bounded and refreshed as an LRU cache", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const graphLayoutNodeBudget = 1_600;/);
  assert.match(graph, /function rememberGraphLayout[\s\S]*?graphLayouts\.delete\(layoutKey\);[\s\S]*?cachedNodeCount > graphLayoutNodeBudget/);
  assert.match(graph, /if \(savedLayout\) rememberGraphLayout\(layoutKey, savedLayout\);/);
});
