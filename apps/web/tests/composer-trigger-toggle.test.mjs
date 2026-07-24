import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appUrl = new URL("../src/App.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);

test("composer trigger buttons toggle their picker without inserting duplicate tokens", async () => {
  const app = await readFile(appUrl, "utf8");

  assert.match(app, /if \(composerTrigger\?\.trigger === trigger\) \{[\s\S]*?setComposerTrigger\(null\);[\s\S]*?return;[\s\S]*?\}/);
  assert.match(app, /const currentDraft = composerDraftRef\.current;[\s\S]*?const existingTrigger = findComposerTrigger\(currentDraft, caret\);/);
});

test("starting a new conversation closes and resets the composer picker", async () => {
  const app = await readFile(appUrl, "utf8");
  const startNewConversation = app.match(/const startNewConversation = useCallback\(\(\) => \{([\s\S]*?)\n  \}, \[workspace\.resetWarningComposerSettings, workspace\.startNewConversation\]\);/)?.[1] ?? "";

  assert.match(startNewConversation, /setComposerTrigger\(null\);/);
  assert.match(startNewConversation, /setComposerSuggestions\(\[\]\);/);
  assert.match(startNewConversation, /setSuggestionIndex\(0\);/);
  assert.match(startNewConversation, /current !== null && current >= 20_000 \? defaultArtifactOutputTokens : current/);
  assert.match(startNewConversation, /setAnalysisDepth\(\(current\) => current === "deep" \? "auto" : current\);/);
  assert.match(startNewConversation, /setAnswerLength\(\(current\) => current === "detailed" \? "auto" : current\);/);
  assert.match(startNewConversation, /void workspace\.resetWarningComposerSettings\(\);/);
  assert.match(startNewConversation, /workspace\.startNewConversation\(\);/);
  assert.doesNotMatch(startNewConversation, /workspace\.createConversation\(/);
});

test("starting a new conversation resets only warning-colored persisted settings", async () => {
  const workspace = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");
  const resetWarningSettings = workspace.match(/const resetWarningComposerSettings = useCallback\(async \(\) => \{([\s\S]*?)\n  \}, \[persistSettings\]\);/)?.[1] ?? "";

  assert.match(resetWarningSettings, /current\.outputMode === "file"\) patch\.outputMode = "auto"/);
  assert.match(resetWarningSettings, /current\.analysisDepth === "deep"\) patch\.analysisDepth = "auto"/);
  assert.match(resetWarningSettings, /current\.answerLength === "detailed"\) patch\.answerLength = "auto"/);
  assert.match(resetWarningSettings, /current\.execution\.effortId === "high"/);
  assert.match(resetWarningSettings, /patch\.execution = \{ \.\.\.current\.execution, effortId: "auto" \}/);
  assert.match(resetWarningSettings, /Object\.keys\(patch\)\.length > 0\) await persistSettings\(patch\)/);
  assert.doesNotMatch(resetWarningSettings, /providerId|modelKey/);
});

