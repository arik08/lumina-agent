import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const panelPath = new URL("../src/components/McpMarketplacePanel.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("MCP installs expose direct account and project actions with the Skill install-state toggle", async () => {
  const panel = await readFile(panelPath, "utf8");

  assert.match(panel, /onClick=\{\(\) => void install\("user"\)\}/);
  assert.match(panel, /"내 계정 설치됨" : "내 계정 설치"/);
  assert.match(panel, /onClick=\{\(\) => void install\("project"\)\}/);
  assert.match(panel, /"내 프로젝트 설치됨" : "내 프로젝트 설치"/);
  assert.doesNotMatch(panel, /<select|installScope/);
  assert.match(panel, /className=\{`marketplace-install-toggle \$\{stateClass\}`\}/);
  assert.match(panel, /"is-installed" : userInstallation \? "is-unused"/);
  assert.match(panel, /<span className="install-toggle-rest">설치됨<\/span><span className="install-toggle-hover">미사용<\/span>/);
  assert.match(panel, /api\.mcp\.setEnabled\(userInstallation\.id, !userInstallation\.enabled\)/);
  assert.match(panel, /api\.mcp\.install\(definition\.id, revision!\.id, "user", undefined/);
});

test("MCP installation status and secret actions keep compact trailing geometry", async () => {
  const [panel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(panel, /className="mcp-installation-actions"/);
  assert.match(panel, /mcp-installation-ready-state/);
  assert.match(panel, /className="mcp-secret-action text-danger"/);
  assert.match(styles, /\.mcp-installation-row > header > \.mcp-installation-actions \{[^}]*flex: 0 0 auto;[^}]*white-space: nowrap;/);
  assert.match(styles, /\.mcp-secret-row > \.mcp-secret-action \{[^}]*grid-column: -2 \/ -1;[^}]*width: max-content;[^}]*justify-self: end;/);
});
