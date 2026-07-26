import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const panelPath = new URL("../src/components/McpMarketplacePanel.tsx", import.meta.url);
const adminPanelPath = new URL("../src/components/AdminMcpPanel.tsx", import.meta.url);
const adminViewPath = new URL("../src/components/AdminView.tsx", import.meta.url);
const marketplaceViewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const appPath = new URL("../src/App.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("MCP installs once and uses the shared multi-project scope UI", async () => {
  const panel = await readFile(panelPath, "utf8");

  assert.match(panel, /onClick=\{\(\) => void install\(\)\}/);
  assert.doesNotMatch(panel, /내 계정 설치|내 프로젝트 설치/);
  assert.match(panel, /api\.mcp\.updateProjects/);
  assert.match(panel, /aria-label="MCP를 사용할 프로젝트"/);
  assert.match(panel, /aria-multiselectable="true"/);
  assert.match(panel, /전체 해제/);
  assert.match(panel, /전체 선택/);
  assert.match(panel, /> 프로젝트 설정<\/button>/);
  assert.match(panel, /ref=\{projectScopeMenuRef\}/);
  assert.match(panel, /useDismissablePopover\(projectScopeOpen, projectScopeButtonRef, projectScopeMenuRef, setProjectScopeOpen\)/);
  assert.match(panel, /toggleCatalogInstallation\(selected\)/);
  assert.match(panel, /"처리 중" : "미사용"/);
  assert.doesNotMatch(panel, /<select|installScope/);
  assert.match(panel, /className=\{`marketplace-install-toggle \$\{stateClass\}`\}/);
  assert.match(panel, /const stateClass = userInstallation \? "is-installed" : ""/);
  assert.match(panel, /<span className="install-toggle-rest">설치됨<\/span><span className="install-toggle-hover">미사용<\/span>/);
  assert.match(panel, /await api\.mcp\.uninstall\(userInstallation\.id\)/);
  assert.match(panel, /current\.filter\(\(item\) => item\.id !== userInstallation\.id\)/);
  assert.doesNotMatch(panel, /api\.mcp\.setEnabled\(userInstallation\.id/);
  assert.match(panel, /api\.mcp\.install\(definition\.id, revision!\.id, "user", undefined/);
  assert.match(panel, /const verified = await api\.mcp\.verify\(installed\.id\)/);
  assert.match(panel, /item\.id === verified\.id \? verified : item/);
});

test("MCP installation status and secret actions keep compact trailing geometry", async () => {
  const [panel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(panel, /className="mcp-installation-actions"/);
  assert.match(panel, /mcp-installation-ready-state/);
  assert.match(panel, /api\.mcp\.verify\(item\.id, controller\.signal\)/);
  assert.match(panel, /if \(installation\.healthStatus === "failed"\) return "사용 불가"/);
  assert.match(panel, /installation\.ready \? "is-ready" : "is-pending"/);
  assert.match(panel, /setVerifyingInstallationIds\(new Set\(verifiable\.map\(\(item\) => item\.id\)\)\)/);
  assert.match(panel, /const verified = await api\.mcp\.verify\(item\.id, controller\.signal\)[\s\S]*?finally[\s\S]*?next\.delete\(item\.id\)/);
  assert.match(panel, /verifyingInstallationIds\.has\(installation\.id\) \? <LoaderCircle className="is-running" size=\{13\} \/> : null/);
  assert.match(panel, /selectedConnection\?\.healthStatus \?\? currentRevision\.healthStatus/);
  assert.match(panel, /mcp-secret-action text-danger/);
  assert.match(styles, /\.mcp-installation-row > header > \.mcp-installation-actions \{[^}]*flex: 0 0 auto;[^}]*white-space: nowrap;/);
  assert.match(styles, /\.mcp-secret-row > \.mcp-secret-action \{[^}]*grid-column: -2 \/ -1;[^}]*width: max-content;[^}]*justify-self: end;/);
});

test("MCP installation can run a real LLM answer test inline", async () => {
  const [panel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(panel, /api\.mcp\.testAnswer\(installation\.id, projectId, prompt\)/);
  assert.match(panel, /실제 답변 테스트/);
  assert.match(panel, /providerId.*modelKey.*toolName/);
  assert.match(styles, /\.mcp-answer-test-result/);
});

test("MCP detail shows whether its Skill wrapper is applied", async () => {
  const [panel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(panel, /const skillWrapperApplied = selected\?\.skillWrapper\?\.wrapped/);
  assert.match(panel, /skillWrapperApplied === true \? "적용" : skillWrapperApplied === false \? "누락" : "확인 불가"/);
  assert.match(panel, /skillWrapperApplied === false && <div className="mcp-wrapper-warning"/);
  assert.match(panel, /Skill 래퍼가 없습니다\./);
  assert.match(panel, /source: skill-mcp:\{selected\.slug\}/);
  assert.match(styles, /\.detail-badges \.is-wrapper-ready/);
  assert.match(styles, /\.detail-badges \.is-wrapper-missing/);
  assert.match(styles, /\.mcp-wrapper-warning \{/);
});

test("MCP destructive actions use inline same-button confirmation instead of popups", async () => {
  const [panel, adminPanel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(adminPanelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.doesNotMatch(panel, /window\.confirm/);
  assert.doesNotMatch(adminPanel, /window\.confirm/);
  assert.match(panel, /uninstallConfirmId !== installation\.id[\s\S]*?setUninstallConfirmId\(installation\.id\)/);
  assert.match(panel, /unbindConfirmKey !== key[\s\S]*?setUnbindConfirmKey\(key\)/);
  assert.match(panel, /"한 번 더 눌러 설치 해제"/);
  assert.match(styles, /button\.mcp-uninstall-action\.is-delete-armed span\s*\{[^}]*font-size:\s*11\.5px;/);
  assert.match(panel, /"한 번 더 눌러 연결 해제"/);
  assert.match(adminPanel, /approveConfirmId !== revisionId[\s\S]*?setApproveConfirmId\(revisionId\)/);
  assert.match(adminPanel, /disableConfirmId !== selected\.id[\s\S]*?setDisableConfirmId\(selected\.id\)/);
  assert.match(adminPanel, /"한 번 더 눌러 승인"/);
  assert.match(adminPanel, /"한 번 더 눌러 비활성화"/);
  assert.match(styles, /\.mcp-installation-row > header button\.mcp-uninstall-action\.is-delete-armed \{/);
  assert.match(styles, /\.mcp-secret-row > \.mcp-secret-action\.is-delete-armed \{/);
  assert.match(styles, /\.admin-mcp-detail button\.is-delete-armed/);
});

test("Marketplace MCP exposes definition management only to administrators", async () => {
  const [adminView, marketplaceView, app] = await Promise.all([
    readFile(adminViewPath, "utf8"),
    readFile(marketplaceViewPath, "utf8"),
    readFile(appPath, "utf8"),
  ]);

  assert.doesNotMatch(adminView, /AdminMcpPanel|tab === "mcp"|> MCP<\/button>/);
  assert.match(marketplaceView, /interface MarketplaceViewProps[\s\S]*?canManage: boolean/);
  assert.match(marketplaceView, /\{canManage && <button[\s\S]*?정의 관리<\/button>\}/);
  assert.match(marketplaceView, /mcpView === "admin" && canManage \? <AdminMcpPanel/);
  assert.match(app, /<MarketplaceView[\s\S]*?canManage=\{isAdmin\}/);
});
