import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspaceUrl = new URL("../src/use-lumina-workspace.ts", import.meta.url);
const appUrl = new URL("../src/App.tsx", import.meta.url);
const apiUrl = new URL("../src/api.ts", import.meta.url);

test("older conversation turn sets are fetched by cursor and prepended without duplicates", async () => {
  const workspace = await readFile(workspaceUrl, "utf8");

  assert.match(workspace, /previousTurnSetCursor: page\.previousCursor/);
  assert.match(workspace, /hasMoreTurnSetsBefore: page\.hasMoreBefore/);
  assert.match(workspace, /const pageSize = requestedQuestionIndex === null \? 3 : 20/);
  assert.match(workspace, /getTurnSets\(conversationId, cursor, pageSize\)/);
  assert.match(workspace, /requestedQuestionIndex < unloadedQuestionCount/);
  assert.match(workspace, /const currentTurnSetIds = new Set\(currentRuntime\.turnSets\.map/);
  assert.match(workspace, /turnSets: \[\.\.\.olderTurnSets, \.\.\.currentRuntime\.turnSets\]/);
  assert.match(workspace, /loadOlderConversationTurnSets,/);
});

test("approaching the top preloads older turn sets and preserves the visible position", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /Math\.max\(240, container\.clientHeight \* 0\.75\)/);
  assert.match(app, /container\.scrollTop > prefetchDistance/);
  assert.match(app, /scrollHeight: container\.scrollHeight/);
  assert.match(app, /workspace\.loadOlderConversationTurnSets\(conversationId\)/);
  assert.match(app, /workspace\.loadOlderConversationTurnSets\(conversationId, questionIndex\)/);
  assert.match(app, /container\.scrollTop = anchor\.scrollTop \+ \(container\.scrollHeight - anchor\.scrollHeight\)/);
  assert.match(app, /onScroll=\{\(\) => \{\s*conversationFollow\.onScroll\(\);\s*void loadOlderTurnSetsNearTop\(\);/s);
});

test("run snapshot batches respect the backend limit while loading distant history", async () => {
  const api = await readFile(apiUrl, "utf8");

  assert.match(api, /const uniqueRunIds = \[\.\.\.new Set\(runIds\)\]/);
  assert.match(api, /index \+= 20/);
  assert.match(api, /uniqueRunIds\.slice\(index, index \+ 20\)/);
  assert.match(api, /await Promise\.all\(chunks\.map/);
  assert.match(api, /return pages\.flat\(\)/);
});
