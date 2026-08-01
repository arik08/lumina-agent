import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const apiTypesPath = new URL("../src/api-types.ts", import.meta.url);
const safetyPath = new URL("../../server/src/lumina/runs/safety.py", import.meta.url);
const policyPath = new URL(
  "../../server/src/lumina/agent/execution_policy.py",
  import.meta.url,
);
const plansPath = new URL("../../server/src/lumina/runs/plans.py", import.meta.url);

test("frontend Run limits and events cover the backend wire contract", async () => {
  const [apiTypes, safety, policy, plans] = await Promise.all([
    readFile(apiTypesPath, "utf8"),
    readFile(safetyPath, "utf8"),
    readFile(policyPath, "utf8"),
    readFile(plansPath, "utf8"),
  ]);

  const limitSnapshot = safety.slice(
    safety.indexOf("def run_limit_snapshot"),
    safety.indexOf("def run_approval_mode"),
  );
  const limitFields = [...limitSnapshot.matchAll(/^\s+"([A-Za-z]+)":/gm)].map(
    (match) => match[1],
  );
  assert.deepEqual(limitFields, [
    "maxModelTurns",
    "maxTotalTokens",
    "maxElapsedSeconds",
    "maxCostUsd",
    "costAccounting",
  ]);
  for (const field of limitFields) {
    assert.match(apiTypes, new RegExp(`\\b${field}\\b`));
  }
  assert.match(apiTypes, /"provider_reported_or_estimated"/);

  const limitCodes = [...policy.matchAll(/code="(run_[a-z_]+_reached)"/g)].map(
    (match) => match[1],
  );
  assert.equal(limitCodes.length, 4);
  for (const code of limitCodes) {
    assert.match(apiTypes, new RegExp(`"${code}"`));
  }

  assert.match(plans, /"retry_scheduled"/);
  assert.match(apiTypes, /"retry_scheduled"/);
});
