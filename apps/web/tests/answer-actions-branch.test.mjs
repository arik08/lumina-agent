import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");

test("answer actions place usage first and branch immediately before share", () => {
  const actions = turnSource.match(/<div className="answer-actions"[\s\S]*?<\/div>/)?.[0] ?? "";

  const usageIndex = actions.indexOf("<UsageCostPopover");
  const copyIndex = actions.indexOf('aria-label="답변 복사"');
  const branchIndex = actions.indexOf('aria-label="이 답변까지 새 채팅으로 분기"');
  const shareIndex = actions.indexOf('aria-label="답변 공유"');

  assert.ok(usageIndex >= 0 && usageIndex < copyIndex, "usage control should be the leftmost answer action");
  assert.ok(branchIndex >= 0 && branchIndex < shareIndex, "branch should be immediately before share");
  assert.match(actions.slice(branchIndex, shareIndex), /GitBranch size=\{16\}/);
});

test("answer branching sends the clicked assistant message and activates the created session", () => {
  assert.match(turnSource, /await onBranch\(finalMessage\.id\)/);
  assert.match(appSource, /workspace\.branchConversation\(workspace\.activeConversationId, anchorMessageId\)/);
  assert.match(workspaceSource, /branchConversation = useCallback\(async \(conversationId: string, anchorMessageId\?: string \| null\)/);
  assert.match(workspaceSource, /api\.conversations\.branch\(conversationId, resolvedAnchorMessageId\)/);
  assert.match(workspaceSource, /setActiveConversationId\(created\.id\)/);
});
