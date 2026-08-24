import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [turn, styles] = await Promise.all([
  readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
]);

test("registered source links render as circled citation markers", () => {
  assert.match(turn, /const targetByUrl = useMemo/);
  assert.match(turn, /targetByUrl\.get\(citationUrlKey\(href\)/);
  assert.match(turn, /if \(citationTarget\) return <CitationMarker target=\{citationTarget\} \/>/);
  assert.match(turn, /"①", "②", "③"/);
});

test("citation tooltip identifies the site and quoted evidence", () => {
  assert.match(turn, /target\.source\.domain \|\| target\.source\.title/);
  assert.match(turn, /target\.source\.verbatimExcerpt/);
  assert.match(turn, /onMouseEnter=\{\(\) => setTooltipOpen\(true\)\}/);
  assert.match(turn, /onFocus=\{\(\) => setTooltipOpen\(true\)\}/);
  assert.match(styles, /\.citation-tooltip q \{[^}]*font-size: 13px;/);
});
