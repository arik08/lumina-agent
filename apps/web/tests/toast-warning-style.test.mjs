import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const stylesheet = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("error toasts share the outlined danger alert treatment", () => {
  assert.match(stylesheet, /--danger-border: color-mix\(in srgb, var\(--danger\) 55%, var\(--line\)\)/);
  assert.match(stylesheet, /--danger-surface: color-mix\(in srgb, var\(--surface\) 94%, var\(--danger\)\)/);
  assert.match(stylesheet, /\.toast\.is-error \{[^}]*border-color: var\(--danger-border\)[^}]*background: var\(--danger-surface\)[^}]*color: var\(--danger\)/s);
  assert.match(stylesheet, /\.backend-disconnected \{[^}]*border: 1px solid var\(--danger-border\)[^}]*background: var\(--danger-surface\)/s);
  assert.doesNotMatch(stylesheet, /\.toast\.is-error \{[^}]*background:\s*#[0-9a-f]{3,8}/i);
});
