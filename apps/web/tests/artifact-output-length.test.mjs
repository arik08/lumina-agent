import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("composer sends a transient MyHarness-style Artifact length target", async () => {
  const [app, workspace, types] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);

  assert.match(app, /자동 · 일반 보고서 10–12k/);
  for (const target of ["10000", "12000", "16000", "24000", "32000", "40000"]) {
    assert.match(app, new RegExp(`id: "${target}"`));
  }
  assert.match(app, /파일 생성 시 목표 분량입니다\. 채팅 답변 길이에는 적용하지 않습니다\./);
  assert.match(app, /targetOutputTokens \?\? undefined/);
  assert.match(app, /setTargetOutputTokens\(null\)/);
  assert.match(workspace, /targetOutputTokens\?: number/);
  assert.match(workspace, /currentSettings\.outputMode !== "chat" && targetOutputTokens/);
  assert.match(types, /targetOutputTokens\?: number/);
});
