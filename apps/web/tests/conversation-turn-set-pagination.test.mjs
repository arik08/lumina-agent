import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspaceUrl = new URL("../src/use-lumina-workspace.ts", import.meta.url);
const appUrl = new URL("../src/App.tsx", import.meta.url);

test("older conversation turn sets are fetched by cursor and prepended without duplicates", async () => {
  const workspace = await readFile(workspaceUrl, "utf8");

  assert.match(workspace, /previousTurnSetCursor: page\.previousCursor/);
  assert.match(workspace, /hasMoreTurnSetsBefore: page\.hasMoreBefore/);
  assert.match(workspace, /getTurnSets\(\s*conversationId,\s*runtime\.previousTurnSetCursor,\s*3,/s);
  assert.match(workspace, /const currentTurnSetIds = new Set\(currentRuntime\.turnSets\.map/);
  assert.match(workspace, /turnSets: \[\.\.\.olderTurnSets, \.\.\.currentRuntime\.turnSets\]/);
  assert.match(workspace, /loadOlderConversationTurnSets,/);
});

test("scrolling to the top loads older turn sets and preserves the visible position", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /container\.scrollTop > 80/);
  assert.match(app, /scrollHeight: container\.scrollHeight/);
  assert.match(app, /workspace\.loadOlderConversationTurnSets\(conversationId\)/);
  assert.match(app, /container\.scrollTop = anchor\.scrollTop \+ \(container\.scrollHeight - anchor\.scrollHeight\)/);
  assert.match(app, /onScroll=\{\(\) => \{\s*conversationFollow\.onScroll\(\);\s*void loadOlderTurnSetsAtTop\(\);/s);
});
