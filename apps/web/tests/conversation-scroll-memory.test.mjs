import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const streamingUiUrl = new URL("../src/streaming-ui.ts", import.meta.url);
const appUrl = new URL("../src/App.tsx", import.meta.url);

test("conversation scroll position is restored per session without completed-run auto-follow", async () => {
  const [streamingUi, app] = await Promise.all([
    readFile(streamingUiUrl, "utf8"),
    readFile(appUrl, "utf8"),
  ]);

  assert.match(streamingUi, /sessionStorage\.getItem\(`\$\{scrollPositionStoragePrefix\}\$\{conversationId\}`\)/);
  assert.match(streamingUi, /sessionStorage\.setItem\(`\$\{scrollPositionStoragePrefix\}\$\{conversationId\}`/);
  assert.match(streamingUi, /useLayoutEffect\(\(\) => \{[\s\S]*?container\.scrollTop = targetTop;/);
  assert.match(streamingUi, /\(!activeRef\.current && !force\)/);
  assert.match(streamingUi, /!activeRef\.current && conversationId && remembered\?\.atBottom/);
  assert.match(streamingUi, /follow\(false, true, true\)/);
  assert.match(app, /useConversationAutoFollow\([\s\S]*?runIsActive,[\s\S]*?workspace\.activeConversationId,[\s\S]*?activeRuntime\.loaded,/);
});
