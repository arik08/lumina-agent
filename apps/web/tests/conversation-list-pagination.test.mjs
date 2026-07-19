import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspace = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");
const recentItems = await readFile(new URL("../src/components/SidebarRecentItems.tsx", import.meta.url), "utf8");
const app = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

test("conversation sidebar loads cursor pages in bounded batches", () => {
  assert.match(workspace, /CONVERSATION_LIST_PAGE_SIZE = 20/);
  assert.match(workspace, /cursor,\s*limit: CONVERSATION_LIST_PAGE_SIZE/s);
  assert.match(workspace, /page\.items\.filter\(\(item\) => !currentIds\.has\(item\.id\)\)/);
  assert.match(workspace, /setConversationNextCursor\(page\.nextCursor\)/);
  assert.match(workspace, /loadingMoreConversationsRef\.current/);
});

test("conversation sidebar preloads before reaching the bottom", () => {
  assert.match(recentItems, /Math\.max\(132, list\.clientHeight \* 0\.35\)/);
  assert.match(recentItems, /list\.scrollHeight - list\.scrollTop - list\.clientHeight <= prefetchDistance/);
  assert.match(recentItems, /hasMore &&[\s\S]*onLoadMore\?\.\(\)/);
  assert.match(app, /hasMore=\{workspace\.hasMoreConversations\}/);
  assert.match(app, /onLoadMore=\{\(\) => void workspace\.loadMoreConversations\(\)\}/);
});
