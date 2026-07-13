import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnUrl = new URL("../src/components/ConversationTurn.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("usage popover flips below the trigger before the conversation scroller clips it", async () => {
  const [turn, styles] = await Promise.all([
    readFile(turnUrl, "utf8"),
    readFile(stylesUrl, "utf8"),
  ]);

  assert.match(turn, /control\.closest<HTMLElement>\("\.conversation-scroll"\)\?\.getBoundingClientRect\(\)/);
  assert.match(turn, /const topBoundary = Math\.max\(viewportPadding, \(clippingRect\?\.top \?\? 0\) \+ viewportPadding\)/);
  assert.match(turn, /const bottomBoundary = Math\.min\(/);
  assert.match(turn, /const spaceAbove = controlRect\.top - topBoundary - popoverGap/);
  assert.match(turn, /const spaceBelow = bottomBoundary - controlRect\.bottom - popoverGap/);
  assert.match(turn, /spaceAbove < popover\.offsetHeight && spaceBelow > spaceAbove \? "below" : "above"/);
  assert.match(turn, /onPointerEnter=\{updatePopoverPlacement\}/);
  assert.match(turn, /onFocusCapture=\{updatePopoverPlacement\}/);
  assert.match(styles, /\.answer-usage-control\.is-below \.answer-usage-popover\s*\{[^}]*top:\s*calc\(100% \+ 8px\)[^}]*bottom:\s*auto/);
});
