import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("assistant responses expose compact preview markers and stable anchors", async () => {
  const [app, navigator, turn] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/components/ConversationResponseNavigator.tsx"),
    read("../src/components/ConversationTurn.tsx"),
  ]);

  assert.match(app, /<ConversationResponseNavigator[\s\S]*?turnSets=\{activeRuntime\.turnSets\}[\s\S]*?scrollContainerRef=\{conversationFollow\.containerRef\}[\s\S]*?onNavigateStart=\{conversationFollow\.onUserIntent\}/s);
  assert.match(navigator, /finalMessage\?\.text \|\| snapshot\?\.assistantDraft\?\.text/);
  assert.match(navigator, /sanitizeAssistantResponse\(responseText,/);
  assert.match(navigator, /\[0-9a-f\]\{8\}.*?\[0-9a-f\]\{12\}/);
  assert.match(navigator, /aria-label=\{`AI 응답 \$\{items\.length\}개 바로가기`\}/);
  assert.match(turn, /data-response-anchor=\{turnSet\.id\}/);
});

test("hovered marker tapers its neighbors and click scrolling accelerates then decelerates", async () => {
  const [navigator, styles] = await Promise.all([
    read("../src/components/ConversationResponseNavigator.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(navigator, /function markerScaleForDistance\(distance: number\)[\s\S]*?distance === 0[\s\S]*?distance === 1[\s\S]*?distance === 2[\s\S]*?distance === 3/s);
  assert.match(navigator, /function easeInOutCubic\(progress: number\)/);
  assert.match(navigator, /Math\.min\(340, Math\.max\(190,/);
  assert.match(navigator, /window\.requestAnimationFrame\(step\)/);
  assert.match(navigator, /prefers-reduced-motion: reduce/);
  assert.match(styles, /\.response-navigator-marker::before \{[^}]*transform: translateY\(-50%\) scaleX\(var\(--response-marker-scale\)\)[^}]*transition:/s);
  assert.match(styles, /\.response-navigator-tooltip \{[\s\S]*?animation: response-tooltip-enter/s);
});
