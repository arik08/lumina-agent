import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("collapsed work plan stays thin and hides its visible copy", async () => {
  const [app, index, styles] = await Promise.all([
    read("../src/App.tsx"),
    read("../index.html"),
    read("../src/progress-summary.css"),
  ]);

  assert.match(app, /<span className="current-step"[^>]*>[\s\S]*?latestProgressSummary\?\.text \?\? runStatusLabel\(activeRun\.status\)/);
  assert.match(app, /className=\{`progress-trigger \$\{progressOpen \? "is-open" : "is-collapsed"\}`\}/);
  assert.match(app, /aria-label=\{progressOpen \? "작업 계획 접기" : `작업 계획 펼치기,/);
  assert.match(index, /<link rel="stylesheet" href="\/src\/progress-summary\.css" \/>/);
  assert.match(styles, /\.progress-trigger \.current-step\[title\]\s*\{[^}]*pointer-events:\s*none;/s);

  const mainStyles = await read("../src/styles.css");
  assert.match(mainStyles, /\.progress-trigger\.is-collapsed \{[^}]*min-height: 25px;/s);
  assert.match(mainStyles, /\.progress-trigger\.is-collapsed :is\(\.progress-title strong, \.current-step, \.progress-count\) \{ display: none; \}/);
});
