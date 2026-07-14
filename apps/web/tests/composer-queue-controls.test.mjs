import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);
const workspaceUrl = new URL("../src/use-lumina-workspace.ts", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("queued requests accumulate above the composer with steer and cancel controls", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /queuedComposerCommands[\s\S]*?command\.type === "queue_next"[\s\S]*?command\.status === "queued"/);
  assert.match(app, /queuedComposerCommands\.map\(\(command, index\)/);
  assert.match(app, /controlPendingCommand\("steer_queued", command\.id\)/);
  assert.match(app, /controlPendingCommand\("cancel_command", command\.id\)/);
  assert.match(app, /command\.messageText \|\| "대기 중인 요청"/);
  assert.match(app, /aria-label=\{`Queue \$\{position\}번 요청 취소`\}/);
});

test("queue controls use the run command endpoint and keep pending queue messages out of chat", async () => {
  const workspace = await readFile(workspaceUrl, "utf8");

  assert.match(workspace, /type PendingCommandAction = "steer_queued" \| "cancel_command"/);
  assert.match(workspace, /runPendingCommandAction[\s\S]*?api\.runs\.action\(runId/);
  assert.match(workspace, /item\.status === "pending" && item\.metadata\?\.command_type === "queue_next"/);
});

test("the queue list is a bounded connected list rather than stacked cards", async () => {
  const styles = await readFile(stylesUrl, "utf8");

  assert.match(styles, /\.composer-pending-commands\s*\{[^}]*max-height:\s*156px[^}]*overflow-y:\s*auto/);
  assert.match(styles, /\.composer-pending-command \+ \.composer-pending-command\s*\{[^}]*border-top:\s*1px solid var\(--line\)/);
  assert.match(styles, /\.composer-command-text\s*\{[^}]*text-overflow:\s*ellipsis[^}]*white-space:\s*nowrap/);
});
