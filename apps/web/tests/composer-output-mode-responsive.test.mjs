import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("narrow composers hide the output mode toggle before its labels wrap", () => {
  assert.match(styles, /\.composer \{[^}]*container:\s*composer \/ inline-size;/);
  assert.match(styles, /@container composer \(max-width:\s*460px\)\s*\{\s*\.composer-footer \.output-mode-toggle \{ display:\s*none; \}\s*\}/);
});
