import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesPath = new URL("../src/styles.css", import.meta.url);

test("Memory controls end on the primary navigation boundary", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.memory-toolbar\s*\{[^}]*min-height:\s*48px;/);
});
