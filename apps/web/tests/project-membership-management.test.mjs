import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("project settings manage registered accounts inline", async () => {
  const [view, featureApi, types, styles, selectMenu, selectStyles] = await Promise.all([
    read("../src/components/ProjectSettings.tsx"),
    read("../src/feature-api.ts"),
    read("../src/api-types.ts"),
    read("../src/components/ProjectSettings.css"),
    read("../src/components/SelectMenu.tsx"),
    read("../src/components/SelectMenu.css"),
  ]);

  assert.match(types, /interface ProjectMembership/);
  assert.match(featureApi, /export const projectMembershipsApi = \{/);
  assert.match(featureApi, /add: addProjectMembership/);
  assert.match(featureApi, /update: updateProjectMembership/);
  assert.match(featureApi, /remove: removeProjectMembership/);
  assert.match(view, /공유 및 구성원/);
  assert.match(view, /<span>계정명<\/span>/);
  assert.doesNotMatch(view, /<span>등록 계정<\/span>/);
  assert.match(view, /type="email"[\s\S]*?name@posco\.com/);
  assert.match(view, /await api\.projectMemberships\.add/);
  assert.match(view, /await api\.projectMemberships\.update/);
  assert.match(view, /<SelectMenu/);
  assert.match(selectMenu, /aria-haspopup="listbox"/);
  assert.match(selectMenu, /role="option"/);
  assert.doesNotMatch(view, /<select/);
  assert.match(view, /memberDeleteArmed !== membership\.id[\s\S]*?setMemberDeleteArmed\(membership\.id\)/);
  assert.match(view, /await api\.projectMemberships\.remove/);
  assert.match(view, /한 번 더 눌러 제거/);
  assert.doesNotMatch(view, /window\.confirm|<dialog|modal/i);
  assert.match(styles, /\.project-membership-settings\s*\{/);
  assert.match(styles, /\.project-member-list article\s*\{/);
  assert.match(selectStyles, /\.lumina-select-menu\s*\{[\s\S]*?border-radius: var\(--radius-menu\);/);
  assert.match(view, /data-tooltip="프로젝트 추가"/);
  assert.doesNotMatch(styles, /tooltip-control::after/);
});
