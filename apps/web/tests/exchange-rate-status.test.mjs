import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [apiSource, turnSource, styles] = await Promise.all([
  readFile(new URL("../src/api.ts", import.meta.url), "utf8"),
  readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8"),
  readFile(new URL("../src/styles.css", import.meta.url), "utf8"),
]);

test("exchange-rate requests retry stale and unavailable results after a short cache", () => {
  assert.match(apiSource, /status: "fresh" \| "stale" \| "unavailable"/);
  assert.match(apiSource, /USD_KRW_FRESH_CACHE_MS = 6 \* 60 \* 60 \* 1_000/);
  assert.match(apiSource, /USD_KRW_RETRY_CACHE_MS = 5 \* 60 \* 1_000/);
  assert.match(apiSource, /result\.status === "fresh" \? USD_KRW_FRESH_CACHE_MS : USD_KRW_RETRY_CACHE_MS/);
  assert.match(apiSource, /Date\.now\(\) >= usdKrwExchangeRateExpiresAt/);
});

test("usage cost hides exchange-rate metadata while preserving conversion", () => {
  assert.match(turnSource, /const usdKrwRate = exchangeRate\?\.rate/);
  assert.match(turnSource, /Math\.round\(value \* usdKrwRate\)/);
  assert.doesNotMatch(turnSource, /exchangeRateStatus/);
  assert.doesNotMatch(turnSource, /answer-usage-rate-status/);
  assert.doesNotMatch(styles, /answer-usage-rate-status/);
});
