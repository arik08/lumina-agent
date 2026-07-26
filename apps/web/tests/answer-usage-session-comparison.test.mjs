import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const turnSource = await readFile(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = await readFile(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");

test("usage popover hides cumulative session usage for the first answer", () => {
  assert.match(turnSource, /이번 답변과 세션 누적 토큰 및 예상 비용/);
  assert.match(turnSource, /showSessionUsage \? "이번 답변과 세션 누적 토큰 및 예상 비용" : "이번 답변 토큰 및 예상 비용"/);
  assert.match(turnSource, /showSessionUsage && <th colSpan=\{2\}>세션 누적<\/th>/);
  assert.match(turnSource, /showSessionUsage && <><td className=\{cumulativeRows\[index\]\?\.tone\}>/);
  assert.match(turnSource, /usage=\{runUsage\}[\s\S]*?sessionUsage=\{sessionUsage\}[\s\S]*?showSessionUsage=\{showSessionUsage\}/);
});

test("session usage is accumulated in turn order and passed to each answer", () => {
  assert.match(turnSource, /export function cumulativeSessionUsageByTurnSet/);
  assert.match(turnSource, /cumulativeUsage = addUsage\(cumulativeUsage, answerUsage!\)/);
  assert.match(appSource, /cumulativeSessionUsageByTurnSet\([\s\S]*?activeRuntime\.usageBeforeLoadedTurnSets,[\s\S]*?activeRuntime\.turnSets,[\s\S]*?activeRuntime\.snapshots/);
  assert.match(appSource, /sessionUsage=\{cumulativeUsageByTurnSetId\[turnSet\.id\]\}/);
  assert.match(appSource, /showSessionUsage=\{turnIndex > 0 \|\| activeRuntime\.hasMoreTurnSetsBefore\}/);
});

test("session usage starts with the server aggregate before the loaded page", () => {
  assert.match(turnSource, /initialUsage: Record<string, unknown> \| undefined/);
  assert.match(turnSource, /let cumulativeUsage = usageHasData\(initialUsage\)/);
  assert.match(workspaceSource, /usageBeforeLoadedTurnSets: page\.usageBeforePage/);
  assert.match(workspaceSource, /usageBeforeLoadedTurnSets: page\.usageBeforePage/);
});
