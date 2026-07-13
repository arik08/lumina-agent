import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const adminViewPath = new URL("../src/components/AdminView.tsx", import.meta.url);

test("admin entry point and page use the system management name", async () => {
  const [app, adminView] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(adminViewPath, "utf8"),
  ]);

  assert.match(app, /<strong>시스템 관리<\/strong>/);
  assert.doesNotMatch(app, /<strong>관리자 메뉴<\/strong>/);
  assert.match(adminView, /aria-label="시스템 관리 화면"/);
  assert.match(adminView, /<h1>시스템 관리<\/h1>/);
  assert.match(adminView, /aria-label="시스템 관리 항목"/);
});
