import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnUrl = new URL("../src/components/ConversationTurn.tsx", import.meta.url);
const globalTooltipUrl = new URL("../src/components/GlobalTooltip.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("usage popover uses the global layer and only flips below at the viewport edge", async () => {
  const [turn, globalTooltip, styles] = await Promise.all([
    readFile(turnUrl, "utf8"),
    readFile(globalTooltipUrl, "utf8"),
    readFile(stylesUrl, "utf8"),
  ]);

  assert.match(turn, /aria-describedby=\{popoverOpen \? popoverId : undefined\}/);
  assert.match(turn, /<GlobalTooltipLayer anchor=\{controlRef\.current\} className="answer-usage-popover" id=\{popoverId\} open=\{popoverOpen\}>/);
  assert.match(globalTooltip, /createPortal\([\s\S]*?document\.body/s);
  assert.match(globalTooltip, /const spaceAbove = anchorRect\.top - viewportPadding - tooltipGap/);
  assert.match(globalTooltip, /const spaceBelow = window\.innerHeight - anchorRect\.bottom - viewportPadding - tooltipGap/);
  assert.match(globalTooltip, /spaceAbove < layerRect\.height && spaceBelow > spaceAbove \? "below" : "above"/);
  assert.match(styles, /\.global-tooltip-layer\s*\{[^}]*position:\s*fixed;[^}]*z-index:\s*10000/s);
  assert.doesNotMatch(styles, /\.answer-usage-control\.is-below/);
});
