import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);

test("an uncached session renders a restoring state instead of the new-chat welcome", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /const restoringActiveConversation = Boolean\([\s\S]*?activeConversationId && !activeRuntime\.loaded && !activeRuntime\.error/);
  assert.match(app, /const showNewConversationWelcome = activeRuntime\.turnSets\.length === 0 && \([\s\S]*?!workspace\.activeConversationId \|\| activeRuntime\.loaded/);
  assert.match(app, /aria-busy=\{restoringActiveConversation\}/);
  assert.match(app, /\{restoringActiveConversation && <div className="conversation-loading"/);
  assert.match(app, /\{showNewConversationWelcome && \([\s\S]*?<StarterPrompts/);
  assert.doesNotMatch(app, /!activeRuntime\.loading && activeRuntime\.turnSets\.length === 0/);
});
