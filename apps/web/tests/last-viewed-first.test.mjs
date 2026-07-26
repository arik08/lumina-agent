import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";

const read = (path) => fs.readFileSync(new URL(path, import.meta.url), "utf8");

test("data-heavy views retain their last successful list during background refresh", () => {
  const app = read("../src/App.tsx");
  const marketplace = read("../src/components/MarketplaceView.tsx");
  const library = read("../src/components/ArtifactLibraryView.tsx");
  const files = read("../src/components/ProjectFilesView.tsx");
  const schedules = read("../src/components/SchedulesView.tsx");
  const memory = read("../src/components/MemoryView.tsx");

  assert.match(app, /<ViewDataCacheProvider scope=\{workspace\.authSession\.user\.id\}>/);
  for (const source of [marketplace, library, files, schedules, memory]) {
    assert.match(source, /useCachedViewState/);
    assert.match(source, /hasCached/);
  }
  assert.match(marketplace, /const visibleCatalog = hasCachedCatalog \? catalog : lastVisibleCatalogRef\.current/);
  assert.match(marketplace, /catalog=\{visibleCatalog\}/);
  assert.match(marketplace, /loading=\{!hasCachedCatalog && visibleCatalog\.items\.length === 0 && \(catalogLoading \|\| !error\)\}/);
  assert.match(library, /loading && !hasCachedItems/);
  assert.match(files, /\(!hasCachedFiles \|\| !hasCachedFolders\) && \(loading \|\| !error\)/);
  assert.match(schedules, /loading && !hasCachedTasks/);
  assert.match(memory, /!hasCachedItems && \(loading \|\| !error\)/);
});

test("the shared design system defines last-viewed-first as a default", () => {
  const design = read("../../../DESIGN.md");
  assert.match(design, /\*\*Last-Viewed First:\*\*/);
  assert.match(design, /마지막으로 성공적으로 본 콘텐츠를 즉시 렌더링/);
  assert.match(design, /백그라운드에서 다시 검증/);
});
