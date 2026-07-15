import assert from "node:assert/strict";
import test from "node:test";

import { shouldCollapseRunWorkDetails } from "../src/run-status.ts";

test("work details collapse automatically only after a completed run", () => {
  assert.equal(shouldCollapseRunWorkDetails("completed"), true);

  for (const status of ["cancelled", "interrupted", "failed", "limit_reached"]) {
    assert.equal(shouldCollapseRunWorkDetails(status), false, `${status} should remain open`);
  }
});

test("work details stay open while a run is active or has not started", () => {
  for (const status of [null, "queued", "preparing", "model_streaming", "tools_running"]) {
    assert.equal(shouldCollapseRunWorkDetails(status), false, `${status ?? "unset"} should remain open`);
  }
});
