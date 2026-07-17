import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panelSource = readFileSync(
  new URL("../src/components/OrganizationInstructionsPanel.tsx", import.meta.url),
  "utf8",
);
const panelStyles = readFileSync(
  new URL("../src/components/OrganizationInstructionsPanel.css", import.meta.url),
  "utf8",
);
const apiSource = readFileSync(new URL("../src/api.ts", import.meta.url), "utf8");

test("admin prompt management exposes the prompt hierarchy without a duplicate Concept layer", () => {
  for (const label of [
    "Lumina 고정 system prompt",
    "관리자 기본 지침",
    "내장 Agent 기본 지침",
    "프로젝트 지침",
    "개인 지침",
  ]) {
    assert.match(panelSource, new RegExp(label));
  }
  assert.doesNotMatch(panelSource, /프로젝트 Concept/);
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

test("prompt composition controls stay visually quiet and collapse from the full header row", () => {
  assert.match(panelSource, /className="admin-prompt-composition-toggle"[\s\S]*onClick=\{\(\) => setShowComposition\(false\)\}/);
  assert.match(panelStyles, /\.admin-prompt-sidebar > header > button\.tooltip-control \{[^}]*border: 0;[^}]*background: transparent;/);
  assert.match(panelStyles, /\.admin-prompt-composition-toggle \{[^}]*width: 100%;/);
});

test("prompt composition expands in the same lower slot as its shortcut", () => {
  assert.match(
    panelSource,
    /\{showComposition \? \(\s*<section className="admin-prompt-composition"[\s\S]*<\/section>\s*\) : \(\s*<button className="admin-prompt-composition-shortcut"/,
  );
});

test("project preview selector stays compact so the toolbar note remains readable", () => {
  assert.match(panelStyles, /\.admin-prompt-toolbar \.lumina-select \{[^}]*width: min\(260px, 38vw\);[^}]*flex: 0 1 260px;/);
  assert.doesNotMatch(panelStyles, /\.admin-prompt-toolbar \.select-menu/);
});
