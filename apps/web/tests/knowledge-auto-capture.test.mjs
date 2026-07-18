import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const api = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");
const settings = readFileSync(
  new URL("../src/workspace-frontends/knowledge/KnowledgeSettings.tsx", import.meta.url),
  "utf8",
);

test("Knowledge settings expose one account-level research auto-capture target", () => {
  assert.match(api, /getKnowledgeAutoCapture/);
  assert.match(api, /updateKnowledgeAutoCapture/);
  assert.match(settings, /role="switch"/);
  assert.match(settings, /aria-checked=\{capturesToCurrentSpace\}/);
  assert.match(settings, /분석 결과 자동 축적/);
  assert.match(settings, /최대 60,000자만 AI 추출에 사용/);
  assert.match(settings, /자동 승인 없이 검토함에 제안/);
});
