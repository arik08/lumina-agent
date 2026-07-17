import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const panelPath = new URL("../src/components/McpMarketplacePanel.tsx", import.meta.url);
const adminPanelPath = new URL("../src/components/AdminMcpPanel.tsx", import.meta.url);
const adminViewPath = new URL("../src/components/AdminView.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("MCP installs expose direct account and project actions and return to install after removal", async () => {
  const panel = await readFile(panelPath, "utf8");

  assert.match(panel, /onClick=\{\(\) => void install\("user"\)\}/);
  assert.match(panel, /"내 계정 설치됨" : "내 계정 설치"/);
  assert.match(panel, /onClick=\{\(\) => void install\("project"\)\}/);
  assert.match(panel, /"내 프로젝트 설치됨" : "내 프로젝트 설치"/);
  assert.doesNotMatch(panel, /<select|installScope/);
  assert.match(panel, /className=\{`marketplace-install-toggle \$\{stateClass\}`\}/);
  assert.match(panel, /const stateClass = userInstallation \? "is-installed" : ""/);
  assert.match(panel, /<span className="install-toggle-rest">설치됨<\/span><span className="install-toggle-hover">미사용<\/span>/);
  assert.match(panel, /await api\.mcp\.uninstall\(userInstallation\.id\)/);
  assert.match(panel, /current\.filter\(\(item\) => item\.id !== userInstallation\.id\)/);
  assert.doesNotMatch(panel, /api\.mcp\.setEnabled\(userInstallation\.id/);
  assert.match(panel, /api\.mcp\.install\(definition\.id, revision!\.id, "user", undefined/);
});

test("MCP installation status and secret actions keep compact trailing geometry", async () => {
  const [panel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(panel, /className="mcp-installation-actions"/);
  assert.match(panel, /mcp-installation-ready-state/);
  assert.match(panel, /mcp-secret-action text-danger/);
  assert.match(styles, /\.mcp-installation-row > header > \.mcp-installation-actions \{[^}]*flex: 0 0 auto;[^}]*white-space: nowrap;/);
  assert.match(styles, /\.mcp-secret-row > \.mcp-secret-action \{[^}]*grid-column: -2 \/ -1;[^}]*width: max-content;[^}]*justify-self: end;/);
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
  assert.match(panel, /"한 번 더 눌러 연결 해제"/);
  assert.match(adminPanel, /approveConfirmId !== revisionId[\s\S]*?setApproveConfirmId\(revisionId\)/);
  assert.match(adminPanel, /disableConfirmId !== selected\.id[\s\S]*?setDisableConfirmId\(selected\.id\)/);
  assert.match(adminPanel, /"한 번 더 눌러 승인"/);
  assert.match(adminPanel, /"한 번 더 눌러 비활성화"/);
  assert.match(styles, /\.mcp-installation-row > header button\.mcp-uninstall-action\.is-delete-armed \{/);
  assert.match(styles, /\.mcp-secret-row > \.mcp-secret-action\.is-delete-armed \{/);
  assert.match(styles, /\.admin-mcp-detail button\.is-delete-armed/);
});

test("system management exposes the administrator MCP panel", async () => {
  const adminView = await readFile(adminViewPath, "utf8");

  assert.match(adminView, /import \{ AdminMcpPanel \} from "\.\/AdminMcpPanel"/);
  assert.match(adminView, /aria-selected=\{tab === "mcp"\}[\s\S]*?<ServerCog size=\{15\} \/> MCP/);
  assert.match(adminView, /tab === "mcp" && <AdminMcpPanel \/>/);
  assert.match(adminView, /tab === "policy" \|\| tab === "mcp"/);
});
