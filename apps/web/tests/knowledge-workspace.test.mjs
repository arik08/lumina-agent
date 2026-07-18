import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const viewPath = new URL(
  "../src/workspace-frontends/knowledge/KnowledgeView.tsx",
  import.meta.url,
);
const apiPath = new URL("../src/api.ts", import.meta.url);

test("Knowledge is a top-level lazy Workspace view", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /lazy\(\(\) => import\("\.\/workspace-frontends\/knowledge"\)/);
  assert.match(app, /id: "knowledge", label: "지식"/);
  assert.match(app, /mainView === "knowledge" && <KnowledgeView/);
});

test("Knowledge uses account-scoped Space and typed source, entity, statement APIs", async () => {
  const [view, api] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(apiPath, "utf8"),
  ]);

  assert.match(view, /api\.knowledge\.listSpaces/);
  assert.match(view, /api\.knowledge\.createSource/);
  assert.match(view, /api\.knowledge\.createEntity/);
  assert.match(view, /api\.knowledge\.createStatement/);
  assert.match(view, /api\.knowledge\.startIngestion/);
  assert.match(view, /api\.knowledge\.listIngestions/);
  assert.match(api, /\/knowledge\/spaces\/\$\{encodeURIComponent\(spaceId\)\}\/sources/);
  assert.match(api, /\/knowledge\/spaces\/\$\{encodeURIComponent\(spaceId\)\}\/entities/);
  assert.match(api, /sources\/\$\{encodeURIComponent\(sourceId\)\}\/ingestions/);
});

test("Knowledge AI ingestion exposes durable progress and review-only results", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /job\.status === "queued" \|\| job\.status === "running"/);
  assert.match(view, /근거 기반 추출 중/);
  assert.match(view, /검토 제안/);
  assert.match(view, /추출 완료/);
});

test("Knowledge graph stays bounded and approved relations preserve evidence", async () => {
  const view = await readFile(viewPath, "utf8");

  assert.match(view, /getNeighborhood\(selectedEntityId, 2/);
  assert.match(view, /evidenceSegmentIds: evidenceId \? \[evidenceId\] : \[\]/);
  assert.match(view, /status: evidenceId \? "approved" : "proposed"/);
  assert.match(view, /원문과 근거를 보존하면서 Wiki와 Knowledge Graph/);
});
