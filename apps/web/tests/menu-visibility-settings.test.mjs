import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("primary navigation uses the persisted visible menu subset", async () => {
  const [app, workspace, apiTypes] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);

  assert.match(apiTypes, /menuVisibility: MenuVisibilityId\[\]/);
  assert.match(workspace, /persistSettings\(\{ menuVisibility \}\)/);
  assert.match(app, /const visibleNavigation = navigation\.filter/);
  assert.equal((app.match(/\{visibleNavigation\.map/g) ?? []).length, 2);
});

test("personal settings expose every shared navigation item as a checkbox", async () => {
  const app = await read("../src/App.tsx");

  assert.match(app, /<h2 id="menu-settings-title">메뉴 표시<\/h2>/);
  assert.match(app, /navigation\.map\(\(\{ id, label, icon: Icon \}\)/);
  assert.match(app, /type="checkbox" checked=\{checked\}/);
  assert.match(app, /disabled=\{menuVisibilitySaving\}/);
  assert.match(app, /숨긴 기능도 설정에서 다시 표시할 수 있습니다/);
});