test("a new chat stays local until the first message is sent", async () => {
  const workspace = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");
  const startNewConversation = workspace.match(/const startNewConversation = useCallback\(\(\) => \{([\s\S]*?)\n  \}, \[\]\);/)?.[1] ?? "";
  const sendMessage = workspace.match(/const sendMessage = useCallback\(async \(([\s\S]*?)\n  \}, \[activeConversationId, createConversation/)?.[1] ?? "";

  assert.match(startNewConversation, /setActiveConversationId\(null\);/);
  assert.doesNotMatch(startNewConversation, /api\.conversations\.create|createConversation\(/);
  assert.match(sendMessage, /if \(!conversationId\) \{[\s\S]*?await createConversation\(\);/);
  assert.match(workspace, /openConversation,[\s\S]*?startNewConversation,[\s\S]*?createConversation,/);
});

test("late workspace hydration cannot replace an explicitly requested new chat", async () => {
  const workspace = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");

  assert.match(workspace, /const newConversationPendingRef = useRef\(false\);/);
  assert.match(workspace, /const startNewConversation = useCallback\(\(\) => \{[\s\S]*?newConversationPendingRef\.current = true;[\s\S]*?setActiveConversationId\(null\);/);
  assert.equal((workspace.match(/if \(newConversationPendingRef\.current\) return null;/g) ?? []).length, 2);
  assert.equal((workspace.match(/let conversationId = newConversationPendingRef\.current \? null : activeConversationId;/g) ?? []).length, 2);
  assert.match(workspace, /const openConversation = useCallback\([\s\S]*?newConversationPendingRef\.current = false;/);
});

test("send button tooltip uses the shared global layer", async () => {
  const [app, styles] = await Promise.all([readFile(appUrl, "utf8"), readFile(stylesUrl, "utf8")]);

  assert.match(app, /className=\{`send-button tooltip-control/);
  assert.match(app, /data-tooltip=\{composerShowsStop \? "중지" : "Enter 반영 · Ctrl\+Enter 대기"\}/);
  assert.doesNotMatch(styles, /send-button::after/);
});

test("Skill and MCP suggestions use compact single-line rows", async () => {
  const [app, styles] = await Promise.all([readFile(appUrl, "utf8"), readFile(stylesUrl, "utf8")]);

  assert.match(app, /composer-suggestions is-trigger-list \$\{composerTrigger\.trigger === "\$" \? "is-extension-list" : ""\}/);
  assert.match(app, /className=\{`composer-suggestion-icon kind-\$\{suggestion\.kind\}`\}/);
  assert.match(app, /composerTrigger\.trigger === "\$" && suggestion\.description && <small className="composer-suggestion-description">· \{suggestion\.description\}<\/small>/);
  assert.match(app, /<small className="composer-suggestion-path" data-tooltip=\{suggestion\.subtitle\}>\{suggestion\.subtitle\}<\/small>/);
  assert.doesNotMatch(app, /composerTrigger\.trigger === "@" && <small>\{suggestion\.subtitle\}<\/small>/);
  assert.doesNotMatch(app, /suggestion\.kind === "mcp" \? `MCP ·/);
  assert.match(styles, /\.composer-suggestions\.is-extension-list > button \{[^}]*min-height: 29px;[^}]*padding-block: 2px;/);
  assert.match(styles, /\.composer-suggestions\.is-extension-list \.composer-suggestion-copy \{[^}]*display: flex;[^}]*overflow: hidden;[^}]*white-space: nowrap;/);
  assert.match(styles, /\.composer-suggestions\.is-extension-list \.composer-suggestion-description \{[^}]*min-width: 0;[^}]*flex: 1 1 0;/);
  assert.match(styles, /\.composer-suggestions\.is-extension-list \.composer-suggestion-icon\.kind-skill \{ color: var\(--skill-accent\); \}/);
  assert.match(styles, /\.composer-suggestions\.is-extension-list \.composer-suggestion-icon\.kind-mcp \{ color: var\(--mcp-accent\); \}/);
  assert.match(styles, /\.composer-suggestions\.is-trigger-list \.composer-suggestions-heading small \{[^}]*font-size: 12px;/);
  assert.match(styles, /\.composer-suggestions\.is-trigger-list \.composer-suggestion-copy strong \{[^}]*font-size: 13px;/);
  assert.match(styles, /\.composer-suggestions\.is-trigger-list \.composer-suggestion-copy small \{[^}]*font-size: 12px;/);
  assert.match(styles, /\.composer-suggestions\.is-trigger-list small\.composer-suggestion-path \{[^}]*max-width: min\(42vw, 360px\);[^}]*text-overflow: ellipsis;[^}]*white-space: nowrap;/);
  assert.match(styles, /\.composer-suggestions\.is-trigger-list span\.composer-suggestion-kind \{[^}]*font-size: 12px;/);
  assert.doesNotMatch(styles, /\.composer-suggestions\.is-extension-list [^{]*(?:heading small|copy strong|suggestion-description|suggestion-kind) \{[^}]*font-size:/);
});
