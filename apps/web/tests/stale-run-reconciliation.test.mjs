import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspaceSource = await readFile(
  new URL("../src/use-lumina-workspace.ts", import.meta.url),
  "utf8",
);

test("active runs periodically reconcile with the authoritative server snapshot", () => {
  assert.match(workspaceSource, /ACTIVE_RUN_RECONCILIATION_INTERVAL_MS = 15_000/);
  assert.match(workspaceSource, /mergeAuthoritativeRunSnapshot\(await api\.runs\.getSnapshot\(runId\)\)/);
  assert.match(workspaceSource, /window\.setInterval\(reconcileActiveRuns, ACTIVE_RUN_RECONCILIATION_INTERVAL_MS\)/);
  assert.match(workspaceSource, /window\.addEventListener\("focus", reconcileActiveRuns\)/);
  assert.match(workspaceSource, /document\.addEventListener\("visibilitychange", onVisibilityChange\)/);
});

test("stream errors reconcile immediately and terminal snapshots close stale streams", () => {
  assert.match(workspaceSource, /onError: \(\) => \{[\s\S]*?void reconcileRunSnapshot\(snapshot\.runId\)/);
  assert.match(workspaceSource, /if \(terminal\) \{[\s\S]*?streamsRef\.current\.get\(snapshot\.runId\)\?\.\(\)/);
  assert.match(workspaceSource, /activeRunId: terminal[\s\S]*?item\.activeRunId === snapshot\.runId \? null : item\.activeRunId/);
  assert.match(workspaceSource, /completedAt: snapshot\.finishedAt/);
});
