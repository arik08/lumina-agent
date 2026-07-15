import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [turnSource, rendererSource, rendererStyles, globalStyles] = await Promise.all([
  readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/components/InteractiveResponse.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/components/InteractiveResponse.css", import.meta.url), "utf8"),
  readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
]);

test("chat renders Mermaid and full ECharts options as interactive blocks", () => {
  assert.match(turnSource, /language === "mermaid" \|\| language === "mmd"[\s\S]*?<MermaidDiagram source=\{source\}/);
  assert.match(turnSource, /language === "lumina-chart"[\s\S]*?<InteractiveChart source=\{source\}/);
  assert.match(rendererSource, /securityLevel: "strict"/);
  assert.match(rendererSource, /export function parseInteractiveChart/);
  assert.match(rendererSource, /import\("echarts"\)/);
  assert.match(rendererSource, /echarts\.init\(container/);
  assert.match(rendererSource, /new ResizeObserver\(\(\) => chart\.resize\(\)\)/);
  assert.match(rendererSource, /new MutationObserver\(applyOption\)/);
  assert.match(rendererSource, /darkMode: Boolean\(container\.closest\("\.theme-dark"\)\)/);
  assert.match(rendererSource, /legacyChartOption/);
});

test("Mermaid preloads once, deduplicates active renders, and stays mounted while Markdown grows", () => {
  assert.match(rendererSource, /let mermaidModulePromise: Promise<typeof import\("mermaid"\)> \| null = null/);
  assert.match(rendererSource, /window\.requestIdleCallback\(preloadMermaid, \{ timeout: 1500 \}\)/);
  assert.match(rendererSource, /const mermaidRenderJobs = new Map/);
  assert.match(rendererSource, /const activeJob = mermaidRenderJobs\.get\(cacheKey\)/);
  assert.match(turnSource, /const markdownCodeComponent: NonNullable<Components\["code"\]>/);
  assert.match(turnSource, /code: markdownCodeComponent/);
  assert.doesNotMatch(turnSource, /code: \(\{ className, children \}\) =>/);
});

test("Mermaid uses the designated artifact palette without overriding authored classes", () => {
  for (const color of ["#3288bd", "#66c2a5", "#e6f598", "#d53e4f", "#9e0142", "#f46d43", "#fdae61", "#fee08b", "#abdda4", "#5e4fa2"]) {
    assert.match(rendererSource, new RegExp(color));
    assert.match(rendererStyles, new RegExp(color));
  }
  assert.match(rendererSource, /const mermaidNodeTones = \["blue", "teal", "orange", "red", "purple"\]/);
  assert.match(rendererSource, /const hasAuthoredClass = Array\.from\(node\.classList\)/);
  assert.match(rendererSource, /node\.dataset\.luminaTone = isDecision \? "orange"/);
  assert.match(rendererSource, /pie10: artifactVisualPalette\.purple/);
  assert.match(rendererSource, /cScale9: artifactVisualPalette\.purple/);
  assert.match(rendererSource, /plotColorPalette: artifactVisualPaletteSequence\.join\(","\)/);
  assert.match(rendererStyles, /\.node\[data-lumina-tone="blue"\]/);
  assert.match(rendererStyles, /\.node\[data-lumina-tone="teal"\]/);
  assert.match(rendererStyles, /\.node\[data-lumina-tone="orange"\]/);
  assert.match(rendererStyles, /\.node\[data-lumina-tone="red"\]/);
  assert.match(rendererStyles, /\.node\[data-lumina-tone="purple"\]/);
  assert.match(rendererStyles, /var\(--mermaid-palette-blue\) 14%/);
  assert.match(rendererStyles, /var\(--mermaid-palette-teal\) 16%/);
  assert.match(rendererStyles, /var\(--mermaid-palette-amber\) 22%/);
});

test("tall Mermaid workflows keep readable geometry inside a bounded scroll surface", () => {
  assert.match(rendererStyles, /\.mermaid-surface \{[\s\S]*max-height: min\(640px, 68vh\);[\s\S]*overflow: auto;[\s\S]*overscroll-behavior: contain;/);
  assert.match(rendererStyles, /\.mermaid-surface:not\(\.is-expanded\) \{[^}]*cursor: grab;[^}]*touch-action: none;/);
  assert.match(rendererStyles, /\.mermaid-surface\.is-dragging \{[^}]*cursor: grabbing;[^}]*user-select: none;/);
  assert.match(rendererStyles, /\.mermaid-surface svg \{[\s\S]*width: auto;[\s\S]*max-width: 100%;[\s\S]*height: auto;/);
  assert.match(rendererStyles, /\.mermaid-surface\.is-expanded \{[\s\S]*max-height: none;/);
  assert.doesNotMatch(rendererStyles, /\.mermaid-surface svg \{[\s\S]*max-height: 660px;/);
  assert.doesNotMatch(globalStyles, /\.mermaid-diagram svg/);
});

test("Mermaid and structured charts expose a zoomable, pannable dialog", () => {
  assert.match(rendererSource, /function ZoomViewer/);
  assert.match(rendererSource, /document\.querySelector\("\.app-shell\.theme-dark"\) \? " theme-dark" : ""/);
  assert.match(rendererSource, /className=\{`response-zoom-backdrop\$\{themeClassName\}`\}/);
  assert.match(globalStyles, /\.response-zoom-backdrop\.theme-dark,[\s\S]*?\.app-shell\.theme-dark/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 확대"/);
  assert.match(rendererSource, /<div[\s\S]*?className="interactive-response-toolbar interactive-response-expand-trigger"[\s\S]*?role="button"[\s\S]*?tabIndex=\{0\}[\s\S]*?onClick=\{\(\) => setExpanded\(true\)\}/);
  assert.match(rendererSource, /className="response-zoom-title"[\s\S]*?aria-label=\{`\$\{title\} 확대 보기 닫기`\}[\s\S]*?onClick=\{onClose\}/);
  assert.match(rendererStyles, /\.response-zoom-title \{[^}]*cursor: pointer;/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 확대"\s+onClick/);
  assert.match(rendererSource, /className="interactive-response-expand-icon" aria-hidden="true"><Maximize2 size=\{15\} \/><\/span>/);
  assert.match(rendererSource, /event\.key !== "Enter" && event\.key !== " "/);
  assert.match(rendererSource, /event\.currentTarget\.scrollLeft = drag\.scrollLeft - \(event\.clientX - drag\.x\)/);
  assert.match(rendererSource, /event\.currentTarget\.scrollTop = drag\.scrollTop - \(event\.clientY - drag\.y\)/);
  assert.match(rendererStyles, /\.interactive-response-expand-trigger \{[^}]*cursor: pointer;/);
  assert.doesNotMatch(rendererStyles, /\.interactive-response-content \{[^}]*cursor: zoom-in;/);
  assert.doesNotMatch(rendererStyles, /\.interactive-response-expand-trigger \{[^}]*cursor: zoom-in;/);
  assert.match(rendererSource, /setPointerCapture/);
  assert.match(rendererSource, /changeZoom\(zoom \* \(event\.deltaY > 0 \? 0\.9 : 1\.1\)\)/);
  assert.match(rendererStyles, /\.response-zoom-viewport[\s\S]*cursor: grab/);
  assert.match(rendererStyles, /touch-action: none/);
});

test("safe Markdown images render inline and open a large viewer", () => {
  assert.match(turnSource, /<InlineMarkdownImage src=\{safeSrc\} alt=\{alt \|\| ""\} \/>/);
  assert.match(rendererSource, /export function InlineMarkdownImage/);
  assert.match(rendererSource, /className="inline-image-backdrop"/);
  assert.match(rendererSource, /className="inline-markdown-image-caption"/);
  assert.doesNotMatch(rendererSource, /<figure className="inline-markdown-image">/);
  assert.doesNotMatch(turnSource, />이미지: \{alt \|\| safeSrc\}<\/a>/);
});
