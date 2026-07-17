import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");
const actionIconsSource = await readFile(new URL("../src/components/ActionIcons.tsx", import.meta.url), "utf8");

test("answer actions place usage first and branch immediately before share", () => {
  const actions = turnSource.match(/<div className="answer-actions"[\s\S]*?<\/div>/)?.[0] ?? "";

  const usageIndex = actions.indexOf("<UsageCostPopover");
  const copyIndex = actions.indexOf('aria-label="답변 복사"');
  const branchIndex = actions.indexOf('aria-label="이 답변까지 새 채팅으로 분기"');
  const shareIndex = actions.indexOf('aria-label="답변 공유"');

  assert.ok(usageIndex >= 0 && usageIndex < copyIndex, "usage control should be the leftmost answer action");
  assert.ok(branchIndex >= 0 && branchIndex < shareIndex, "branch should be immediately before share");
  assert.match(actions.slice(branchIndex, shareIndex), /BranchFromHereIcon size=\{16\}/);
});

test("branch icon uses the attached split-arrow shape and every share action uses the rotated shared icon", () => {
  assert.match(actionIconsSource, /createLucideIcon\("BranchFromHere"/);
  assert.match(actionIconsSource, /d: "M4 12h8"/);
  assert.match(actionIconsSource, /d: "M12 12 22 2"/);
  assert.match(actionIconsSource, /d: "M16 2h6v6"/);
  assert.match(actionIconsSource, /d: "m12 12 10 10"/);
  assert.match(actionIconsSource, /d: "M16 22h6v-6"/);
  assert.doesNotMatch(actionIconsSource, /\["circle"/);
  assert.match(actionIconsSource, /transform: "rotate\(90deg\)"/);
  assert.match(turnSource, /aria-label="답변 공유"[\s\S]*?<ShareActionIcon size=\{16\}/);
  assert.match(appSource, /aria-label="Artifact 공유 링크 복사"[\s\S]*?<ShareActionIcon size=\{17\}/);
  assert.match(turnSource, /kind === "mermaid" \? <BranchFromHereIcon size=\{18\}/);
  assert.match(appSource, /title: "업무 흐름 다이어그램"[\s\S]*?icon: BranchFromHereIcon/);
  assert.doesNotMatch(`${turnSource}\n${appSource}`, /\bGitBranch\b/);
  assert.doesNotMatch(`${turnSource}\n${appSource}`, /<Share2\b/);
});

test("answer branching sends the clicked assistant message and activates the created session", () => {
  assert.match(turnSource, /await onBranch\(finalMessage\.id\)/);
  assert.match(appSource, /workspace\.branchConversation\(workspace\.activeConversationId, anchorMessageId\)/);
  assert.match(workspaceSource, /branchConversation = useCallback\(async \(conversationId: string, anchorMessageId\?: string \| null\)/);
  assert.match(workspaceSource, /api\.conversations\.branch\(conversationId, resolvedAnchorMessageId\)/);
  assert.match(workspaceSource, /setActiveConversationId\(created\.id\)/);
});
