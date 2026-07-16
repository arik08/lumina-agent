import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("all simple tooltips are delegated to one document body portal", async () => {
  const [main, tooltip, styles] = await Promise.all([
    read("../src/main.tsx"),
    read("../src/components/GlobalTooltip.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(main, /<GlobalTooltipProvider>/);
  assert.match(tooltip, /\[data-tooltip\], \[data-global-tooltip-title\], \[title\]:not\(iframe\)/);
  assert.match(tooltip, /document\.addEventListener\("pointerover", show, true\)/);
  assert.match(tooltip, /document\.addEventListener\("focusin", show, true\)/);
  assert.match(tooltip, /target\.removeAttribute\("title"\)/);
  assert.match(tooltip, /document\.body/);
  assert.match(tooltip, /anchor\.closest\("\.theme-dark"\) \? " theme-dark" : ""/);
  assert.match(styles, /\.global-tooltip-layer\s*\{[^}]*position:\s*fixed;[^}]*z-index:\s*10000/s);
  assert.match(styles, /\.global-tooltip-layer\.theme-dark,[\s\S]*?--menu-surface:\s*#121417;/);
  assert.doesNotMatch(styles, /content:\s*attr\(data-tooltip\)/);
  assert.doesNotMatch(styles, /tooltip-control[^,{]*::after/);
});
