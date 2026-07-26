import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const workspaceSource = await readFile(
  new URL("../src/use-lumina-workspace.ts", import.meta.url),
  "utf8",
);

test("active runs periodically reconcile with the authoritative server snapshot", () => {
  assert.match(workspaceSource, /ACTIVE_RUN_RECONCILIATION_INTERVAL_MS = 15_000/);
  assert.match(workspaceSource, /getRunSnapshotsBestEffort\(pendingRunIds\)/);
  assert.match(workspaceSource, /void reconcileRunSnapshots\(runIds\)/);
  assert.doesNotMatch(workspaceSource, /runIds\.forEach\(\(runId\) => void reconcileRunSnapshot\(runId\)\)/);
  assert.match(workspaceSource, /if \(document\.visibilityState === "visible"\) reconcileActiveRuns\(\)/);
  assert.match(workspaceSource, /window\.setInterval\(reconcileActiveRunsWhenVisible, ACTIVE_RUN_RECONCILIATION_INTERVAL_MS\)/);
  assert.match(workspaceSource, /window\.addEventListener\("focus", reconcileActiveRunsWhenVisible\)/);
  assert.match(workspaceSource, /document\.addEventListener\("visibilitychange", reconcileActiveRunsWhenVisible\)/);
});

test("active run hydration batches sessions and retains an isolated failure fallback", () => {
  assert.match(workspaceSource, /const hydrateRuns = useCallback\(async \(runIds: Iterable<string>\)/);
  assert.match(workspaceSource, /void hydrateRuns\(runIds\)/);
  assert.match(workspaceSource, /Promise\.allSettled\(runIds\.map\(\(runId\) => api\.runs\.getSnapshot\(runId\)\)\)/);
});

test("conversation paging reuses snapshots already serialized by the server", () => {
  assert.match(workspaceSource, /const restoredSnapshots = page\.runSnapshots[\s\S]*?\?\? await api\.runs\.getSnapshots/);
  assert.match(workspaceSource, /let fetchedSnapshots: RunSnapshot\[\] \| null = \[\]/);
});

test("stream errors reconcile immediately and terminal snapshots close stale streams", () => {
  assert.match(workspaceSource, /onError: \(\) => \{[\s\S]*?void reconcileRunSnapshot\(snapshot\.runId\)/);
  assert.match(workspaceSource, /if \(terminal\) \{[\s\S]*?streamsRef\.current\.get\(snapshot\.runId\)\?\.\(\)/);
  assert.match(workspaceSource, /activeRunId: terminal[\s\S]*?item\.activeRunId === snapshot\.runId \? null : item\.activeRunId/);
  assert.match(workspaceSource, /completedAt: snapshot\.finishedAt/);
});
