import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const bindings = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeProjectBindings.tsx", import.meta.url),
  "utf8",
);

test("Knowledge Project bindings stay fixed until an explicit revision change", () => {
  assert.match(api, /listKnowledgeProjectBindings/);
  assert.match(api, /createKnowledgeProjectBinding/);
  assert.match(api, /updateKnowledgeProjectBinding/);
  assert.match(api, /deleteKnowledgeProjectBinding/);
  assert.match(bindings, /expectedRevision: binding\.bindingRevision/);
  assert.match(bindings, /새 revision은 자동 반영되지 않습니다/);
  assert.match(bindings, /confirmDeleteId === binding\.id/);
  assert.match(bindings, /고정 revision/);
});
