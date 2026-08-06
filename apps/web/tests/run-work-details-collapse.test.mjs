import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { runActivityOutcome, shouldCollapseRunWorkDetails } from "../src/run-status.ts";

test("work details collapse automatically only after a completed run", () => {
  assert.equal(shouldCollapseRunWorkDetails("completed"), true);

  for (const status of ["cancelled", "interrupted", "failed", "limit_reached"]) {
    assert.equal(shouldCollapseRunWorkDetails(status), false, `${status} should remain open`);
  }
});

test("a visible running timeline does not collapse underneath the viewport when the run completes", async () => {
  const conversationTurn = await readFile(
    new URL("../src/components/ConversationTurn.tsx", import.meta.url),
    "utf8",
  );

  assert.match(
    conversationTurn,
    /useEffect\(\(\) => \{\s*if \(!collapseWorkDetails\) setWorkDetailsOpen\(true\);\s*\}, \[snapshot\?\.runId, collapseWorkDetails\]\);/,
  );
  assert.doesNotMatch(conversationTurn, /setWorkDetailsOpen\(!collapseWorkDetails\)/);
});

test("work details stay open while a run is active or has not started", () => {
  for (const status of [null, "queued", "preparing", "model_streaming", "tools_running"]) {
    assert.equal(shouldCollapseRunWorkDetails(status), false, `${status ?? "unset"} should remain open`);
  }
});

test("terminal run outcomes distinguish a completed activity from a stopped one", () => {
  assert.equal(runActivityOutcome("completed"), "completed");
  assert.equal(runActivityOutcome("failed"), "failed");

  for (const status of ["cancelled", "interrupted", "limit_reached"]) {
    assert.equal(runActivityOutcome(status), "stopped", `${status} should stop active rows`);
  }

  assert.equal(runActivityOutcome("model_streaming"), "running");
});
