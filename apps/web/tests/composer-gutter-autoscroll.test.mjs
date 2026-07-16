import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("composer gutters pass middle-button hits through to the conversation scroller", async () => {
  const styles = await readFile(stylesUrl, "utf8");
  const dockAreaRule = styles.match(/\.dock-area \{([^}]*)\}/)?.[1] ?? "";

  assert.match(dockAreaRule, /pointer-events:\s*none;/);
  assert.match(dockAreaRule, /background:\s*transparent;/);
  assert.match(dockAreaRule, /isolation:\s*isolate;/);
  assert.match(styles, /\.dock-area::after \{[^}]*z-index:\s*-1;[^}]*height:\s*calc\(max\(16px, env\(safe-area-inset-bottom\)\) \+ 14px\);[^}]*background:\s*var\(--chat-canvas\);[^}]*content:\s*"";/);
  assert.match(styles, /\.run-dock,\s*\.jump-to-latest \{\s*pointer-events:\s*auto;\s*\}/);
});

test("jump-to-latest keeps its border without surrounding shadows", async () => {
  const styles = await readFile(stylesUrl, "utf8");
  const jumpToLatestRule = styles.match(/(?:^|\n)\.jump-to-latest \{([^}]*)\}/)?.[1] ?? "";
  const runDockRule = styles.match(/(?:^|\n)\.run-dock \{([^}]*)\}/)?.[1] ?? "";

  assert.match(jumpToLatestRule, /border:\s*1px solid var\(--line-strong\);/);
  assert.doesNotMatch(jumpToLatestRule, /box-shadow\s*:/);
  assert.doesNotMatch(runDockRule, /box-shadow\s*:/);
});

test("run dock aligns with the assistant content and keeps its rounded edge", async () => {
  const styles = await readFile(stylesUrl, "utf8");
  const runDockRule = styles.match(/(?:^|\n)\.run-dock \{([^}]*)\}/)?.[1] ?? "";

  assert.match(runDockRule, /width:\s*min\(calc\(var\(--conversation-content-width\) - 28px\), calc\(100% - 28px\)\);/);
  assert.match(runDockRule, /transform:\s*translateX\(14px\);/);
  assert.match(runDockRule, /border-radius:\s*14px;/);
});
