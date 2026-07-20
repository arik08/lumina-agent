import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = [
  readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8"),
  readFileSync(new URL("../src/components/ComposerControls.tsx", import.meta.url), "utf8"),
].join("\n");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("file mode warning follows the LLM JSON decision through a body-level speech bubble", () => {
  assert.match(app, /workspace\.settings\?\.outputMode === "file"/);
  assert.match(app, /draft\.trim\(\)\.length === 0/);
  assert.match(app, /activeRun\?\.outputIntent\?\.fileCreationRequested === false/);
  assert.doesNotMatch(app, /explicitArtifactRequestPattern|setTimeout\(syncVisibility,\s*420\)/);
  assert.match(app, /<GlobalTooltipLayer[\s\S]*className="file-mode-nudge-layer"/);
  assert.match(app, /controlRef=\{fileModeButtonRef\}/);
  assert.match(app, /ref=\{triggerRef\}/);
  assert.match(app, /파일 생성 요청이 아닌 것 같아요/);
  assert.doesNotMatch(styles, /\.file-mode-nudge-layer\s*\{[^}]*position:/, "layer positioning must remain owned by the global portal primitive");
  assert.match(styles, /\.file-mode-nudge-layer::after\s*\{[^}]*left:\s*var\(--global-tooltip-anchor-x\)/);
  assert.match(styles, /\.file-mode-nudge-layer\[data-placement="above"\]::after/);
});

test("file mode emphasis does not alter composer layout and respects reduced motion", () => {
  assert.match(styles, /\.artifact-length-trigger\.is-file-mode-nudged\s*\{[^}]*box-shadow:/);
  assert.doesNotMatch(styles, /\.artifact-length-trigger\.is-file-mode-nudged\s*\{[^}]*(?:width|height|margin|padding):/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce[^}]*is-file-mode-nudged[^}]*animation:\s*none/s);
});

test("file mode returns to auto only after a message is accepted", () => {
  const sendMessage = app.match(/const sendMessage = async \(queueNext = false\) => \{([\s\S]*?)\n  \};/)?.[1] ?? "";
  const accepted = sendMessage.indexOf("if (!mode) return;");
  const reset = sendMessage.indexOf('if (resetFileModeAfterSend) void workspace.selectOutputMode("auto");');

  assert.match(sendMessage, /const resetFileModeAfterSend = workspace\.settings\?\.outputMode === "file";/);
  assert.ok(accepted >= 0 && reset > accepted, "file mode should reset only after sendMessage succeeds");
});
