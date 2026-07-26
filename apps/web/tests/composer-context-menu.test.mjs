import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("composer replaces the browser context menu with Lumina edit actions", async () => {
  const app = await readFile(appPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(app, /onContextMenu=\{openComposerContextMenu\}/);
  assert.match(app, /className=\{`composer-context-menu lumina-select-menu lumina-select-menu-global size-small/);
  assert.match(app, /aria-label="입력란 편집 메뉴"/);
  assert.match(app, /<ClipboardPaste size=\{15\} aria-hidden="true" \/><span>붙여넣기<\/span>/);
  assert.match(app, /<ScanText size=\{15\} aria-hidden="true" \/><span>전체 선택<\/span>/);
  assert.match(styles, /\.composer-context-menu\.lumina-select-menu \.lumina-select-option > svg \{ opacity: 1; color: var\(--muted\); \}/);
});

test("composer only offers copy and cut when text is selected", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /composerContextMenu\.selectionStart !== composerContextMenu\.selectionEnd \? \(/);
  assert.match(app, /copyComposerSelection\(false\)\}><Copy size=\{15\} aria-hidden="true" \/><span>복사<\/span>/);
  assert.match(app, /copyComposerSelection\(true\)\}><Scissors size=\{15\} aria-hidden="true" \/><span>잘라내기<\/span>/);
});

test("context-menu paste keeps the long-text attachment rule", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /navigator\.clipboard\.readText\(\)/);
  assert.match(app, /pasted\.split\(\/\\r\?\\n\/\)\.length > 20/);
  assert.match(app, /workspace\.attachPastedText\(pasted\)/);
});
