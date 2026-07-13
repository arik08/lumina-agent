import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("session scrollbar fades from its active strength instead of snapping", async () => {
  const [source, styles] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(source, /list\.classList\.add\("is-scrolling"\)/);
  assert.match(source, /list\.classList\.remove\("is-scrolling"\)/);
  assert.match(styles, /@property --session-scrollbar-strength \{[^}]*syntax: "<percentage>";[^}]*initial-value: 11%;/s);
  assert.match(styles, /--scrollbar-activation-duration: 140ms;/);
  assert.match(styles, /--scrollbar-activation-easing: cubic-bezier\(0\.25, 1, 0\.5, 1\);/);
  assert.match(styles, /--scrollbar-fade-duration: 720ms;/);
  assert.match(styles, /\.session-list \{[^}]*--session-scrollbar-strength: 11%;[^}]*transition: --session-scrollbar-strength var\(--scrollbar-fade-duration\) linear;/s);
  assert.match(styles, /\.theme-dark \.session-list \{ scrollbar-color: color-mix\(in srgb, var\(--ink\) var\(--session-scrollbar-strength\), transparent\) transparent; \}/);
  assert.match(styles, /\.session-list\.is-scrolling \{ --session-scrollbar-strength: 30%; transition-duration: var\(--scrollbar-activation-duration\); transition-timing-function: var\(--scrollbar-activation-easing\); \}/);
  assert.match(styles, /\.session-list::\-webkit-scrollbar-thumb \{[^}]*transition: border-width var\(--scrollbar-fade-duration\) linear;/s);
});
