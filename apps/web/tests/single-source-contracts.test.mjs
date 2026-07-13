import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);
const turnPath = new URL("../src/components/ConversationTurn.tsx", import.meta.url);
const workspacePath = new URL("../src/use-lumina-workspace.ts", import.meta.url);

test("the UI consumes backend cost breakdowns instead of keeping a model price table", async () => {
  const turn = await readFile(turnPath, "utf8");

  assert.doesNotMatch(turn, /MODEL_TOKEN_PRICING/);
  assert.doesNotMatch(turn, /gpt-5\.|gemini-3\.|claude-(?:opus|sonnet|haiku)/);
  assert.match(turn, /estimated_cost_breakdown_usd/);
});

test("terminal run checks use the shared frontend status helper", async () => {
  const [app, turn, workspace] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(turnPath, "utf8"),
    readFile(workspacePath, "utf8"),
  ]);

  assert.match(app, /isTerminalRunStatus/);
  assert.match(turn, /isTerminalRunStatus/);
  assert.match(workspace, /isTerminalRunEvent/);
  for (const source of [app, turn, workspace]) {
    assert.doesNotMatch(
      source,
      /\["completed", "failed", "cancelled", "limit_reached", "interrupted"\]/,
    );
  }
});
