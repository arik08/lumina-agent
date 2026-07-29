import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";


const appPath = new URL("../src/App.tsx", import.meta.url);
const typesPath = new URL("../src/api-types.ts", import.meta.url);


test("long-context models default to a named 272K mode with an opt-in maximum mode", async () => {
  const [app, types] = await Promise.all([
    readFile(appPath, "utf8"),
    readFile(typesPath, "utf8"),
  ]);

  assert.match(app, /<strong>컨텍스트 용량 모드<\/strong>/);
  assert.match(app, /표준 모드는 272K 가격 경계 앞에 약 20K만 남기고 압축합니다/);
  assert.match(app, /standard_context_compaction_reserve_tokens/);
  assert.match(app, /"자동 압축 여유"/);
  assert.match(app, /value=\{selectedAdminSettingsModel\.contextCapacityMode \?\? "standard"\}/);
  assert.match(app, /value: "maximum".*토큰 \(고비용\)/);
  assert.match(app, /saveAdminContextCapacityMode\(value as "standard" \| "maximum"\)/);
  assert.match(types, /contextCapacityMode: "standard" \| "maximum" \| null/);
  assert.match(types, /maximumContextWindow: number \| null/);
  assert.match(types, /maximumContextUsageRatio: number \| null/);
  assert.match(types, /standardContextReserveTokens: number \| null/);
});
