import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const workspaceSource = readFileSync(new URL("../src/use-lumina-workspace.ts", import.meta.url), "utf8");
const conversationTurnSource = readFileSync(new URL("../src/components/ConversationTurn.tsx", import.meta.url), "utf8");
const helpCenterSource = readFileSync(new URL("../src/components/HelpCenterView.tsx", import.meta.url), "utf8");
const projectFilesSource = readFileSync(new URL("../src/components/ProjectFilesView.tsx", import.meta.url), "utf8");

test("routine Run, save, copy, read, and delete actions stay quiet", () => {
  for (const message of [
    "새 Run을 시작했습니다.",
    "Run을 일시 정지했습니다.",
    "Run을 재개했습니다.",
    "작업을 중지했습니다.",
    "전체 Tool 로그를 복사했습니다.",
    "Artifact 다운로드를 시작했습니다.",
    "모든 알림을 읽음으로 표시했습니다.",
    "알림을 모두 삭제했습니다.",
  ]) {
    assert.doesNotMatch(appSource, new RegExp(message));
  }

  assert.doesNotMatch(workspaceSource, /setNotice\("세션을 삭제했습니다\."\)/);
  assert.doesNotMatch(conversationTurnSource, /onToast\([^\n]*(?:복사했습니다|저장했습니다|게시했습니다)/);
  assert.doesNotMatch(helpCenterSource, /onToast/);
  assert.doesNotMatch(projectFilesSource, /onToast/);
});

test("errors, guard states, and partial failures still notify the user", () => {
  assert.match(appSource, /showToast\("요청 내용을 입력해 주세요\."\)/);
  assert.match(appSource, /showToast\("Tool 메시지를 복사하지 못했습니다\."\)/);
  assert.match(workspaceSource, /if \(failedCount\) setNotice\(`\$\{succeeded\.length\}개 세션을 삭제했고 \$\{failedCount\}개는 삭제하지 못했습니다\.`\)/);
  assert.match(conversationTurnSource, /onToast\("답변을 Markdown Artifact로 저장하지 못했습니다\."\)/);
});
