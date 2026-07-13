import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const srcRoot = fileURLToPath(new URL("../src", import.meta.url));

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map((entry) => {
    const resolved = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(resolved) : entry.name.endsWith(".tsx") ? [resolved] : [];
  }));
  return nested.flat();
}

test("simple selections use the shared rounded menu instead of native selects", async () => {
  const [component, styles, files] = await Promise.all([
    readFile(new URL("../src/components/SelectMenu.tsx", import.meta.url), "utf8"),
    readFile(new URL("../src/components/SelectMenu.css", import.meta.url), "utf8"),
    sourceFiles(srcRoot),
  ]);
  const sources = await Promise.all(files.map((file) => readFile(file, "utf8")));

  assert.equal(sources.some((source) => /<select\b/i.test(source)), false);
  assert.match(component, /aria-haspopup="listbox"/);
  assert.match(component, /role="option"/);
  assert.match(component, /closeOnOutsidePointer/);
  assert.match(component, /event\.key === "Escape"/);
  assert.match(component, /event\.key === "Enter" \|\| event\.key === " "/);
  assert.match(component, /"ArrowDown", "ArrowUp", "Home", "End"/);
  assert.match(component, /lacksRoomBelow/);
  assert.match(styles, /\.lumina-select-menu\s*\{[\s\S]*?border-radius: 10px;/);
  assert.match(styles, /\.lumina-select-menu > button\s*\{[\s\S]*?border-radius: 6px;/);
});
