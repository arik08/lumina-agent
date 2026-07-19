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
  assert.match(streamingUi, /useLayoutEffect\(\(\) => \{[\s\S]*?setProgrammaticScrollTop\(container, targetTop,/);
  assert.match(streamingUi, /\(!activeRef\.current && !force\)/);
  assert.match(streamingUi, /!activeRef\.current && conversationId && remembered\?\.atBottom/);
  assert.match(streamingUi, /setShowJumpToLatest\(!followingRef\.current && distance > jumpButtonThresholdPx\)/);
  assert.match(streamingUi, /if \(distance <= nearBottomPx\) \{[\s\S]*?followingRef\.current = true;[\s\S]*?setShowJumpToLatest\(false\);[\s\S]*?return;/);
  assert.match(streamingUi, /const jumpToLatest = useCallback\(\(\) => \{[\s\S]*?followingRef\.current = true;[\s\S]*?setShowJumpToLatest\(false\);[\s\S]*?follow\(distance > \(container\?\.clientHeight \?\? 0\) \* instantJumpDistanceViewports, true, true\)/);
  assert.doesNotMatch(streamingUi, /if \(!force\) \{/);
  assert.match(streamingUi, /const responseMs = 340;[\s\S]*?setProgrammaticScrollTop\(current, Math\.max\(current\.scrollTop, Math\.min\(target, nextTop\)\), false\)/);
  assert.match(streamingUi, /container\.dataset\.programmaticScroll === "true"/);
  assert.match(app, /useConversationAutoFollow\([\s\S]*?runIsActive,[\s\S]*?workspace\.activeConversationId,[\s\S]*?activeRuntime\.loaded,/);
});

test("jump to latest accelerates quickly across long conversations", async () => {
  const streamingUi = await readFile(streamingUiUrl, "utf8");

  assert.match(streamingUi, /const maxAcceleration = Math\.max\(18_000, Math\.min\(90_000, current\.clientHeight \* 110\)\)/);
  assert.match(streamingUi, /const maxVelocity = Math\.max\(700, Math\.min\(9_000, current\.clientHeight \* 7 \+ Math\.abs\(distance\) \* 4\)\)/);
  assert.match(streamingUi, /const acceleration = distance \* omega \* omega - followVelocity \* 2 \* omega/);
  assert.match(streamingUi, /const maxFrameScrollDistance = Math\.max\(32, Math\.min\(96, current\.clientHeight \* 0\.12\)\)/);
  assert.match(streamingUi, /remaining <= Math\.max\(1, frameScrollDistance\)/);
});

test("jump to latest skips animation when the remaining distance exceeds four viewports", async () => {
  const streamingUi = await readFile(streamingUiUrl, "utf8");

  assert.match(streamingUi, /const instantJumpDistanceViewports = 4;/);
  assert.match(streamingUi, /const distance = container\s*\? container\.scrollHeight - container\.clientHeight - container\.scrollTop\s*: 0;/);
  assert.match(streamingUi, /follow\(distance > \(container\?\.clientHeight \?\? 0\) \* instantJumpDistanceViewports, true, true\)/);
});
