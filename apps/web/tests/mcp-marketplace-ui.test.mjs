import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const panelPath = new URL("../src/components/McpMarketplacePanel.tsx", import.meta.url);

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
