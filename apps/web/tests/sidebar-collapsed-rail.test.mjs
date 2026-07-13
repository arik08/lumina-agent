import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);

test("the empty area of the collapsed sidebar rail expands only on double click", async () => {
  const app = await readFile(appPath, "utf8");
  const collapsedNavigation = app.match(
    /<nav[\s\S]*?className="sidebar-collapsed-navigation"[\s\S]*?<\/nav>/,
  )?.[0] ?? "";

  assert.match(collapsedNavigation, /onDoubleClick=\{\(event\) => \{/);
  assert.doesNotMatch(collapsedNavigation, /onClick=\{\(event\) => \{/);
  assert.match(
    collapsedNavigation,
    /event\.detail > 1 && event\.target === event\.currentTarget\) event\.preventDefault\(\);/,
  );
  assert.match(collapsedNavigation, /if \(event\.target !== event\.currentTarget\) return;/);
  assert.match(collapsedNavigation, /return;\s+event\.preventDefault\(\);/);
  assert.match(collapsedNavigation, /sidebarAutoCollapsedRef\.current = false;/);
  assert.match(collapsedNavigation, /setSidebarCollapsed\(false\);/);
});
