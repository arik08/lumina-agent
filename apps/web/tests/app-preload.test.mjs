import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("navigation intent and network-aware idle work warm lazy views without eager API traffic", async () => {
  const app = await read("../src/App.tsx");
  const preload = await read("../src/app-preload.ts");
  const api = await read("../src/api.ts");

  assert.match(app, /onPointerEnter=\{\(\) => void preloadAppView\(id\)\}/);
  assert.match(app, /onFocus=\{\(\) => void preloadAppView\(id\)\}/);
  assert.match(app, /if \(!workspace\.authSession \|\| !shouldBackgroundPreloadAppViews\(\)\) return/);
  assert.match(app, /const view = backgroundPreloadOrder\[preloadIndex\]/);
  assert.match(app, /window\.requestIdleCallback\(preloadNext, \{ timeout: 5_000 \}\)/);
  assert.match(app, /globalThis\.setTimeout\(preloadNext, 750\)/);
  assert.match(app, /window\.cancelIdleCallback\(idleId\)/);
  assert.match(preload, /const viewLoaders: Record<PreloadableAppView/);
  assert.match(preload, /"deep-analysis": \(\) => import\("\.\/workspace-frontends\/deep-analysis"\)/);
  assert.match(preload, /knowledge: \(\) => import\("\.\/workspace-frontends\/knowledge"\)/);
  assert.match(preload, /backgroundPreloadOrder: readonly PreloadableAppView\[\]/);
  assert.match(preload, /connection\?\.saveData/);
  assert.match(preload, /\["slow-2g", "2g"\]\.includes/);
  assert.match(preload, /const loader = viewLoaders\[view as PreloadableAppView\]/);
  assert.match(preload, /await loader\(\)\.catch\(\(\) => undefined\)/);
  assert.doesNotMatch(preload, /from "\.\/api"/);
  assert.doesNotMatch(api, /prefetchApiData|apiPrefetchDepth|prefetchedRequests/);
});
