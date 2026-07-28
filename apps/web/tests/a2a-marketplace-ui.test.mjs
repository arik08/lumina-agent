import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const panelPath = new URL("../src/components/A2AMarketplacePanel.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("Marketplace exposes A2A beside Skill and MCP without pretending runtime support exists", async () => {
  const [view, panel] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(panelPath, "utf8"),
  ]);

  assert.match(view, /useState<"skill" \| "mcp" \| "a2a">/);
  assert.match(view, /<Network size=\{14\} \/> A2A/);
  assert.match(view, /marketKind === "a2a" \? <A2AMarketplacePanel \/>/);
  assert.match(view, /marketKind !== "a2a" && <button type="button" aria-label="새로 고침"/);
  assert.match(panel, /A2A v0\.3/);
  assert.match(panel, /설비 이상 대응 Agent/);
  assert.match(panel, /Smart Operations Lab/);
  assert.match(panel, /EquipmentAlertBundle/);
  assert.match(panel, /ShiftHandoverDraft/);
  assert.match(panel, /JSON-RPC · HTTP\/SSE/);
  assert.match(panel, /OAuth 2\.0 \+ mTLS/);
  assert.match(panel, /Agent Card/);
  assert.match(panel, /Streaming task updates/);
  assert.match(panel, /Artifact handoff/);
  assert.match(panel, /외부 발송 전 사용자 승인/);
  assert.match(panel, /<button type="button" disabled aria-describedby="a2a-availability-note">프로젝트에 연결<\/button>/);
  assert.match(panel, /A2A Runtime 적용 후 사용할 수 있습니다\./);
  assert.match(panel, /setSelectedAgentId\(agent\.id\)/);
  assert.match(panel, /aria-current=\{agent\.id === selectedAgent\.id \? "true" : undefined\}/);
});

test("A2A demo catalog has real local navigation, search, empty states, and responsive layout", async () => {
  const [panel, styles] = await Promise.all([
    readFile(panelPath, "utf8"),
    readFile(stylesPath, "utf8"),
  ]);

  assert.match(panel, /useState<A2AView>\("catalog"\)/);
  assert.match(panel, /카탈로그 <span>\{demoAgents\.length\}<\/span>/);
  assert.match(panel, /<small>\{visibleAgents\.length\}개<\/small>/);
  assert.match(panel, /setView\("connected"\)/);
  assert.match(panel, /연결된 A2A Agent가 없습니다\./);
  assert.match(panel, /aria-label="A2A Agent 검색"/);
  assert.match(panel, /setQuery\(""\)/);
  assert.match(styles, /\.a2a-catalog-layout \{[^}]*grid-template-columns: 294px minmax\(0, 1fr\)/);
  assert.match(styles, /\.a2a-agent-detail \{[^}]*overflow-y: auto;/);
  assert.match(styles, /@media \(max-width: 720px\)[\s\S]*?\.a2a-catalog-layout \{ grid-template-columns: minmax\(0, 1fr\);/);
  assert.match(styles, /\.a2a-detail-columns \{[^}]*grid-template-columns: minmax\(0, 1\.55fr\) minmax\(280px, \.8fr\)/);
});

test("Marketplace type tabs keep the same font weight when selection changes", async () => {
  const styles = await readFile(stylesPath, "utf8");

  assert.match(styles, /\.feature-kind-tabs button \{[^}]*font-weight: 500;/);
  assert.match(styles, /\.feature-kind-tabs button\[aria-selected="true"\] \{ color: var\(--cobalt\); \}/);
});
