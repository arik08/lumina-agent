import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("all visible scrollbars share the neutral idle fade behavior", async () => {
  const [main, activity, styles, design] = await Promise.all([
    read("../src/main.tsx"),
    read("../src/scrollbar-activity.ts"),
    read("../src/styles.css"),
    read("../../../DESIGN.md"),
  ]);

  assert.match(main, /installScrollbarActivity\(\)/);
  assert.match(activity, /document\.addEventListener\("scroll", handleScroll, true\)/);
  assert.match(activity, /element\.classList\.add\("has-scrollbar-fade", "is-scrolling"\)/);
  assert.match(activity, /element\.classList\.remove\("is-scrolling"\)/);
  assert.match(activity, /const SCROLLBAR_IDLE_DELAY_MS = 650;/);
  assert.match(styles, /@property --scrollbar-strength \{[^}]*syntax: "<percentage>";[^}]*initial-value: 11%;/s);
  assert.match(styles, /--scrollbar-thumb: color-mix\(in srgb, var\(--ink\) 11%, transparent\);/);
  assert.match(styles, /--scrollbar-thumb-strong: color-mix\(in srgb, var\(--ink\) 30%, transparent\);/);
  assert.match(styles, /--scrollbar-activation-duration: 140ms;/);
  assert.match(styles, /--scrollbar-activation-easing: cubic-bezier\(0\.25, 1, 0\.5, 1\);/);
  assert.match(styles, /--scrollbar-fade-duration: 520ms;/);
  assert.match(styles, /:where\(\*\) \{[^}]*scrollbar-color: var\(--scrollbar-thumb\) transparent;[^}]*scrollbar-width: thin;/s);
  assert.match(styles, /\.has-scrollbar-fade \{[^}]*--scrollbar-strength: 11%;[^}]*transition: --scrollbar-strength var\(--scrollbar-fade-duration\) linear;/s);
  assert.match(styles, /\.has-scrollbar-fade\.is-scrolling \{ --scrollbar-strength: 30%;[^}]*transition-duration: var\(--scrollbar-activation-duration\);/s);
  assert.match(styles, /:where\(\*\)::\-webkit-scrollbar-thumb \{[^}]*transition: border-width var\(--scrollbar-fade-duration\) linear;/s);
  assert.doesNotMatch(styles, /scrollbar[^;}]*var\(--cobalt\)/);
  assert.match(design, /thumb는[^.\n]*중성 회색/);
  assert.match(design, /650ms/);
});
