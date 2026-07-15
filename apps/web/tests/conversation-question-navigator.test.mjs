import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("user questions expose compact preview markers and message anchors", async () => {
  const [app, navigator, turn] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/components/ConversationQuestionNavigator.tsx"),
    read("../src/components/ConversationTurn.tsx"),
  ]);

  assert.match(app, /<ConversationQuestionNavigator[\s\S]*?turnSets=\{activeRuntime\.turnSets\}[\s\S]*?scrollContainerRef=\{conversationFollow\.containerRef\}[\s\S]*?onNavigateStart=\{conversationFollow\.onUserIntent\}/s);
  assert.doesNotMatch(app, /<ConversationQuestionNavigator[\s\S]*?snapshots=/s);
  assert.match(navigator, /message\.role !== "user"/);
  assert.match(navigator, /anchorId: message\.id, questionPreview, answerPreview/);
  assert.match(navigator, /questionNavigatorPreview\(message\.text, questionPreviewCharacterLimit\)/);
  assert.match(navigator, /\.find\(\(candidate\) => candidate\.role === "assistant"\)/);
  assert.match(navigator, /questionNavigatorPreview\(answer\?\.text \?\? "", answerPreviewCharacterLimit\)/);
  assert.doesNotMatch(navigator, /\[\*_`~>\|\]/);
  assert.match(navigator, /aria-label=\{`사용자 질문 \$\{items\.length\}개 바로가기`\}/);
  assert.match(turn, /data-question-anchor=\{message\.id\}/);
  assert.doesNotMatch(turn, /data-response-anchor/);
});

test("hovered marker tapers its neighbors and click scrolling accelerates then decelerates", async () => {
  const [navigator, styles, globalTooltip] = await Promise.all([
    read("../src/components/ConversationQuestionNavigator.tsx"),
    read("../src/styles.css"),
    read("../src/components/GlobalTooltip.tsx"),
  ]);

  assert.match(navigator, /if \(distance === 1\) return 0\.76/);
  assert.match(navigator, /onMouseEnter=\{\(\) => setActiveIndex\(index\)\}/);
  assert.match(navigator, /const target = \[\.\.\.container\.querySelectorAll<HTMLElement>\("\[data-question-anchor\]"\)\]/);
  assert.match(navigator, /Math\.min\(340, Math\.max\(190,/);
  assert.match(navigator, /window\.requestAnimationFrame\(step\)/);
  assert.match(navigator, /prefers-reduced-motion: reduce/);
  assert.match(styles, /\.question-navigator-marker::before \{[^}]*transform: translateY\(-50%\) scaleX\(var\(--question-marker-scale\)\)[^}]*transition:/s);
  assert.match(navigator, /<GlobalTooltipLayer anchor=\{markerRefs\.current\[index\]\} className="question-navigator-tooltip"/);
  assert.match(navigator, /preferredPlacement="right"/);
  assert.match(globalTooltip, /preferredPlacement\?: "vertical" \| "right"/);
  assert.match(globalTooltip, /spaceRight >= layerRect\.width \|\| spaceRight >= spaceLeft \? "right" : "left"/);
  assert.match(navigator, />질문<\/small>/);
  assert.match(navigator, />답변<\/small>/);
  assert.match(navigator, /item\.answerPreview \|\| "아직 답변이 없습니다\."/);
  assert.match(styles, /\.question-navigator-tooltip \{/);
  assert.match(styles, /\.question-navigator-preview-row\.is-answer \{[^}]*border-top:/s);
  assert.doesNotMatch(styles, /question-tooltip-enter/);
});
