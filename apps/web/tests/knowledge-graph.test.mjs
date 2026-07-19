import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const graphPath = new URL("../src/workspace-frontends/knowledge/KnowledgeGraph.tsx", import.meta.url);
const viewPath = new URL("../src/workspace-frontends/knowledge/KnowledgeView.tsx", import.meta.url);

test("Knowledge graph uses a coupled D3 force simulation", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /from "d3-force"/);
  assert.match(graph, /forceSimulation<GraphNode>\(nodes\)/);
  assert.match(graph, /forceLink<GraphNode, GraphLink>\(links\)/);
  assert.match(graph, /forceManyBody<GraphNode>\(\)\.strength\(-forceSettings\.repulsion\)/);
  assert.match(graph, /forceX<GraphNode>\(0\)\.strength\(forceSettings\.centerStrength\)/);
  assert.match(graph, /forceY<GraphNode>\(0\)\.strength\(forceSettings\.centerStrength\)/);
  assert.match(graph, /forceCollide<GraphNode>\(\)/);
  assert.match(graph, /\.strength\(forceSettings\.linkStrength\)/);
  assert.match(graph, /\.distance\(forceSettings\.linkDistance\)/);
  assert.match(graph, /\.velocityDecay\(0\.36\)/);
  assert.match(graph, /data-force-engine="d3"/);
});

test("Knowledge graph reheats every force while dragging and releases the node", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /simulation\.alphaTarget\(alpha\)/);
  assert.match(graph, /simulation\.restart\(\)/);
  assert.match(graph, /node\.fx = node\.x/);
  assert.match(graph, /node\.fy = node\.y/);
  assert.match(graph, /dragState\.node\.fx = world\.x/);
  assert.match(graph, /dragState\.node\.fy = world\.y/);
  assert.match(graph, /node\.fx = null/);
  assert.match(graph, /node\.fy = null/);
  assert.match(graph, /simulation\.alphaTarget\(0\)/);
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
  assert.match(graph, /button\.setAttribute\("aria-label", `\$\{node\.name\} 문서 열기`\)/);
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
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /label="중심 장력"/);
  assert.match(graph, /label="반발력"/);
  assert.match(graph, /label="링크 장력"/);
  assert.match(graph, /label="링크 거리"/);
  assert.match(graph, /forces\.x\.strength\(forceSettings\.centerStrength\)/);
  assert.match(graph, /forces\.charge\.strength\(-forceSettings\.repulsion\)/);
  assert.match(graph, /forces\.link\.strength\(forceSettings\.linkStrength\)\.distance\(forceSettings\.linkDistance\)/);
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

test("Knowledge graph keeps idle edges visible and highlights active edges in green", async () => {
  const [graph, styles] = await Promise.all([
    readFile(graphPath, "utf8"),
    readFile(new URL("../src/workspace-frontends/knowledge/knowledge.css", import.meta.url), "utf8"),
  ]);
  assert.match(graph, /edgeHighlight: token\("--success", "#2f9765"\)/);
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
  assert.match(graph, /const nodeAlpha = 1 - 0\.84 \* Math\.max\(0, focusLevel - relatedLevel\)/);
  assert.match(graph, /0\.84 - 0\.74 \* Math\.max\(0, focusLevel - relatedLevel\) \+ 0\.16 \* ownLevel/);
  assert.match(graph, /node\.radius \* \(1 \+ 0\.2 \* ownLevel\)/);
  assert.match(graph, /if \(reducedMotion\) \{\s*nodeHoverLevels\.clear\(\)/);
  assert.match(graph, /if \(hoverFrame !== null\) cancelAnimationFrame\(hoverFrame\)/);
});

test("Knowledge graph eases wheel zoom across animation frames", async () => {
  const graph = await readFile(graphPath, "utf8");
  assert.match(graph, /const animateZoom = \(\) =>/);
  assert.match(graph, /Math\.exp\(Math\.log\(scaleRatio\) \* 0\.24\)/);
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
  assert.match(graph, /if \(restoresCompleteLayout\) \{\s*simulation\.alpha\(0\)\.stop\(\)/);
  assert.match(graph, /graphLayouts\.set\(layoutKey, \{/);
  assert.match(graph, /viewport: \{ \.\.\.viewport \}/);
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
