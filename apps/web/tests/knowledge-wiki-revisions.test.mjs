import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const wiki = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeWiki.tsx", import.meta.url),
  "utf8",
);

test("Knowledge Wiki exposes durable manual edits and revision comparison", () => {
  assert.match(api, /listKnowledgePageRevisions/);
  assert.match(api, /updateKnowledgePage/);
  assert.match(wiki, /expectedRevision: page\.currentRevision\.revisionNumber/);
  assert.match(wiki, /AI 재생성 시에도 유지됩니다/);
  assert.match(wiki, /변경 이력/);
  assert.match(wiki, /knowledge-wiki-compare/);
});
