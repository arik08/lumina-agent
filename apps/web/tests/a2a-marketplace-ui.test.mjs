import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const viewPath = new URL("../src/components/MarketplaceView.tsx", import.meta.url);
const panelPath = new URL("../src/components/A2AMarketplacePanel.tsx", import.meta.url);
const stylesPath = new URL("../src/styles.css", import.meta.url);

test("Marketplace exposes realistic but explicitly demo-only A2A connections", async () => {
  const [view, panel] = await Promise.all([
    readFile(viewPath, "utf8"),
    readFile(panelPath, "utf8"),
  ]);

  assert.match(view, /useState<"skill" \| "mcp" \| "a2a">/);
  assert.match(view, /<Network size=\{14\} \/> A2A/);
  assert.match(view, /marketKind === "a2a" \? <A2AMarketplacePanel \/>/);
  assert.match(view, /marketKind !== "a2a" && <button type="button" aria-label="새로 고침"/);
  assert.match(panel, /A2A v0\.3/);
  assert.match(panel, /원가분석 AI Agent/);
  assert.match(panel, /publisher: "Enhans"/);
  assert.match(panel, /POSCO Data Lake · Cost Mart/);
  assert.match(panel, /CostScenarioWorkbook/);
  assert.match(panel, /name: "MIH Agent"/);
  assert.match(panel, /publisher: "Salesforce"/);
  assert.match(panel, /MarketingIntelligenceBrief/);
  assert.match(panel, /설비관리 GPT/);
  assert.match(panel, /EquipmentHealthSummary/);
  assert.doesNotMatch(panel, /조달 리서치 코디네이터/);
  assert.doesNotMatch(panel, /설비 이상 대응 Agent/);
  assert.match(panel, /JSON-RPC · HTTP\/SSE/);
  assert.match(panel, /OAuth 2\.0 \+ mTLS/);
  assert.match(panel, /Agent Card/);
  assert.match(panel, /Streaming task updates/);
  assert.match(panel, /Artifact handoff/);
  assert.match(panel, /실제 연결 전 보안·권한·데이터 경계 검토가 필요합니다/);
  assert.match(panel, /연결됨 <span>\{connectedAgents\.length\}<\/span>/);
  assert.match(panel, /<button type="button" disabled aria-describedby="a2a-availability-note">연결됨<\/button>/);
  assert.match(panel, /표시 전용 연결이며 실제 작업은 실행되지 않습니다\./);
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
