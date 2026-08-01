import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("navigation intent warms only the selected lazy view without eager API traffic", async () => {
  const app = await read("../src/App.tsx");
  const preload = await read("../src/app-preload.ts");
  const api = await read("../src/api.ts");

  assert.doesNotMatch(app, /requestIdleCallback/);
  assert.match(app, /onPointerEnter=\{\(\) => preloadAppView\(id\)\}/);
  assert.match(app, /onFocus=\{\(\) => preloadAppView\(id\)\}/);
  assert.match(preload, /const viewLoaders: Record<PreloadableAppView/);
  assert.match(preload, /"deep-analysis": \(\) => import\("\.\/workspace-frontends\/deep-analysis"\)/);
  assert.match(preload, /knowledge: \(\) => import\("\.\/workspace-frontends\/knowledge"\)/);
  assert.match(preload, /const loader = viewLoaders\[view as PreloadableAppView\]/);
  assert.match(preload, /loader\(\)\.catch\(\(\) => undefined\)/);
  assert.doesNotMatch(preload, /from "\.\/api"/);
  assert.doesNotMatch(api, /prefetchApiData|apiPrefetchDepth|prefetchedRequests/);
});
