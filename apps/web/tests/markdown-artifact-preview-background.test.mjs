import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const stylesSource = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("Markdown artifact previews use the white work surface", () => {
  assert.match(stylesSource, /\.artifact-markdown-preview \{[^}]*background: var\(--surface\);/);
});
