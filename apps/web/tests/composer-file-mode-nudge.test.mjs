import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("file mode warns through a body-level anchored layer for conversational drafts", () => {
  assert.match(app, /workspace\.settings\?\.outputMode === "file"/);
  assert.match(app, /!explicitlyRequestsArtifact\(draft\)/);
  assert.match(app, /<GlobalTooltipLayer[\s\S]*className="file-mode-nudge-layer"/);
  assert.match(app, /ref=\{value === "file" \? fileModeButtonRef : undefined\}/);
  assert.match(app, /파일 모드가 선택되어 있습니다/);
  assert.doesNotMatch(styles, /\.file-mode-nudge-layer\s*\{[^}]*position:/, "layer positioning must remain owned by the global portal primitive");
});

test("file mode emphasis does not alter composer layout and respects reduced motion", () => {
  assert.match(styles, /button\.is-file-mode-nudged\s*\{[^}]*box-shadow:/);
  assert.doesNotMatch(styles, /button\.is-file-mode-nudged\s*\{[^}]*(?:width|height|margin|padding):/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce[^}]*is-file-mode-nudged[^}]*animation:\s*none/s);
});
