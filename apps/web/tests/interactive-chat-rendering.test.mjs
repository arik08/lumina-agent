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
  assert.match(rendererSource, /estimatedLabelWidth <= Math\.max\(availableWidth - 80, 240\)/);
  assert.match(rendererSource, /axisLabel: \{ interval: 0, rotate: 30, \.\.\.axisLabel \}/);
  assert.match(rendererSource, /withReadableCategoryAxes\(spec\.option, container\.clientWidth\)/);
});

test("streaming diagram, chart, and table placeholders sweep light across the card background", () => {
  assert.match(turnSource, /kind === "mermaid" \? "다이어그램 작성 중" : kind === "chart" \? "인터랙티브 차트 작성 중" : "표 작성 중"/);
  assert.match(turnSource, /className={`stream-block-pending is-\${kind}`} role="status"/);
  assert.match(globalStyles, /\.stream-block-pending::before \{[^}]*linear-gradient[^}]*animation: stream-block-light-sweep/s);
  assert.doesNotMatch(globalStyles, /\.stream-block-pending > span \{[^}]*background-clip: text/s);
  assert.match(globalStyles, /@keyframes stream-block-light-sweep/);
  assert.match(globalStyles, /\.stream-block-pending::before \{[^}]*left: -45%; width: 45%;[^}]*animation: stream-block-light-sweep 1\.8s linear infinite/);
  assert.match(globalStyles, /@keyframes stream-block-light-sweep \{ from \{ transform: translate3d\(0, 0, 0\); \} to \{ transform: translate3d\(322\.222%, 0, 0\); \} \}/);
  assert.match(globalStyles, /@media \(prefers-reduced-motion: reduce\) \{ \.stream-block-pending::before \{[^}]*animation: none;[^}]*\} \}/);
});

test("Mermaid loads on demand, deduplicates active renders, and stays mounted while Markdown grows", () => {
  assert.match(rendererSource, /let mermaidModulePromise: Promise<typeof import\("mermaid"\)> \| null = null/);
  assert.match(rendererSource, /mermaidModulePromise = import\("mermaid"\)/);
  assert.doesNotMatch(rendererSource, /requestIdleCallback\(preloadMermaid/);
  assert.match(rendererSource, /const mermaidRenderJobs = new Map/);
  assert.match(rendererSource, /const activeJob = mermaidRenderJobs\.get\(cacheKey\)/);
  assert.match(turnSource, /const markdownCodeComponent: NonNullable<Components\["code"\]>/);
  assert.match(turnSource, /code: markdownCodeComponent/);
  assert.doesNotMatch(turnSource, /code: \(\{ className, children \}\) =>/);
});

test("Markdown code blocks provide inline copy feedback without changing interactive blocks", () => {
  assert.match(turnSource, /function MarkdownCodeBlock\(\{ children \}/);
  assert.match(turnSource, /preRef\.current\?\.querySelector\("code"\)\?\.textContent/);
  assert.match(turnSource, /await copyText\(source\)/);
  assert.match(turnSource, /copyState === "copied" \? <Check size=\{14\}/);
  assert.match(turnSource, /className="visually-hidden" role="status" aria-live="polite"/);
  assert.match(turnSource, /language === "mermaid" \|\| language === "mmd" \|\| language === "lumina-chart"/);
  assert.match(turnSource, /pre: markdownPreComponent/);
  assert.match(globalStyles, /\.markdown-code-copy \{[^}]*position: absolute;[^}]*top: 6px; right: 6px;[^}]*width: 28px; height: 28px;/);
  assert.match(globalStyles, /\.markdown-code-copy \{[^}]*border: 0;/);
  assert.match(globalStyles, /\.markdown-code-copy \{[^}]*background: transparent;/);
  assert.match(globalStyles, /\.markdown-code-copy:hover \{ background: transparent;/);
  assert.match(globalStyles, /\.markdown-code-copy\.is-copied,[\s\S]*?color: var\(--success\);/);
});

test("user messages expose an external copy action with inline feedback", () => {
  assert.match(turnSource, /function UserMessageCopyButton\(\{ text \}/);
  assert.match(turnSource, /await copyText\(text\)/);
  assert.match(turnSource, /copyState === "copied" \? <Check size=\{14\}/);
  assert.match(turnSource, /<div className="user-message-row">[\s\S]*?<UserMessageCopyButton text=\{message\.text\} \/>[\s\S]*?<div className="user-message">/);
  assert.match(globalStyles, /\.user-message-row \{[^}]*display: flex;[^}]*align-items: flex-start;[^}]*gap: 8px;/);
  assert.match(globalStyles, /\.user-message-copy \{[^}]*width: 28px; height: 28px;[^}]*margin-top: 8px;[^}]*background: transparent;[^}]*color: var\(--faint\);/);
  assert.match(globalStyles, /\.user-message-copy:hover \{ background: transparent; color: var\(--muted\);/);
  assert.match(globalStyles, /\.user-message-copy\.is-copied,[\s\S]*?color: var\(--success\);/);
});

