import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const marketplace = readFileSync(new URL("../src/components/MarketplaceView.tsx", import.meta.url), "utf8");
const projectSettings = readFileSync(new URL("../src/components/ProjectSettings.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("installed Skill project scope uses a multi-select LOV without changing detail layout", () => {
  assert.match(marketplace, /aria-multiselectable="true"/);
  assert.match(marketplace, /전체 해제/);
  assert.match(marketplace, /전체 선택/);
  assert.match(marketplace, /createPortal\(/);
  assert.doesNotMatch(marketplace, /marketplace-project-scope/);
  assert.match(styles, /\.marketplace-project-options\.project-options \{ position: fixed;/);
  assert.match(marketplace, /> 프로젝트 설정<\/button>/);
  assert.match(marketplace, /ref=\{projectScopeMenuRef\}/);
  assert.match(marketplace, /useDismissablePopover\(projectScopeOpen, projectScopeButtonRef, projectScopeMenuRef, setProjectScopeOpen\)/);
  assert.doesNotMatch(marketplace, /프로젝트 사용 설정/);
  assert.match(styles, /\.feature-view\.feature-view \.marketplace-package-summary button \{[^}]*font-size: 14px;/);
  assert.match(styles, /\.marketplace-package-actions > \.marketplace-project-selector > button \{[^}]*font-size: 14px;/);
  assert.match(styles, /\.marketplace-project-options\.project-options button \{ font-size: 14px; \}/);
  assert.match(styles, /\.marketplace-project-options > footer > span \{[^}]*font-size: 14px;/);
});

test("project settings retain unchecked Skill and MCP rows until navigation", () => {
  assert.match(projectSettings, /Skill 및 MCP/);
  assert.match(projectSettings, /setProjectSkills\(\(items\) => items\.map/);
  assert.match(projectSettings, /setProjectMcps\(\(items\) => items\.map/);
  assert.doesNotMatch(projectSettings, /setProjectSkills\(\(items\) => items\.filter/);
  assert.doesNotMatch(projectSettings, /setProjectMcps\(\(items\) => items\.filter/);
});

test("project settings show MCP descriptions instead of slugs", () => {
  assert.match(projectSettings, /api\.mcp\.listCatalog\(controller\.signal\)/);
  assert.match(projectSettings, /mcpDefinitionById\.get\(installation\.definitionId\)\?\.description/);
  assert.match(projectSettings, /setting\.description \|\| "설명 없음"/);
  assert.doesNotMatch(projectSettings, /<small>\{setting\.installation\.slug\}<\/small>/);
});

test("project instructions replace the duplicate business Concept field near project information", () => {
  assert.doesNotMatch(projectSettings, /업무 Concept/);
  assert.doesNotMatch(projectSettings, /setConcept/);
  assert.match(projectSettings, /프로젝트 정보[\s\S]*<InstructionEditor[\s\S]*공유 및 구성원/);
});

test("project information actions sit together in the header with save before delete", () => {
  assert.match(projectSettings, /<header>[\s\S]*프로젝트 정보[\s\S]*정보 저장[\s\S]*프로젝트 삭제[\s\S]*<\/header>[\s\S]*<label>이름/);
  assert.match(projectSettings, /deleteArmed \? "한 번 더 눌러 삭제" : "프로젝트 삭제"/);
  assert.doesNotMatch(projectSettings, /<label>설명[\s\S]*<div className="project-settings-actions">/);
});
