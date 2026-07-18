import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const bindings = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeProjectBindings.tsx", import.meta.url),
  "utf8",
);
const view = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeView.tsx", import.meta.url),
  "utf8",
);
const settings = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeSettings.tsx", import.meta.url),
  "utf8",
);
const explore = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeExplore.tsx", import.meta.url),
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

test("Project-bound Knowledge is visible to members without owner actions", () => {
  assert.match(view, /selectedSpace\?\.accessMode === "owner"/);
  assert.match(view, /Project 연결 · 읽기 전용/);
  assert.match(view, /canEditSelectedSpace && <div>/);
  assert.match(settings, /Project 읽기 전용 연결/);
  assert.match(settings, /원문 추가, AI 추출, Wiki 편집, 검토와 설정 변경은 Space 소유자만/);
});

test("Knowledge Explore uses debounced, abortable server search", () => {
  assert.match(api, /\/knowledge\/search/);
  assert.match(explore, /window\.setTimeout\(\(\) =>/);
  assert.match(explore, /}, 250\)/);
  assert.match(explore, /api\.knowledge\.search\(spaceId, normalized, scope, controller\.signal\)/);
  assert.match(explore, /controller\.abort\(\)/);
  assert.match(explore, /remote\?\.query\.toLocaleLowerCase\(\) === normalized/);
});
