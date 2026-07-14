import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnUrl = new URL("../src/components/ConversationTurn.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("cache rate uses the agreed five color thresholds", async () => {
  const [turn, styles] = await Promise.all([
    readFile(turnUrl, "utf8"),
    readFile(stylesUrl, "utf8"),
  ]);

  assert.match(turn, /if \(rate <= 50\) return "cache-rate-critical";/);
  assert.match(turn, /if \(rate <= 70\) return "cache-rate-low";/);
  assert.match(turn, /if \(rate <= 80\) return "cache-rate-moderate";/);
  assert.match(turn, /if \(rate <= 90\) return "cache-rate-good";/);
  assert.match(turn, /return "cache-rate-excellent";/);
  assert.match(turn, /tone: cacheRateTone\(cacheRatePercent\)/);
  assert.match(turn, /<td className=\{row\.tone\}>\{row\.tokens\}<\/td>/);
  assert.match(turn, /<td className=\{cumulativeRows\[index\]\?\.tone\}>/);

  for (const tone of ["critical", "low", "moderate", "good", "excellent"]) {
    assert.match(styles, new RegExp(`--cache-rate-${tone}:`));
    assert.match(styles, new RegExp(`td\\.cache-rate-${tone} \\{ color: var\\(--cache-rate-${tone}\\);`));
  }
});
