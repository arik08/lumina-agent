import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const paths = {
  app: new URL("../src/App.tsx", import.meta.url),
  actions: new URL("../src/components/ArtifactPreviewActions.tsx", import.meta.url),
  preview: new URL("../src/components/ArtifactHtmlPreview.tsx", import.meta.url),
  capture: new URL("../src/artifact-capture.ts", import.meta.url),
  clipboard: new URL("../src/clipboard.ts", import.meta.url),
  bridge: new URL("../public/artifact-preview-bridge.js", import.meta.url),
};

test("HTML Artifact full-image copy is independent and immediately precedes download", async () => {
  const [app, actions] = await Promise.all([
    readFile(paths.app, "utf8"),
    readFile(paths.actions, "utf8"),
  ]);
  assert.match(app, /onCapture=\{artifactVersion\?\.mimeType === "text\/html" \? copyArtifactImage : undefined\}/);
  assert.match(app, /captureDisabled=\{artifactTab !== "preview" \|\| artifactEditing \|\| artifactLoading\}/);
  assert.match(actions, /aria-label=\{captureState === "capturing" \? "전체 이미지 생성 중"/);
  assert.match(actions, /className=\{`artifact-capture-control[\s\S]*?<button\s+className="artifact-file-control/s);
  assert.match(actions, /<Camera size=\{17\}/);
  assert.match(actions, /<Download size=\{17\}/);
});

test("HTML Artifact capture keeps the preview sandbox and clones through the bridge", async () => {
  const [preview, capture, bridge] = await Promise.all([
    readFile(paths.preview, "utf8"),
    readFile(paths.capture, "utf8"),
    readFile(paths.bridge, "utf8"),
  ]);
  assert.match(preview, /artifactCaptureRequestMessage/);
  assert.match(preview, /event\.source !== target/);
  assert.match(preview, /captureArtifactSnapshot\(event\.data as ArtifactCaptureSnapshot\)/);
  assert.match(preview, /sandbox="allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-popups allow-popups-to-escape-sandbox"/);
  assert.doesNotMatch(preview, /allow-scripts allow-same-origin/);
  assert.match(bridge, /const captureRequestType = "lumina:artifact-capture-request"/);
  assert.match(bridge, /snapshot\.querySelectorAll\("script"\)/);
  assert.match(bridge, /base\.href = document\.baseURI/);
  assert.match(bridge, /canvas\.toDataURL\("image\/png"\)/);
  assert.match(capture, /import html2canvas from "html2canvas"/);
  assert.match(capture, /artifactCaptureMaxPixels = 50_000_000/);
  assert.match(capture, /const stableHeightLimit = Math\.ceil\(shortestHeight \* 1\.08\)/);
  assert.match(capture, /contentHeight <= stableHeightLimit/);
  assert.doesNotMatch(capture, /growth <= plateauThreshold/);
  assert.match(capture, /scale: 1/);
  assert.match(capture, /frame\.remove\(\)/);
});

test("PNG clipboard uses the browser on secure origins and host fallback on HTTP", async () => {
  const clipboard = await readFile(paths.clipboard, "utf8");
  assert.match(clipboard, /window\.isSecureContext !== false/);
  assert.match(clipboard, /new ClipboardItem\(\{/);
  assert.match(clipboard, /"image\/png": png/);
  assert.match(clipboard, /await uploadFallback\(await png\)/);
});

test("the development proxy forwards the real LAN client address for clipboard safety", async () => {
  const vite = await readFile(new URL("../vite.config.ts", import.meta.url), "utf8");
  assert.match(vite, /"\/api":\s*\{[\s\S]*?xfwd:\s*true/);
});
