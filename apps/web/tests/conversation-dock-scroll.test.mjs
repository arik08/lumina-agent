import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("conversation bottom space tracks the mounted dock after login and view changes", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /pane\.style\.setProperty\("--dock-height", `\$\{Math\.ceil\(dock\.getBoundingClientRect\(\)\.height\)\}px`\)/);
  assert.match(app, /observer\.observe\(dock\)/);
  assert.match(app, /\}, \[conversationFollow\.follow, mainView, workspace\.authSession\?\.user\.id\]\);/);
});

test("dock resize keeps a followed conversation aligned to its new bottom edge", async () => {
  const app = await readFile(appPath, "utf8");
  const styles = await readFile(stylesPath, "utf8");

  assert.match(app, /window\.requestAnimationFrame\(\(\) => \{[\s\S]*?conversationFollow\.follow\(true\);[\s\S]*?\}\);/);
  assert.match(styles, /\.conversation \{[^}]*padding:\s*28px 0 calc\(var\(--dock-height, 140px\) \+ 42px\);/s);
});
