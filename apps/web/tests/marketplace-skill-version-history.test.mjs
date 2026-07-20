import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("marketplace exposes immutable version history, code diff, and revert-style rollback", async () => {
  const [marketplace, history, styles, api] = await Promise.all([
    read("../src/components/MarketplaceView.tsx"),
    read("../src/components/SkillVersionHistory.tsx"),
    read("../src/components/SkillVersionHistory.css"),
    read("../src/api.ts"),
  ]);

  assert.match(marketplace, /<History size=\{14\} \/> \{versionHistoryOpen \? "패키지 보기" : "버전 이력"\}/);
  assert.match(marketplace, /<SkillVersionHistory[\s\S]*?latestPublishedVersionId=\{selected\.latestPublishedVersionId\}/);
  assert.match(marketplace, /selected\.currentUserRole === "owner"/);
  assert.match(marketplace, /editableChangeSummary\.trim\(\) \|\| "Marketplace 패키지 편집"/);
  assert.match(history, /서로 다른 두 버전을 선택해 변경 내용을 비교해 보세요/);
  assert.match(history, /className=\{`skill-code-line is-\$\{line\.kind\}`\}/);
  assert.match(history, /새 버전으로 복원/);
  assert.match(history, /version\.restoredFromVersionId/);
  assert.match(styles, /\.skill-code-line\.is-add/);
  assert.match(styles, /\.skill-code-line\.is-delete/);
  assert.match(styles, /@media \(max-width: 820px\)/);
  assert.match(api, /\/skills\/\$\{encodeURIComponent\(skillId\)\}\/compare/);
  assert.match(api, /\/skills\/\$\{encodeURIComponent\(skillId\)\}\/rollbacks/);
});
