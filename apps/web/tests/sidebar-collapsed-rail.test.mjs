import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);

test("the empty area of the collapsed sidebar rail expands the sidebar", async () => {
  const app = await readFile(appPath, "utf8");
  const collapsedNavigation = app.match(
    /<nav[\s\S]*?className="sidebar-collapsed-navigation"[\s\S]*?<\/nav>/,
  )?.[0] ?? "";

  assert.match(collapsedNavigation, /if \(event\.target !== event\.currentTarget\) return;/);
  assert.match(collapsedNavigation, /sidebarAutoCollapsedRef\.current = false;/);
  assert.match(collapsedNavigation, /setSidebarCollapsed\(false\);/);
});
