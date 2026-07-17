import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const adminView = await readFile(new URL("../src/components/AdminView.tsx", import.meta.url), "utf8");
const apiSource = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");

test("admin conversation export downloads an xlsx with the active filters", () => {
  assert.match(adminView, /aria-label="대화 Excel 내보내기"/);
  assert.match(adminView, /api\.admin\.exportConversations\(\{\s*query,\s*feedbackOnly,\s*limit: conversationLimit,/s);
  assert.match(adminView, /URL\.createObjectURL\(download\.blob\)/);
  assert.match(adminView, /anchor\.download = download\.fileName/);
  assert.match(apiSource, /fetchApi\("\/admin\/conversations\/export\.xlsx"/);
  assert.match(apiSource, /feedback_only: filters\.feedbackOnly \|\| undefined/);
});
