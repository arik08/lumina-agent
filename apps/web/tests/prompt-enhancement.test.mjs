import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);
const controlsUrl = new URL("../src/components/ComposerControls.tsx", import.meta.url);
const apiUrl = new URL("../src/api.ts", import.meta.url);

test("prompt enhancement uses the composer endpoint and never sends automatically", async () => {
  const app = await readFile(appUrl, "utf8");
  const api = await readFile(apiUrl, "utf8");
  const handler = app.match(/const enhanceComposerPrompt = async \([\s\S]*?\n  };/)?.[0] ?? "";

  assert.match(api, /request<PromptEnhancementResult>\("\/composer\/enhance"/);
  assert.match(handler, /api\.composer\.enhancePrompt\(/);
  assert.match(handler, /composerDraftRef\.current !== sourceText/);
  assert.match(handler, /writeComposerDraft\(result\.enhancedText\)/);
  assert.doesNotMatch(handler, /sendMessage\(/);
});

test("prompt enhancement menu provides four selectable edits and one apply action", async () => {
  const controls = await readFile(controlsUrl, "utf8");

  for (const option of ["structure", "evidence", "missing_context", "output_format"]) {
    assert.match(controls, new RegExp(`id: "${option}"`));
  }
  assert.match(controls, /role="menuitemcheckbox"/);
  assert.match(controls, /className="prompt-enhancement-apply"/);
  assert.match(controls, /onApply\(selected\)/);
});

test("prompt enhancement keeps explicit restore and reapply paths", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /const restoreOriginalPrompt = \(\) =>/);
  assert.match(app, /current\.view === "edited" && !current\.restoreArmed/);
  assert.match(app, /writeComposerDraft\(current\.original\)/);
  assert.match(app, /const reapplyEnhancedPrompt = \(\) =>/);
  assert.match(app, /writeComposerDraft\(promptEnhancementState\.enhanced\)/);
  assert.match(app, /현재 수정 내용도 사라집니다/);
});
