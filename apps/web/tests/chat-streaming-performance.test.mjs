import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("completed chat turns keep stable props and skip offscreen rendering work", async () => {
  const [app, turn, draftStore, styles] = await Promise.all([
    read("../src/App.tsx"),
    read("../src/components/ConversationTurn.tsx"),
    read("../src/run-assistant-draft-store.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(turn, /export const AssistantTurn = memo\(function AssistantTurn/);
  assert.match(turn, /const terminalPresentationReady = terminal && displayedText === sanitizedAssistantText;/);
  assert.match(turn, /const mountedTerminalRef = useRef\(terminalPresentationReady\);/);
  assert.match(turn, /mountedTerminalRef\.current \? "is-terminal" : "is-live-terminal"/);
  assert.match(turn, /className=\{`turn-set \$\{terminalLayoutClass\}`\}/);
  assert.match(turn, /terminalPresentationReady && researchVerification === "unverified"/);
  assert.match(turn, /\{terminalPresentationReady && \(/);
  assert.match(turn, /export function sessionUsageRevision/);
  assert.match(app, /cumulativeUsageCacheRef\.current\?\.revision !== activeSessionUsageRevision/);
  assert.match(turn, /const \[openCalls, setOpenCalls\] = useState<Set<string>>\(new Set\(\)\)/);
  assert.match(turn, /const liveAssistantDraft = useRunAssistantDraft\(turnSet\.runId/);
  assert.match(draftStore, /useSyncExternalStore/);
  assert.doesNotMatch(app, /toggleOpenCall/);
  assert.match(app, /onCopyTool=\{copyTool\}/);
  assert.match(app, /onOpenArtifact=\{openArtifact\}/);
  assert.match(app, /onBranch=\{branchFromMessage\}/);
  assert.match(app, /onShare=\{shareFromMessage\}/);
  assert.match(styles, /\.turn-set\.is-terminal \{[^}]*content-visibility: auto;[^}]*contain-intrinsic-size: auto 520px;/s);
  assert.match(styles, /\.conversation-scroll \{[^}]*overflow-anchor: none;/);
});

test("the live work clock does not rerender the full assistant turn", async () => {
  const [turn, sharedClock] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/shared-clock.ts"),
  ]);

  assert.match(turn, /function WorkDurationLabel\([\s\S]*?useSharedNow\(running\)/);
  assert.match(turn, /function RunActivityTimeline\([\s\S]*?useSharedNow\(timelineRunning\)/);
  assert.match(sharedClock, /const clocks = new Map<number, ClockState>\(\)/);
  assert.match(sharedClock, /state\.listeners\.size === 0/);
  assert.match(sharedClock, /document\.visibilityState !== "visible"/);
  assert.doesNotMatch(turn, /const \[workClock, setWorkClock\]/);
  assert.match(turn, /<WorkDurationLabel[\s\S]*?running=\{!terminal && !awaitingInput\}/);
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
  assert.match(renderer, /const mermaidRenderCacheCharacterBudget = 1_000_000;/);
  assert.match(renderer, /mermaidRenderCache\.size > mermaidRenderCacheLimit[\s\S]*?cachedCharacters > mermaidRenderCacheCharacterBudget/);
  assert.match(renderer, /mermaidRenderQueue = mermaidRenderQueue/);
  assert.match(renderer, /useNearViewport\(containerRef, \{ eager: expanded \}\)/);
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

test("in-memory conversation scroll history uses a bounded LRU cache", async () => {
  const streaming = await read("../src/streaming-ui.ts");

  assert.match(streaming, /const rememberedScrollPositionLimit = 100;/);
  assert.match(streaming, /function rememberScrollPosition[\s\S]*?positions\.delete\(conversationId\);[\s\S]*?while \(positions\.size > rememberedScrollPositionLimit\)/);
  assert.equal((streaming.match(/rememberScrollPosition\(savedPositionsRef\.current/g) ?? []).length, 3);
});
