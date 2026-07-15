import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("composer gutters pass middle-button hits through to the conversation scroller", async () => {
  const styles = await readFile(stylesUrl, "utf8");
  const dockAreaRule = styles.match(/\.dock-area \{([^}]*)\}/)?.[1] ?? "";

  assert.match(dockAreaRule, /pointer-events:\s*none;/);
  assert.match(styles, /\.run-dock,\s*\.jump-to-latest \{\s*pointer-events:\s*auto;\s*\}/);
});
