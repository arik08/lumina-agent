import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("collapsed work plan summary stays visible with one delegated tooltip", async () => {
  const [app, index, styles] = await Promise.all([
    read("../src/App.tsx"),
    read("../index.html"),
    read("../src/progress-summary.css"),
  ]);

  assert.match(app, /className="progress-trigger"[^>]*data-tooltip=\{progressOpen \? undefined : latestProgressSummary\?\.text \?\? runStatusLabel\(activeRun\.status\)\}/);
  assert.match(app, /<span className="current-step"[^>]*>[\s\S]*?latestProgressSummary\?\.text \?\? runStatusLabel\(activeRun\.status\)/);
  assert.match(index, /<link rel="stylesheet" href="\/src\/progress-summary\.css" \/>/);
  assert.match(styles, /\.progress-trigger \.current-step\s*\{[^}]*pointer-events:\s*none;/s);
});
