import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("artifact progress fills each 5,000-token bucket with staged colors", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /TOKEN_PROGRESS_BUCKET_SIZE = 5_000/);
  assert.match(app, /TOKEN_PROGRESS_STAGES = \["blue", "green", "orange", "red"\]/);
  assert.match(app, /\(\(totalTokens - 1\) % TOKEN_PROGRESS_BUCKET_SIZE\) \+ 1/);
  assert.match(app, /Math\.min\(bucketIndex, TOKEN_PROGRESS_STAGES\.length - 1\)/);
  assert.match(app, /artifact-progress-meter/);
  assert.match(app, /artifact-progress-fill/);
  assert.match(app, /style=\{\{ width: `\$\{artifactProgress\.percent\}%` \}\}/);
  assert.match(app, /snapshot\?\.artifactProgress\s+\?\? snapshot\?\.artifactUsage\s+\?\? finalMessage\?\.metadata\?\.artifactUsage/);
  assert.match(app, /artifactUsage\.tokens\.toLocaleString\(\)\} 토큰 · \{artifactUsage\.lines\.toLocaleString\(\)\}줄/);
  assert.match(app, /aria-live=\{terminal \? undefined : "polite"\}/);

  const workspace = await read("../src/use-lumina-workspace.ts");
  assert.match(workspace, /nextSnapshot\.artifactUsage = event\.payload/);

  assert.match(stylesheet, /--artifact-progress-color: var\(--cobalt\)/);
  assert.match(stylesheet, /\.artifact-progress-count \{[^}]*width: 100%/s);
  assert.match(stylesheet, /\.artifact-progress-count \{[^}]*font: 13px\/1\.35 var\(--font-code\)/s);
  assert.match(stylesheet, /\.artifact-progress-count\.is-green \{ --artifact-progress-color: var\(--success\); \}/);
  assert.match(stylesheet, /\.artifact-progress-count\.is-orange \{ --artifact-progress-color: var\(--warning\); \}/);
  assert.match(stylesheet, /\.artifact-progress-count\.is-red \{ --artifact-progress-color: var\(--danger\); \}/);
  assert.match(stylesheet, /\.artifact-progress-fill \{[^}]*transition: width 180ms/s);
  assert.doesNotMatch(stylesheet, /stream-meter-sweep/);
});
