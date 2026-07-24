import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("authenticated app warms lazy views and their initial data in the background", async () => {
  const app = await read("../src/App.tsx");
  const preload = await read("../src/app-preload.ts");
  const api = await read("../src/api.ts");

  assert.match(app, /requestIdleCallback\(preload, \{ timeout: 1_000 \}\)/);
  assert.match(app, /preloadAppViews\(\{[\s\S]*?projectId: workspace\.activeProjectId,[\s\S]*?isAdmin/);
  assert.match(preload, /const moduleLoads = \[[\s\S]*?loadMarketplaceView\(\)[\s\S]*?loadKnowledgeView\(\)/);
  assert.match(preload, /listArtifacts\(projectId \?\? undefined\)/);
  assert.match(preload, /listDeepAnalysisMissions\(projectId\)/);
  assert.match(preload, /listProjectFiles\(projectId\)/);
  assert.match(preload, /listScheduledTasks\(projectId\)/);
  assert.match(preload, /listMemories\(undefined, "active"\)/);
  assert.match(preload, /listProjects\(\)/);
  assert.match(preload, /listAdminUsers\(\{ query: "", limit: 100 \}\)/);
  assert.match(preload, /getAdminUsageStatistics\(30\)/);
  assert.match(preload, /listAdminConversations\(\{ query: "", feedbackOnly: false, limit: 120 \}\)/);
  assert.match(preload, /getOrganizationInstructions\(\)/);
  assert.match(api, /export async function prefetchApiData/);
  assert.match(api, /if \(apiPrefetchDepth === 0\) prefetchedRequests\.delete\(cacheKey\)/);
});
