import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("completed chat turns keep stable props and skip offscreen rendering work", async () => {
  const [app, turn, styles] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/components/ConversationTurn.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(turn, /export const AssistantTurn = memo\(function AssistantTurn/);
  assert.match(turn, /const terminalPresentationReady = terminal && displayedText === sanitizedAssistantText;/);
  assert.match(turn, /className=\{`turn-set \$\{terminalPresentationReady \? "is-terminal" : "is-active"\}`\}/);
  assert.match(turn, /terminalPresentationReady && researchVerification === "unverified"/);
  assert.match(turn, /\{terminalPresentationReady && \(/);
  assert.match(turn, /export function sessionUsageRevision/);
  assert.match(app, /cumulativeUsageCacheRef\.current\?\.revision !== activeSessionUsageRevision/);
  assert.match(app, /onToggleCall=\{toggleOpenCall\}/);
  assert.match(app, /onCopyTool=\{copyTool\}/);
  assert.match(app, /onOpenArtifact=\{openArtifact\}/);
  assert.match(app, /onBranch=\{branchFromMessage\}/);
  assert.match(app, /onShare=\{shareFromMessage\}/);
  assert.match(styles, /\.turn-set\.is-terminal \{[^}]*content-visibility: auto;[^}]*contain-intrinsic-size: auto 520px;/s);
  assert.match(styles, /\.conversation-scroll \{[^}]*overflow-anchor: none;/);
});

test("streaming block placeholders keep their compact shared height", async () => {
  const styles = await read("../src/styles.css");

  assert.match(styles, /\.stream-block-pending \{[^}]*min-height: 58px;/);
  assert.doesNotMatch(styles, /\.stream-block-pending\.is-(?:table|mermaid|chart) \{[^}]*min-height:/);
});

test("Mermaid rendering reuses a bounded theme-and-source cache", async () => {
  const renderer = await read("../src/components/InteractiveResponse.tsx");

  assert.match(renderer, /const mermaidRenderCache = new Map<string, MermaidRenderResult>\(\);/);
  assert.match(renderer, /const mermaidRenderCacheLimit = 24;/);
  assert.match(renderer, /const cachedResult = mermaidRenderCache\.get\(cacheKey\);/);
  assert.match(renderer, /if \(mermaidRenderCache\.size > mermaidRenderCacheLimit\)/);
});

test("programmatic follow scrolls do not restart persistence and scrollbar timers", async () => {
  const [streaming, scrollbar] = await Promise.all([
    read("../src/streaming-ui.ts"),
    read("../src/scrollbar-activity.ts"),
  ]);

  assert.match(streaming, /container\.dataset\.programmaticScroll = "true";/);
  assert.match(streaming, /performance\.now\(\) <= programmaticScrollUntilRef\.current/);
  assert.match(scrollbar, /if \(element\.dataset\.programmaticScroll === "true"\) \{\s*return;/);
});
