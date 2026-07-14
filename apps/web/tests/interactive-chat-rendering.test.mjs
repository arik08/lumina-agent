import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [turnSource, rendererSource, rendererStyles] = await Promise.all([
  readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/components/InteractiveResponse.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/components/InteractiveResponse.css", import.meta.url), "utf8"),
]);

test("chat renders Mermaid and structured charts as native interactive blocks", () => {
  assert.match(turnSource, /language === "mermaid" \|\| language === "mmd"[\s\S]*?<MermaidDiagram source=\{source\}/);
  assert.match(turnSource, /language === "lumina-chart"[\s\S]*?<InteractiveChart source=\{source\}/);
  assert.match(rendererSource, /securityLevel: "strict"/);
  assert.match(rendererSource, /export function parseInteractiveChart/);
  assert.match(rendererSource, /onPointerMove=\{selectFromPointer\}/);
  assert.match(rendererSource, /event\.key !== "ArrowLeft" && event\.key !== "ArrowRight"/);
});

test("Mermaid and structured charts expose a zoomable, pannable dialog", () => {
  assert.match(rendererSource, /function ZoomViewer/);
  assert.match(rendererSource, /aria-label="Mermaid 다이어그램 확대"/);
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
