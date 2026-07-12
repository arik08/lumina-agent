import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("composer trigger buttons toggle their picker without inserting duplicate tokens", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /if \(composerTrigger\?\.trigger === trigger\) \{[\s\S]*?setComposerTrigger\(null\);[\s\S]*?return;[\s\S]*?\}/);
  assert.match(app, /const existingTrigger = findComposerTrigger\(draft, caret\);/);
});

test("starting a new conversation closes and resets the composer picker", async () => {
  const app = await readFile(appUrl, "utf8");
  const startNewConversation = app.match(/const startNewConversation = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[workspace\.createConversation\]\);/)?.[1] ?? "";

  assert.match(startNewConversation, /setComposerTrigger\(null\);/);
  assert.match(startNewConversation, /setComposerSuggestions\(\[\]\);/);
  assert.match(startNewConversation, /setSuggestionIndex\(0\);/);
  assert.ok(
    startNewConversation.indexOf("setComposerTrigger(null);") < startNewConversation.indexOf("await workspace.createConversation();"),
    "the picker must close even when the workspace reuses the current untouched conversation",
  );
});

test("send button tooltip is anchored to the composer right edge", async () => {
  const styles = await readFile(stylesUrl, "utf8");

  assert.match(styles, /\.composer-footer \.send-button::after\s*\{[^}]*right:\s*0;[^}]*left:\s*auto;/);
  assert.match(styles, /\.composer-footer \.send-button:hover::after,[\s\S]*?\.composer-footer \.send-button:focus-visible::after\s*\{\s*transform:\s*translateY\(0\);/);
});
