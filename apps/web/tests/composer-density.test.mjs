import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("composer stays compact for a single-line draft and grows only when needed", async () => {
  const [app, styles] = await Promise.all([readFile(appUrl, "utf8"), readFile(stylesUrl, "utf8")]);
  const composerRule = styles.match(/\.composer \{([^}]*)\}/)?.[1] ?? "";

  assert.match(app, /<textarea[\s\S]*?rows=\{1\}/);
  assert.doesNotMatch(composerRule, /min-height/);
  assert.match(composerRule, /padding:\s*var\(--space-1\) var\(--space-3\) var\(--space-2\)/);
  assert.match(styles, /\.composer textarea \{[^}]*min-height:\s*var\(--control-height-sm\);[^}]*max-height:\s*120px;[^}]*field-sizing:\s*content;/);
  assert.match(styles, /\.composer textarea \{[^}]*padding:\s*var\(--space-1\) var\(--space-2\);/);
});
