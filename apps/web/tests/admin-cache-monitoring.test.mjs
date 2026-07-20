import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const adminView = await readFile(new URL("../src/components/AdminView.tsx", import.meta.url), "utf8");
const apiTypes = await readFile(new URL("../src/api-types.ts", import.meta.url), "utf8");

test("monitoring separates first and subsequent model-call cache metrics", () => {
  assert.match(adminView, /aria-label="Prefix cache 모니터링"/);
  assert.match(adminView, /Run 첫 호출[\s\S]*?cache\.firstCall\.cacheHitRatioPercent/);
  assert.match(adminView, /Run 내부 후속[\s\S]*?cache\.subsequentCalls\.cacheHitRatioPercent/);
});

test("monitoring groups cache usage by the provider static digest", () => {
  assert.match(adminView, /aria-label="Prompt cache static digest별 집계"/);
  assert.match(adminView, /usageStatistics\.cache\.byStaticDigest\.map/);
  assert.match(apiTypes, /byStaticDigest: Array<AdminCacheMetric/);
  assert.match(adminView, /item\.firstCall\.cacheHitRatioPercent/);
  assert.match(adminView, /item\.subsequentCalls\.cacheHitRatioPercent/);
  assert.match(apiTypes, /cacheWriteTokens: number/);
});
