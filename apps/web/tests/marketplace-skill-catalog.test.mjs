import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const panelPath = new URL("../src/components/SkillCatalogPanel.tsx", import.meta.url);
const buttonPath = new URL("../src/components/MarketplaceInstallButton.tsx", import.meta.url);
const apiPath = new URL("../src/api.ts", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("catalog uses a searchable filterable card grid without opening package details", async () => {
  const [view, panel, api, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(panelPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(view, /skillView === "catalog" \? <SkillCatalogPanel/);
  assert.match(view, /if \(skillView === "catalog" \|\| skillView === "trash"/);
  assert.match(panel, /placeholder="이름, 설명, 태그 검색"/);
  assert.match(panel, /catalog\.facets\.categories\.map/);
  assert.match(panel, /catalog\.facets\.tags\.map/);
  assert.match(panel, /사용자 설치 많은 순/);
  assert.match(panel, /실행 많은 순/);
  assert.match(panel, /좋아요 많은 순/);
  assert.match(panel, /label="사용자 설치"/);
  assert.match(panel, /label="실행"/);
  assert.match(panel, /className=\{`skill-catalog-like/);
  assert.match(api, /request<SkillCatalogResponse>\("\/extensions\/catalog"/);
  assert.match(api, /method: liked \? "PUT" : "DELETE"/);
  assert.match(styles, /\.skill-catalog-layout \{[^}]*grid-template-columns: 248px minmax\(0, 1fr\)/);
  assert.match(styles, /\.skill-catalog-grid \{[^}]*repeat\(auto-fill, minmax\(300px, 1fr\)\)/);
  assert.doesNotMatch(panel, /SKILL\.md|package|상세보기|QA|신뢰/);
});

test("shared Skill lifecycle button keeps English states and invariant geometry", async () => {
  const [view, panel, button, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(panelPath, "utf8"),
    readFile(buttonPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(view, /<MarketplaceInstallButton name=\{item\.name\}/);
  assert.match(panel, /<MarketplaceInstallButton/);
  assert.match(button, /<span>Install<\/span>/);
  assert.match(button, /<span>Installed<\/span>/);
  assert.match(button, /<span>Delete<\/span>/);
  assert.match(button, /<LoaderCircle className="is-running" size=\{13\} \/>/);
  assert.match(styles, /\.skill-install-toggle \{[^}]*width: 96px; min-width: 96px; max-width: 96px;[^}]*height: 26px; min-height: 26px; max-height: 26px;/);
  assert.match(styles, /\.marketplace-install-icon \{[^}]*width: 13px; min-width: 13px; height: 13px;/);
  assert.match(styles, /\.skill-install-toggle:active \{ transform: none; \}/);

  // The existing detail actions remain Korean and use their original control.
  assert.match(view, /\{selected\.canEdit \? "편집" : "내 버전으로 수정"\}/);
  assert.match(view, /\{installation \? "미사용" : "설치"\}/);
  assert.match(view, /deleteConfirmId === selected\.id \? "경고" : "삭제"/);
});
