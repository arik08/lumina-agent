import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

test("run plan opens when a plan appears and closes when the run finishes", () => {
  assert.match(appSource, /if \(planId && progressPlanIdRef\.current !== planId\)[\s\S]*setProgressOpen\(true\)/);
  assert.match(appSource, /if \(terminal\) \{\s*setProgressOpen\(false\)/);
});

test("the whole plan surface toggles without pause or cancel controls", () => {
  const panelStart = appSource.indexOf('className="progress-panel"');
  const panelEnd = appSource.indexOf('<div className="composer">', panelStart);
  const panelSource = appSource.slice(panelStart, panelEnd);

  assert.ok(panelStart >= 0 && panelEnd > panelStart);
  assert.match(panelSource, /setProgressOpen\(\(open\) => !open\)/);
  assert.doesNotMatch(panelSource, /controlRun\("pause"\)/);
  assert.doesNotMatch(panelSource, /controlRun\("cancel"\)/);
});

test("Korean plan steps are displayed with polite declarative endings", () => {
  assert.match(appSource, /function formalizePlanStepLabel/);
  assert.match(appSource, /\.replace\(\/한다\(\[\.\!\?\]\?\)\$\/u, "합니다\$1"\)/);
  assert.match(appSource, /label: formalizePlanStepLabel\(step\.step\)/);
});

test("completed plan steps use the same success pill treatment as tool calls", async () => {
  const stylesSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

  assert.match(appSource, /className={`progress-step-status \$\{step\.status === "complete" \? "status-complete" : ""\}`}/);
  assert.match(stylesSource, /\.tool-call-status,\s*\.progress-step-status\.status-complete/);
  assert.match(stylesSource, /\.tool-call-status\.status-complete,\s*\.progress-step-status\.status-complete/);
});

test("plan copy stays one pixel smaller than the conversation body", async () => {
  const stylesSource = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

  assert.match(stylesSource, /\.chat-pane\.view-chat \.progress-title,[\s\S]*?\.chat-pane\.view-chat \.progress-step-label > span,[\s\S]*?\.chat-pane\.view-chat \.progress-step-status \{\s*font-size: calc\(var\(--conversation-font-size\) - 1px\);/);
});