test("Mermaid preserves authored semantic fills and repairs only unreadable node text", () => {
  for (const color of ["#3288bd", "#66c2a5", "#e6f598", "#d53e4f", "#9e0142", "#f46d43", "#fdae61", "#fee08b", "#abdda4", "#5e4fa2"]) {
    assert.match(rendererSource, new RegExp(color));
  }
  assert.match(rendererSource, /pie10: artifactVisualPalette\.purple/);
  assert.match(rendererSource, /cScale9: artifactVisualPalette\.purple/);
  assert.match(rendererSource, /plotColorPalette: artifactVisualPaletteSequence\.join\(","\)/);
  assert.match(rendererSource, /const themedResult = \{ \.\.\.result, svg: bindMermaidThemeTokens/);
  assert.match(rendererSource, /return themedResult/);
  assert.match(rendererSource, /ensureMermaidNodeTextContrast\(renderedSvg\)/);
  assert.doesNotMatch(rendererSource, /inferMermaidNodeTone|decorateMermaidSvg|luminaTone/);
  assert.doesNotMatch(rendererStyles, /data-lumina-tone|--mermaid-node-fill|--mermaid-node-stroke/);
  assert.doesNotMatch(rendererStyles, /\.mermaid-surface svg :is\(\.edgePath|\.mermaid-surface svg marker/);
});

test("Mermaid uses cobalt tokens for the default node fill and border", () => {
  assert.match(rendererSource, /document\.querySelector<HTMLElement>\("\.app-shell"\) \?\? document\.documentElement/);
  assert.match(rendererSource, /primaryColor: token\("--cobalt-pale", "#edf2fb"\)/);
  assert.match(rendererSource, /primaryBorderColor: token\("--cobalt", "#3f66c9"\)/);
  assert.match(rendererSource, /function bindMermaidThemeTokens/);
  assert.match(rendererSource, /themedSvg\.replaceAll\(value, `var\(\$\{tokenName\}, \$\{value\}\)`\)/);
  assert.match(rendererSource, /svg: bindMermaidThemeTokens\(result\.svg, appearance\.tokenBindings\)/);
  assert.doesNotMatch(rendererSource, /MutationObserver\(\(\) => setThemeRevision/);
});

test("tall Mermaid workflows keep readable geometry inside a bounded scroll surface", () => {
  assert.match(rendererStyles, /\.mermaid-surface \{[\s\S]*max-height: min\(640px, 68vh\);[\s\S]*overflow: auto;[\s\S]*overscroll-behavior: contain;/);
  assert.match(rendererStyles, /\.mermaid-surface:not\(\.is-expanded\) \{[^}]*overscroll-behavior: auto;[^}]*cursor: grab;[^}]*touch-action: none;/);
  assert.match(rendererStyles, /\.mermaid-surface\.is-dragging \{[^}]*cursor: grabbing;[^}]*user-select: none;/);
  assert.match(rendererStyles, /\.mermaid-surface svg \{[\s\S]*width: auto;[\s\S]*max-width: 100%;[\s\S]*height: auto;/);
  assert.match(rendererStyles, /\.mermaid-surface:not\(\.is-expanded\) svg \{[^}]*transition: width 150ms var\(--ease-out-quint, ease-out\);/);
  assert.match(rendererStyles, /\.mermaid-surface\.is-expanded \{[\s\S]*max-height: none;[\s\S]*overflow: hidden;/);
  assert.doesNotMatch(rendererStyles, /\.mermaid-surface svg \{[\s\S]*max-height: 660px;/);
  assert.doesNotMatch(globalStyles, /\.mermaid-diagram svg/);
});

test("chat Mermaid cards provide button-only zoom controls beside the expand button", () => {
  assert.match(rendererSource, /const \[zoom, setZoom\] = useState\(1\)/);
  assert.match(rendererSource, /const \[initialZoom, setInitialZoom\] = useState\(1\)/);
  assert.match(rendererSource, /setZoom\(clamp\(next, 0\.3, 2\)\)/);
  assert.match(rendererSource, /baseWidthRef\.current = naturalWidth/);
  assert.match(rendererSource, /const fitZoom = Math\.min\(widthFit, heightFit, 1\)/);
  assert.match(rendererSource, /expanded[\s\S]*?clamp\(fitZoom, 0\.3, 1\)/);
  assert.match(rendererSource, /clamp\(Math\.floor\(fitZoom \* 10\) \/ 10, 0\.7, 1\)/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 축소"[\s\S]*?zoom - 0\.2/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 배율 초기화"[\s\S]*?setZoom\(initialZoom\)/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 확대"[\s\S]*?zoom \+ 0\.2/);
  assert.match(rendererSource, /<MermaidSurface source=\{source\} zoom=\{zoom\} onInitialFit=\{applyInitialFit\} \/>/);
  assert.match(rendererSource, /className="interactive-response-expand-label" aria-label="Mermaid 다이어그램 크게 보기" onClick=\{\(\) => setExpanded\(true\)\}>Mermaid<\/button>/);
  assert.match(rendererSource, /renderedSvg\.style\.maxWidth = "none"/);
  assert.match(rendererSource, /const positionAtFlowStart = \(surface: HTMLDivElement, renderedSvg: SVGSVGElement\)/);
  assert.match(rendererSource, /source\.match\(\/\^\\s\*\(\?:flowchart\|graph\)\\s\+\(TB\|TD\|BT\|LR\|RL\)\\b\/im\)/);
  assert.match(rendererSource, /querySelectorAll<SVGGraphicsElement>\("g\.node"\)/);
  assert.match(rendererSource, /positionAtFlowStart\(surface, renderedSvg\)/);
  assert.doesNotMatch(rendererSource, /surface\.scrollLeft = Math\.max\(\(surface\.scrollWidth - surface\.clientWidth\) \/ 2, 0\)/);
  assert.doesNotMatch(rendererSource, /<MermaidSurface source=\{source\} zoom=\{zoom\}[^>]*onWheel/);
  assert.match(rendererStyles, /\.mermaid-inline-zoom-controls \{[\s\S]*?border-right: 1px solid var\(--line\);/);
  assert.match(rendererStyles, /\.interactive-response-toolbar button\.mermaid-inline-zoom-value \{[^}]*width: 3em;[^}]*flex: 0 0 3em;[^}]*white-space: nowrap;/s);
  assert.match(rendererStyles, /\.interactive-response-toolbar \.interactive-response-expand-label \{[\s\S]*?flex: 1;[\s\S]*?justify-content: flex-start;[\s\S]*?cursor: pointer;/);
  assert.match(rendererStyles, /\.interactive-response-toolbar \.interactive-response-expand-label:hover \{[^}]*border-color: transparent;[^}]*background: transparent;[^}]*\}/);
});

test("Mermaid and structured charts expose a zoomable, pannable dialog", () => {
  assert.match(rendererSource, /function ZoomViewer/);
  assert.match(rendererSource, /document\.querySelector\("\.app-shell\.theme-dark"\) \? " theme-dark" : ""/);
  assert.match(rendererSource, /className=\{`response-zoom-backdrop\$\{themeClassName\}`\}/);
  assert.match(globalStyles, /\.response-zoom-backdrop\.theme-dark,[\s\S]*?\.app-shell\.theme-dark/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 크게 보기"/);
  assert.match(rendererSource, /className="response-zoom-title"[\s\S]*?aria-label=\{`\$\{title\} 확대 보기 닫기`\}[\s\S]*?onClick=\{onClose\}/);
  assert.match(rendererStyles, /\.response-zoom-title \{[^}]*cursor: pointer;/);
  assert.match(rendererSource, /className="interactive-response-expand-icon" aria-label="Mermaid 다이어그램 크게 보기"[\s\S]*?onClick=\{\(\) => setExpanded\(true\)\}/);
  assert.match(rendererSource, /event\.currentTarget\.scrollLeft = drag\.scrollLeft - \(event\.clientX - drag\.x\)/);
  assert.match(rendererSource, /event\.currentTarget\.scrollTop = drag\.scrollTop - \(event\.clientY - drag\.y\)/);
  assert.match(rendererSource, /const shouldScrollConversation = \(event\.deltaY < 0 && atTop\) \|\| \(event\.deltaY > 0 && atBottom\)/);
  assert.match(rendererSource, /if \(!shouldScrollConversation\) return;[\s\S]*?event\.preventDefault\(\)/);
  assert.doesNotMatch(rendererSource, /surface\.scrollTop \+= event\.deltaY/);
  assert.match(rendererSource, /surface\.closest<HTMLElement>\("\.conversation-scroll"\)\?\.scrollBy\(\{ top: event\.deltaY \}\)/);
  assert.doesNotMatch(rendererStyles, /\.interactive-response-content \{[^}]*cursor: zoom-in;/);
  assert.match(rendererSource, /setPointerCapture/);
  assert.match(rendererSource, /changeZoom\(zoom \* \(event\.deltaY > 0 \? 0\.9 : 1\.1\)\)/);
  assert.match(rendererStyles, /\.response-zoom-viewport[\s\S]*cursor: grab/);
  assert.match(rendererStyles, /touch-action: none/);
  assert.match(rendererStyles, /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.mermaid-surface:not\(\.is-expanded\) svg[\s\S]*transition: none;/);
});

test("safe Markdown images render inline and open a large viewer", () => {
  assert.match(turnSource, /<InlineMarkdownImage src=\{safeSrc\} alt=\{alt \|\| ""\} \/>/);
  assert.match(rendererSource, /export function InlineMarkdownImage/);
  assert.match(rendererSource, /className="inline-image-backdrop"/);
  assert.match(rendererSource, /className="inline-markdown-image-caption"/);
  assert.doesNotMatch(rendererSource, /<figure className="inline-markdown-image">/);
  assert.doesNotMatch(turnSource, />이미지: \{alt \|\| safeSrc\}<\/a>/);
});
