import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("assistant text deltas bypass the root workspace state tree", async () => {
  const [workspace, draftStore, turn] = await Promise.all([
    read("../src/use-lumina-workspace.ts"),
    read("../src/run-assistant-draft-store.ts"),
    read("../src/components/ConversationTurn.tsx"),
  ]);

  assert.match(workspace, /if \(event\.type === "assistant_text_delta"\) \{[\s\S]*appendRunAssistantDraft/);
  assert.match(workspace, /snapshot\.lastSequence >= knownEventSequence[\s\S]*setRunAssistantDraft/);
  assert.match(draftStore, /useSyncExternalStore/);
  assert.match(turn, /useRunAssistantDraft\(turnSet\.runId/);
  assert.match(turn, /const \[openCalls, setOpenCalls\] = useState<Set<string>>/);
});

test("stream reveal and Markdown parsing only process appended input", async () => {
  const [streamingUi, streamingMarkdown] = await Promise.all([
    read("../src/streaming-ui.ts"),
    read("../src/streaming-markdown.ts"),
  ]);

  assert.match(streamingUi, /pendingCharactersRef/);
  assert.match(streamingUi, /targetText\.slice\(previousTarget\.length\)/);
  assert.doesNotMatch(streamingUi, /Array\.from\(target\.slice/);
  assert.equal((streamingUi.match(/Array\.from\(/g) ?? []).length, 2);
  assert.match(streamingMarkdown, /!input\.startsWith\(previous\.input\)/);
  assert.match(streamingMarkdown, /scanPosition/);
  assert.match(streamingMarkdown, /scanner\.source\.indexOf\("\\n", scanPosition\)/);
});

test("deep-analysis events and large fixed-height lists update isolated windows", async () => {
  const [view, eventStore, virtualList] = await Promise.all([
    read("../src/workspace-frontends/deep-analysis/DeepAnalysisView.tsx"),
    read("../src/workspace-frontends/deep-analysis/mission-event-store.ts"),
    read("../src/use-fixed-virtual-list.ts"),
  ]);

  assert.match(eventStore, /useSyncExternalStore/);
  assert.match(eventStore, /previousProgressIndex/);
  assert.match(eventStore, /const currentSequences = new Set\(current\.map\(\(event\) => event\.sequence\)\)/);
  assert.match(eventStore, /events\.filter\(\(event\) => !currentSequences\.has\(event\.sequence\)\)/);
  assert.match(view, /const shownWorkflowNodeByKey = useMemo\([\s\S]*new Map/);
  assert.match(view, /pendingNodeDragRef\.current = \{[\s\S]*requestAnimationFrame\(applyPendingNodeDrag\)/);
  assert.match(virtualList, /const start = virtualized[\s\S]*Math\.floor\(viewport\.scrollTop \/ rowHeight\) - overscan/);
  assert.match(virtualList, /ResizeObserver/);
});

test("feature clients and optional renderers stay outside the initial API surface", async () => {
  const [api, featureApi, renderer] = await Promise.all([
    read("../src/api.ts"),
    read("../src/feature-api.ts"),
    read("../src/components/InteractiveResponse.tsx"),
  ]);

  assert.doesNotMatch(api, /deepAnalysis:\s*\{/);
  assert.match(featureApi, /export const deepAnalysisApi = \{/);
  assert.match(renderer, /import\("\.\/echarts-lean-runtime"\)/);
  assert.match(renderer, /canUseLeanChartRuntime/);
  assert.doesNotMatch(renderer, /requestIdleCallback\(preloadMermaid/);
});

test("syntax highlighting runs in a worker and collapses superseded editor jobs", async () => {
  const [syntaxCode, client, worker] = await Promise.all([
    read("../src/components/SyntaxCode.tsx"),
    read("../src/components/syntax-highlight-client.ts"),
    read("../src/components/syntax-highlight.worker.ts"),
  ]);

  assert.match(client, /new Worker\(new URL\("\.\/syntax-highlight\.worker\.ts", import\.meta\.url\)/);
  assert.match(worker, /import hljs from "highlight\.js\/lib\/common"/);
  assert.match(syntaxCode, /runningRef/);
  assert.match(syntaxCode, /queuedRef\.current = \{ value, language \}/);
  assert.match(syntaxCode, /latestRef\.current\.value === job\.value/);
});
