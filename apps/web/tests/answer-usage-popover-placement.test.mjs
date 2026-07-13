import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnUrl = new URL("../src/components/ConversationTurn.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("usage popover flips below the trigger when the viewport top is too close", async () => {
  const [turn, styles] = await Promise.all([
    readFile(turnUrl, "utf8"),
    readFile(stylesUrl, "utf8"),
  ]);

  assert.match(turn, /const spaceAbove = controlRect\.top - viewportPadding - popoverGap/);
  assert.match(turn, /spaceAbove < popover\.offsetHeight && spaceBelow > spaceAbove \? "below" : "above"/);
  assert.match(turn, /onPointerEnter=\{updatePopoverPlacement\}/);
  assert.match(turn, /onFocusCapture=\{updatePopoverPlacement\}/);
  assert.match(styles, /\.answer-usage-control\.is-below \.answer-usage-popover\s*\{[^}]*top:\s*calc\(100% \+ 8px\)[^}]*bottom:\s*auto/);
});
