import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panelSource = readFileSync(
  new URL("../src/components/OrganizationInstructionsPanel.tsx", import.meta.url),
  "utf8",
);
const apiSource = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");

test("admin prompt management exposes the complete six-layer overview", () => {
  for (const label of [
    "Lumina 고정 system prompt",
    "관리자 기본 지침",
    "내장 Agent 기본 지침",
    "프로젝트 Concept",
    "프로젝트 지침",
    "개인 지침",
  ]) {
    assert.match(panelSource, new RegExp(label));
  }
  assert.match(panelSource, /실제 Run 프롬프트 합성 구조/);
  assert.match(panelSource, /공유 프로젝트에서는 개인 지침을 합성하지 않습니다/);
  assert.match(panelSource, /모든 변경은 새 Run부터 적용/);
});

test("internal prompts are editable while project-scoped layers remain read only", () => {
  assert.match(panelSource, /api\.instructions\.updateRuntimePrompt/);
  assert.match(panelSource, /한 번 더 눌러 기본값 복원/);
  assert.match(panelSource, /function ReadOnlyPrompt/);
  assert.match(panelSource, /<SelectMenu/);
  assert.doesNotMatch(panelSource, /<select/);
  assert.doesNotMatch(panelSource, /role="dialog"/);
  assert.match(apiSource, /\/admin\/runtime-prompts/);
});
