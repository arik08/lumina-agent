import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("write file shows a filename and token-proportional cumulative meter", async () => {
  const [app, types, workspace, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/api-types.ts"),
    read("../src/use-lumina-workspace.ts"),
    read("../src/styles.css"),
  ]);

  assert.match(types, /"tool_progress"/);
  assert.match(types, /tokens: number;\s+lines: number;\s+fileName\?: string;/s);
  assert.match(workspace, /event\.type === "tool_progress"/);
  assert.match(app, /WRITE FILE · \{activeWriteFileName \?\? "파일명 확인 중"\}/);
  assert.match(app, /execution\.progress\.tokens\.toLocaleString\(\)\} 토큰 · \{execution\.progress\.lines\.toLocaleString\(\)\}줄/);
  assert.match(app, /WRITE_FILE_PROGRESS_TOKEN_CAPACITY = 5_000/);
  assert.match(app, /WRITE_FILE_PROGRESS_STAGES = \["blue", "green", "yellow", "red"\]/);
  assert.match(app, /Math\.floor\(\(totalTokens - 1\) \/ WRITE_FILE_PROGRESS_TOKEN_CAPACITY\)/);
  assert.match(app, /style=\{\{ width: `\$\{writeProgress\.percent\}%` \}\}/);
  assert.match(app, /setInterval\(\(\) => setLiveNow\(Date\.now\(\)\), 100\)/);
  assert.match(stylesheet, /\.write-file-stream-meter \{/);
  assert.match(stylesheet, /repeating-linear-gradient/);
  assert.match(stylesheet, /\.write-file-stream-progress \{[^}]*width: 100%/s);
  assert.match(stylesheet, /\.write-file-stream-meter > span \{[^}]*transition: width 180ms/s);
  assert.doesNotMatch(stylesheet, /\.write-file-stream-meter > span \{[^}]*animation:/s);
  assert.match(stylesheet, /\.write-file-stream-progress\.is-green \{ --write-stream-color: var\(--success\); \}/);
  assert.match(stylesheet, /\.write-file-stream-progress\.is-yellow \{/);
  assert.match(stylesheet, /\.write-file-stream-progress\.is-red \{ --write-stream-color: var\(--danger\); \}/);
});
