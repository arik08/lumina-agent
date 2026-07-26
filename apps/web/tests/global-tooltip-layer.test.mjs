import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");
const sourceRoot = fileURLToPath(new URL("../src", import.meta.url));

test("all simple tooltips are delegated to one document body portal", async () => {
  const [main, tooltip, styles] = await Promise.all([
    read("../src/main.tsx"),
    read("../src/components/GlobalTooltip.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(main, /<GlobalTooltipProvider>/);
  assert.match(tooltip, /const tooltipSelector = "\[data-tooltip\]"/);
  assert.match(tooltip, /document\.addEventListener\("pointerover", show, true\)/);
  assert.match(tooltip, /event instanceof PointerEvent && event\.buttons !== 0/);
  assert.match(tooltip, /document\.addEventListener\("pointerdown", hide, true\)/);
  assert.match(tooltip, /document\.addEventListener\("focusin", show, true\)/);
  assert.doesNotMatch(tooltip, /getAttribute\("title"\)|removeAttribute\("title"\)/);
  assert.match(tooltip, /document\.body/);
  assert.match(tooltip, /anchor\.closest\("\.theme-dark"\) \? " theme-dark" : ""/);
  assert.match(styles, /\.global-tooltip-layer\s*\{[^}]*position:\s*fixed;[^}]*z-index:\s*10000/s);
  assert.match(styles, /\.global-tooltip-layer\.theme-dark,[\s\S]*?--menu-surface:\s*#121417;/);
  assert.doesNotMatch(styles, /content:\s*attr\(data-tooltip\)/);
  assert.doesNotMatch(styles, /tooltip-control[^,{]*::after/);
});

test("host UI tooltips never fall back to native title attributes", async () => {
  const sourceNames = (await readdir(sourceRoot, { recursive: true }))
    .filter((name) => name.endsWith(".tsx"));
  const offenders = [];

  for (const sourceName of sourceNames) {
    const source = await readFile(join(sourceRoot, sourceName), "utf8");
    if (/<(?!iframe\b)[a-z][^>]*\btitle\s*=/s.test(source)) offenders.push(sourceName);
  }

  assert.deepEqual(offenders, []);
});
