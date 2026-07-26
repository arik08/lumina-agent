import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const settingsSource = readFileSync(
  new URL("../src/components/ProjectSettings.tsx", import.meta.url),
  "utf8",
);

test("personal and project instruction editors explain their empty state", () => {
  assert.match(settingsSource, /개인 프로젝트에 적용되는 나만의 전역 작업 지침/);
  assert.match(settingsSource, /공유 프로젝트에는 적용되지 않으며 조직 정책과 프로젝트 지침보다 우선할 수 없습니다/);
  assert.match(settingsSource, /현재 프로젝트의 모든 Run과 구성원에게 공통 적용되는 업무 지침/);
  assert.match(settingsSource, /개인 지침보다 우선하며 이 프로젝트 밖에는 적용되지 않습니다/);
  assert.match(settingsSource, /placeholder=\{PERSONAL_INSTRUCTIONS_PLACEHOLDER\}/);
  assert.match(settingsSource, /placeholder=\{PROJECT_INSTRUCTIONS_PLACEHOLDER\}/);
});
