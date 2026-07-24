import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);

test("composer replaces the browser context menu with Lumina edit actions", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /onContextMenu=\{openComposerContextMenu\}/);
  assert.match(app, /className=\{`composer-context-menu lumina-select-menu lumina-select-menu-global size-small/);
  assert.match(app, /aria-label="입력란 편집 메뉴"/);
  assert.match(app, />붙여넣기<\/button>/);
  assert.match(app, />전체 선택<\/button>/);
});

test("composer only offers copy and cut when text is selected", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /composerContextMenu\.selectionStart !== composerContextMenu\.selectionEnd \? \(/);
  assert.match(app, /copyComposerSelection\(false\)\}>복사<\/button>/);
  assert.match(app, /copyComposerSelection\(true\)\}>잘라내기<\/button>/);
});

test("context-menu paste keeps the long-text attachment rule", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /navigator\.clipboard\.readText\(\)/);
  assert.match(app, /pasted\.split\(\/\\r\?\\n\/\)\.length > 20/);
  assert.match(app, /workspace\.attachPastedText\(pasted\)/);
});
