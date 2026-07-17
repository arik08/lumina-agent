import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const panelPath = new URL("../src/components/SkillCatalogPanel.tsx", import.meta.url);
const buttonPath = new URL("../src/components/MarketplaceInstallButton.tsx", import.meta.url);
const apiPath = new URL("../src/api.ts", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("catalog uses a searchable card grid with installed-only package viewing", async () => {
  const [view, panel, api, styles] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(panelPath, "utf8"),
    readFile(apiPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(view, /skillView === "catalog" \? <SkillCatalogPanel/);
  assert.match(view, /useEffect\(\(\) => \{\s*if \(hasCachedCatalog\) lastVisibleCatalogRef\.current = catalog;\s*\}, \[catalog, hasCachedCatalog\]\)/);
  assert.match(view, /const visibleCatalog = hasCachedCatalog \? catalog : lastVisibleCatalogRef\.current/);
  assert.match(view, /const selectedTagCount = catalogTag[\s\S]*visibleCatalog\.facets\.tags\.find\(\(item\) => item\.value === catalogTag\)\?\.count/);
  assert.match(view, /const catalogTabCount = hasCachedCatalog[\s\S]*\? catalog\.total[\s\S]*: selectedTagCount \?\? \(visibleCatalog\.total \|\| items\.length\)/);
  assert.match(view, /카탈로그 <span>\{catalogTabCount\}<\/span>/);
  assert.doesNotMatch(view, /카탈로그 <span>\{catalog\.total \|\| items\.length\}<\/span>/);
  assert.match(view, /catalog=\{visibleCatalog\}/);
  assert.match(view, /setSelectedId\(target\.id\);\s*setEnteredInstalledFromCatalog\(true\);\s*setSkillView\("installed"\);/);
  assert.match(view, /window\.history\.pushState\(\{[\s\S]*luminaMarketplaceCatalogDetail:[\s\S]*skillId: target\.id/);
  assert.match(view, /enteredInstalledFromCatalog && skillView === "installed"/);
  assert.match(view, /<ArrowLeft size=\{14\} \/> 뒤로가기/);
  assert.match(view, /const returnToCatalog = \(\) => \{[\s\S]*window\.history\.back\(\);[\s\S]*setSkillView\("catalog"\);/);
  assert.match(view, /window\.addEventListener\("popstate", handlePopState\)/);
  assert.match(view, /typeof detail\.skillId === "string"[\s\S]*setSelectedId\(detail\.skillId\)/);
  assert.match(panel, /placeholder="이름, 설명, 태그 검색"/);
  assert.match(panel, /catalog\.facets\.categories\.map/);
  assert.match(panel, /catalog\.facets\.tags\.map/);
  assert.equal(panel.match(/className="skill-catalog-filter-grid"/g)?.length, 2);
  assert.match(panel, /<span>#\{item\.value\}<\/span><small>\{item\.count\}<\/small>/);
  assert.match(panel, /사용자 설치 많은 순/);
  assert.match(panel, /실행 많은 순/);
  assert.match(panel, /좋아요 많은 순/);
  assert.match(panel, /label="설치 사용자"/);
  assert.match(panel, /label="Skill 실행 횟수"/);
  assert.match(panel, /data-tooltip=\{label\}/);
  assert.match(panel, /data-tooltip="좋아요"/);
  assert.match(panel, /className=\{`skill-catalog-card \$\{item\.likedByMe \? "is-liked" : ""\}`\.trim\(\)\}/);
  assert.match(panel, /className=\{`skill-catalog-like/);
  assert.match(panel, /item\.installed && <button className="skill-catalog-view tooltip-control"/);
  assert.match(panel, /data-tooltip="보기"/);
  assert.match(panel, /<Eye size=\{14\} \/><\/button>/);
  assert.doesNotMatch(panel, />View<\/span>/);
  assert.match(panel, /\(item\.installed \|\| item\.canInstall\) && <MarketplaceInstallButton/);
  assert.match(view, /scrollPosition=\{catalogScrollPosition\}/);
  assert.match(view, /onScrollPositionChange=\{setCatalogScrollPosition\}/);
  assert.match(panel, /scrollRef\.current\.scrollTop = scrollPosition/);
  assert.match(panel, /window\.requestAnimationFrame\(restoreScrollPosition\)/);
  assert.match(panel, /onScrollPositionChange\(scrollRef\.current\?\.scrollTop \?\? 0\)/);
  assert.doesNotMatch(panel, /onScroll=/);
  assert.match(api, /request<SkillCatalogResponse>\("\/extensions\/catalog"/);
  assert.match(api, /method: liked \? "PUT" : "DELETE"/);
  assert.match(styles, /\.skill-catalog-layout \{[^}]*grid-template-columns: 248px minmax\(0, 1fr\)/);
  assert.match(styles, /\.skill-catalog-search > span:last-child \{[^}]*min-width: 0;[^}]*margin-inline-end: var\(--space-2\)/);
  assert.match(styles, /\.skill-catalog-grid \{[^}]*repeat\(auto-fill, minmax\(300px, 1fr\)\)/);
  assert.match(styles, /\.skill-catalog-scroll \{[^}]*overflow-anchor: none;/);
  assert.match(styles, /\.skill-catalog-card\.is-liked \{[^}]*background: var\(--surface-selected\)/);
  assert.match(styles, /\.skill-catalog-metrics \{[^}]*gap: var\(--space-5\)/);
  assert.match(styles, /\.skill-catalog-like\.is-liked \{[^}]*background: transparent;[^}]*color: var\(--cobalt\);/);
  assert.match(styles, /\.skill-catalog-like\.is-liked:not\(:disabled\):hover \{[^}]*background: transparent;[^}]*color: var\(--cobalt-hover\);/);
  assert.doesNotMatch(styles, /\.skill-catalog-like\.is-liked \{[^}]*(?:box-shadow|transform):/);
  assert.doesNotMatch(panel, /SKILL\.md|QA|신뢰/);
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
  assert.match(button, /const justInstalled = installed && !previousInstalled\.current/);
  assert.match(button, /keepInstalledVisible \? "keep-installed-visible" : ""/);
  assert.match(button, /onMouseMove=\{releaseInstalledConfirmation\}/);
  assert.match(button, /onMouseLeave=\{releaseInstalledConfirmation\}/);
  assert.match(styles, /\.feature-view\.feature-view \.skill-install-toggle \{[^}]*width: 80px; min-width: 80px; max-width: 80px;[^}]*height: 26px; min-height: 26px; max-height: 26px;/);
  assert.match(styles, /\.feature-view\.feature-view \.skill-install-toggle \{[^}]*padding: 0 6px;[^}]*font-size: 11px;/);
  assert.match(styles, /\.feature-view\.feature-view \.marketplace-skill-row > \.skill-install-toggle \{[^}]*margin: 7px var\(--space-3\) 0 0;/);
  assert.match(styles, /\.marketplace-install-icon \{[^}]*width: 13px; min-width: 13px; height: 13px;/);
  assert.match(styles, /\.feature-view\.feature-view \.skill-install-toggle\.is-installed \{[^}]*border-color: color-mix\(in oklab, var\(--success\) 24%, var\(--line\)\);[^}]*background: color-mix\(in oklab, var\(--success\) 8%, var\(--surface\)\);[^}]*color: var\(--success\);/);
  assert.match(styles, /\.skill-install-toggle:active \{ transform: none; \}/);
  assert.match(styles, /\.skill-install-toggle\.is-installed\.keep-installed-visible:hover:not\(:focus-visible\) \.install-toggle-rest \{ opacity: 1; \}/);
  assert.match(styles, /\.skill-install-toggle\.is-installed\.keep-installed-visible:hover:not\(:focus-visible\) \.install-toggle-hover \{ opacity: 0; \}/);

  // The existing detail actions remain Korean and use their original control.
  assert.match(view, /\{selected\.canEdit \? "편집" : "내 버전으로 수정"\}/);
  assert.match(view, /\{installation \? "미사용" : "설치"\}/);
  assert.match(view, /className=\{`marketplace-detail-install-toggle \$\{installation \? "is-disable" : "is-primary lumina-primary-action"\}`\}/);
  assert.match(view, /installation \? <Power size=\{14\} \/> : <Download size=\{14\} \/>/);
  assert.match(styles, /\.marketplace-package-summary button\.marketplace-detail-install-toggle \{ width: 92px; min-width: 92px; max-width: 92px; justify-content: center; white-space: nowrap; \}/);
  assert.match(styles, /\.marketplace-package-summary button\.is-disable \{[^}]*var\(--warning\)/);
  assert.match(view, /deleteConfirmId === selected\.id \? "경고" : "삭제"/);
});
