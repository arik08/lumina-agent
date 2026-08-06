import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("web search challenge progress remains visible without exposing the search backend", async () => {
  const conversationTurn = await read("../src/components/ConversationTurn.tsx");

  assert.match(conversationTurn, /const liveStatus = running \? execution\.resultSummary\[0\] : null;/);
  assert.match(conversationTurn, /return userFacingSystemText\(activity\.execution\.resultSummary\[0\]\);/);
  assert.match(conversationTurn, /<span aria-live="polite" role="status">\{toolCallGroupSummary\(toolActivities\)\}<\/span>/);
});
