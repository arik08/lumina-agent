import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("collapsed work plan becomes a thin expandable bar without a hover tooltip", async () => {
  const [app, index, styles] = await Promise.all([
    read("../src/App.tsx"),
    read("../index.html"),
    read("../src/progress-summary.css"),
  ]);

  const progressTrigger = app.match(/<button className="progress-trigger"[^>]*>/)?.[0] ?? "";
  assert.match(progressTrigger, /aria-label=\{progressOpen \? "작업 계획 접기" : "작업 계획 펼치기"\}/);
  assert.doesNotMatch(progressTrigger, /data-tooltip=/);
  assert.match(app, /<span className="current-step"[^>]*>[\s\S]*?latestProgressSummary\?\.text \?\? runStatusLabel\(activeRun\.status\)/);
  assert.match(index, /<link rel="stylesheet" href="\/src\/progress-summary\.css" \/>/);
  assert.match(styles, /\.progress-trigger \.current-step\s*\{[^}]*pointer-events:\s*none;/s);

  const mainStyles = await read("../src/styles.css");
  assert.match(mainStyles, /\.progress-trigger\[aria-expanded="false"\]\s*\{[^}]*min-height:\s*16px;/s);
  assert.match(mainStyles, /\.progress-trigger\[aria-expanded="false"\] :is\(\.progress-title, \.current-step, \.progress-count\)\s*\{[^}]*display:\s*none;/s);
  assert.match(mainStyles, /\.progress-trigger\[aria-expanded="false"\] \.progress-chevron\s*\{[^}]*grid-column:\s*1 \/ -1;[^}]*justify-self:\s*center;/s);
});
