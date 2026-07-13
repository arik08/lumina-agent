import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const editorSource = readFileSync(new URL("../src/components/InstructionEditor.tsx", import.meta.url), "utf8");
const settingsSource = readFileSync(new URL("../src/components/ProjectSettings.tsx", import.meta.url), "utf8");

test("personal and project instructions hide internal version details", () => {
  assert.doesNotMatch(editorSource, /snapshot\.digest\.slice/);
  assert.doesNotMatch(editorSource, /revision \$\{updated\.revision\}/);
  assert.match(editorSource, /setNotice\("지침을 저장했습니다\."\)/);
});

test("project instructions explain direct management by writable members", () => {
  assert.match(settingsSource, /프로젝트를 편집할 수 있는 구성원은 언제든 수정할 수 있습니다/);
  assert.doesNotMatch(settingsSource, /편집은 프로젝트 Owner와 Admin만/);
});
