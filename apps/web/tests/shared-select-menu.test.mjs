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
  assert.match(component, /createPortal\([\s\S]*document\.body/);
  assert.match(component, /\.style\.getPropertyValue\("--conversation-font-size"\)/);
  assert.match(component, /conversationFontSize \? \{ "--conversation-font-size": conversationFontSize \} : \{\}/);
  assert.match(component, /!menuRef\.current\?\.contains\(event\.target\)/);
  assert.match(component, /window\.addEventListener\("scroll", reposition, true\)/);
  assert.match(styles, /\.lumina-select-menu\s*\{[\s\S]*?border-radius: var\(--radius-menu\);/);
  assert.match(styles, /\.lumina-select-menu-global\s*\{[^}]*position: fixed;/);
  assert.match(styles, /\.lumina-select-menu \.lumina-select-option\s*\{[\s\S]*?border-radius: var\(--radius-option\);/);
  assert.match(styles, /\.lumina-select-trigger\s*\{[\s\S]*?font-size: 14px;/);
  assert.match(styles, /\.lumina-select-menu \.lumina-select-option\s*\{[\s\S]*?height: 32px;[\s\S]*?font-size: 14px;/);
  assert.match(styles, /\.lumina-select\.size-small \.lumina-select-trigger \{[^}]*font-size: 14px;/);
  assert.match(styles, /\.lumina-select-menu-global\.size-small \.lumina-select-option \{[^}]*font-size: 14px;/);
});
