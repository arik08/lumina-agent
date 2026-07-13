import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("composer uses a compact file-length slider and sends a transient Artifact target", async () => {
  const [app, workspace, types] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/api-types.ts"),
  ]);

  assert.match(app, /자동 10–12k/);
  assert.match(app, /파일 분량/);
  assert.match(app, /type="range"/);
  assert.match(app, /onChange=\{\(event\) => selectStep/);
  assert.doesNotMatch(app, /onInput=/);
  for (const key of ["Home", "End", "ArrowRight", "ArrowUp", "ArrowLeft", "ArrowDown"]) {
    assert.match(app, new RegExp(`event\\.key.{0,80}${key}|${key}.{0,80}event\\.key`, "s"));
  }
  assert.match(app, /data-testid="artifact-length-slider"/);
  assert.match(app, /채팅 답변이 아닌 생성 파일의 목표 분량/);
  for (const target of ["10_000", "12_000", "16_000", "24_000", "32_000", "40_000"]) {
    assert.match(app, new RegExp(`value: ${target}`));
  }
  assert.match(app, /warning: "장문"/);
  assert.match(app, /warning: "최대"/);
  assert.match(app, /selectedIndex >= 4/);
  assert.match(app, /targetOutputTokens \?\? undefined/);
  assert.match(app, /setTargetOutputTokens\(null\)/);
  assert.match(workspace, /targetOutputTokens\?: number/);
  assert.match(workspace, /currentSettings\.outputMode !== "chat" && targetOutputTokens/);
  assert.match(types, /targetOutputTokens\?: number/);
});
