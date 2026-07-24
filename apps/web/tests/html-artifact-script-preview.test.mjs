import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const appSource = read("../src/App.tsx");
const previewSource = read("../src/components/ArtifactHtmlPreview.tsx");
const previewStyles = read("../src/components/ArtifactHtmlPreview.css");
const previewBridge = read("../public/artifact-preview-bridge.js");
const interactiveResponseSource = read("../src/components/InteractiveResponse.tsx");
const visualArtifactSkillSource = read("../../../extensions/skills/visual-artifact/SKILL.md");

test("HTML Artifact preview paints loading feedback before mounting its streamed iframe", () => {
  assert.match(appSource, /const ArtifactHtmlPreview = lazy\(\(\) => import\("\.\/components\/ArtifactHtmlPreview"\)/);
  assert.match(appSource, /<Suspense fallback=\{<div className="artifact-loading" role="progressbar" aria-label="HTML 미리보기 준비 중"/);
  assert.match(appSource, /previewUrl=\{artifactEditing \? null : artifactPreviewUrl\}/);
  assert.match(previewSource, /setFrameContent\(null\);[\s\S]*?requestAnimationFrame\(\(\) => \{/);
  assert.match(previewSource, /srcDoc: autoHeight \? withAutoHeightBridge\(previewSource\) : previewSource/);
  assert.match(previewSource, /role="progressbar" aria-label="HTML 미리보기 준비 중"/);
  assert.match(previewSource, /sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-popups allow-popups-to-escape-sandbox"/);
  assert.doesNotMatch(previewSource, /allow-scripts allow-same-origin/);
  assert.match(previewSource, /src=\{frameContent\.src\}/);
  assert.match(previewStyles, /\.artifact-preview-frame \{[^}]*background: #fff;[^}]*color-scheme: light;/s);
  assert.match(previewStyles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("HTML Artifact preview can hand scrolling to its parent without weakening the sandbox", () => {
  assert.match(previewSource, /const artifactPreviewHeightMessage = "lumina:artifact-preview-height"/);
  assert.match(previewSource, /new ResizeObserver\(publish\)\.observe\(document\.documentElement\)/);
  assert.match(previewSource, /event\.source !== frameRef\.current\?\.contentWindow/);
  assert.match(previewSource, /scrolling=\{autoHeight \? "no" : undefined\}/);
  assert.match(previewStyles, /\.artifact-preview-shell\.is-auto-height \{[^}]*height: auto;[^}]*min-height: 0;/);
  assert.match(previewStyles, /\.artifact-preview-frame\.is-auto-height \{[^}]*min-height: 0;[^}]*overflow: hidden;/);
});

test("HTML Artifact preview bridge preserves clickable citations without cloning the report in React", () => {
  assert.match(previewBridge, /sup\.source-ref \{[^}]*vertical-align:baseline;/s);
  assert.match(previewBridge, /a\.source-ref, sup\.source-ref > a/);
  assert.match(visualArtifactSkillSource, /\.source-ref:hover \{ text-decoration:none; \}/);
  assert.match(previewBridge, /link\.textContent = markers\[number - 1\]/);
  assert.match(previewBridge, /link\.target = "_blank"/);
  assert.match(previewBridge, /card\.setAttribute\("aria-label", "출처 링크"\)/);
  assert.match(previewBridge, /sourceLink\.textContent = link\.href/);
  assert.doesNotMatch(previewSource, /DOMParser|cloneNode/);
});

test("HTML Artifact Mermaid blocks render sequentially through the bundled renderer", () => {
  assert.match(previewSource, /let renderQueue = Promise\.resolve\(\)/);
  assert.match(previewSource, /renderQueue = renderQueue\.then\(async \(\) =>/);
  assert.match(previewSource, /await import\("\.\/InteractiveResponse"\)/);
  assert.match(previewBridge, /const renderNextMermaid = \(\) =>/);
  assert.match(previewBridge, /if \(pendingMermaid \|\| mermaidIndex >= rawMermaid\.length\) return/);
  assert.match(previewBridge, /parent\.postMessage\(\{ type: "lumina:artifact-mermaid-request"/);
  assert.match(previewBridge, /pendingMermaid = null;[\s\S]*?renderNextMermaid\(\)/);
  assert.match(previewBridge, /new MutationObserver\(scheduleEnhanceZoom\)/);
  assert.match(previewBridge, /closest\('a\[href\^="#"\]'\)/);
  assert.match(previewBridge, /target\.scrollIntoView\(\{ block: "start" \}\)/);
  assert.match(previewBridge, /aria-label", "Mermaid 다이어그램 크게 보기"/);
  assert.match(previewBridge, /const clonedSvg = svg\.cloneNode\(true\)/);
  assert.match(previewBridge, /clonedSvg\.setAttribute\("width", String\(viewBox\[2\]\)\)/);
  assert.match(previewBridge, /clonedSvg\.setAttribute\("height", String\(viewBox\[3\]\)\)/);
  assert.match(previewBridge, /changeZoom\(zoom \* \(event\.deltaY > 0 \? \.9 : 1\.1\)\)/);
  assert.match(previewBridge, /viewport\.addEventListener\("pointermove"/);
  assert.match(visualArtifactSkillSource, /Lumina automatically adds a visible expand button/);
  assert.match(visualArtifactSkillSource, /Do not add a CDN script or initialize Mermaid/);
});

test("HTML direct editing sends cheap dirty signals and serializes only when source or save needs it", () => {
  assert.match(appSource, /document\.addEventListener\('input', publishArtifactEditDirty\)/);
  assert.match(appSource, /parent\.postMessage\(\{ type: '\$\{artifactPreviewEditDirtyMessage\}' \}, '\*'\)/);
  assert.match(appSource, /event\.data\?\.type === '\$\{artifactPreviewEditSnapshotRequest\}'/);
  assert.match(appSource, /nextTab === "source"[\s\S]*?const source = await requestArtifactEditSnapshot\(\);[\s\S]*?setArtifactDraft\(source\)/);
  assert.match(appSource, /artifactVersion\?\.sourceAvailable[\s\S]*?api\.artifacts\.getVersion\([\s\S]*?true/);
  assert.match(appSource, /const sourceText = await requestArtifactEditSnapshot\(\);[\s\S]*?api\.artifacts\.saveDraft/);
  assert.match(appSource, /const sourceText = await requestArtifactEditSnapshot\(\);[\s\S]*?api\.artifacts\.saveVersion/);
  assert.doesNotMatch(appSource, /document\.addEventListener\('input', publishArtifactEdit\)/);
  assert.doesNotMatch(appSource, /requestIdleCallback\(checkpoint/);
});

test("HTML Artifact generation keeps the user-designated visual palette", () => {
  for (const color of ["#3288bd", "#66c2a5", "#e6f598", "#d53e4f", "#9e0142", "#f46d43", "#fdae61", "#fee08b", "#abdda4", "#5e4fa2"]) {
    assert.match(visualArtifactSkillSource, new RegExp(color));
  }
  assert.match(visualArtifactSkillSource, /designated MyHarness palette as the required default visual palette/);
  assert.match(visualArtifactSkillSource, /--viz-blue/);
  assert.match(visualArtifactSkillSource, /--viz-purple/);
  assert.match(visualArtifactSkillSource, /Do not silently replace it with Lumina's app cobalt or an all-gray theme/);
});

test("HTML Artifact reports plan substantive visualizations before prose", () => {
  assert.match(visualArtifactSkillSource, /build a visual inventory from the evidence/);
  assert.match(visualArtifactSkillSource, /Maximize meaningful visualization, not the raw number of graphics/);
  assert.match(visualArtifactSkillSource, /KPI cards, badges, icons, colored headings, and decorative shapes do not count as substantive visualizations/);
  assert.match(visualArtifactSkillSource, /at least one substantive visualization in the first screen/);
  assert.match(visualArtifactSkillSource, /Do not invent precision to satisfy the visual plan/);
  assert.match(visualArtifactSkillSource, /name the reader question each one answers/);
});

test("HTML Artifact Mermaid colors retain fallbacks outside the app theme root", () => {
  assert.match(interactiveResponseSource, /themedSvg\.replaceAll\(value, `var\(\$\{tokenName\}, \$\{value\}\)`\)/);
});

test("visual Artifact report drafting starts inside create_report", () => {
  assert.match(visualArtifactSkillSource, /start `create_report` when report drafting begins/);
  assert.match(visualArtifactSkillSource, /stream the complete document directly through `html_source`/);
  assert.match(visualArtifactSkillSource, /Do not compose the full report in reasoning or chat text first/);
});
