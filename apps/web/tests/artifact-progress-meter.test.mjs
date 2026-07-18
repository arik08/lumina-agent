import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("artifact progress distinguishes document size, target, and model output usage", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/styles.css"),
  ]);

  assert.match(app, /TOKEN_PROGRESS_BUCKET_SIZE = 5_000/);
  assert.match(app, /TOKEN_PROGRESS_STAGES = \["blue", "green", "orange", "red"\]/);
  assert.match(app, /\(\(totalTokens - 1\) % TOKEN_PROGRESS_BUCKET_SIZE\) \+ 1/);
  assert.match(app, /Math\.min\(bucketIndex, TOKEN_PROGRESS_STAGES\.length - 1\)/);
  assert.match(app, /tokenBucketProgress\(artifactUsage\.tokens, artifactUsage\.targetTokens\)/);
  assert.match(app, /Math\.min\(100, \(totalTokens \/ normalizedTarget\) \* 100\)/);
  assert.match(app, /artifact-progress-meter/);
  assert.match(app, /artifact-progress-fill/);
  assert.match(app, /style=\{\{ width: `\$\{artifactProgress\.percent\}%` \}\}/);
  assert.match(app, /snapshot\?\.artifactProgress\s+\?\? snapshot\?\.artifactUsage\s+\?\? finalMessage\?\.metadata\?\.artifactUsage/);
  assert.match(app, /const hasCreateReportExecution = tools\.some\([\s\S]*?includes\("create_report"\)[\s\S]*?\);/);
  assert.match(app, /\{hasCreateReportExecution && artifactUsage && artifactProgress && \(/);
  assert.match(app, /artifactUsage\.estimated === false \? "문서 약" : "작성 중 약"/);
  assert.match(app, /artifactUsage\?\.modelOutputTokens \?\? 0/);
  assert.match(app, /모델 출력 누계 \{liveModelOutputTokens\.toLocaleString\(\)\}토큰/);
  assert.match(app, /aria-label="작성 중 토큰과 모델 출력 누계의 차이"/);
  assert.match(app, /data-tooltip="작성 중은 현재 문서 본문의 추정량이고, 모델 출력 누계는 이번 작업의 모든 모델 응답을 합산한 값입니다\."/);
  assert.match(app, /artifactUsage\.targetTokens \? <span className="artifact-progress-target"> · 목표/);
  assert.match(app, /aria-live=\{terminal \? undefined : "polite"\}/);

  const workspace = await read("../src/use-lumina-workspace.ts");
  assert.match(workspace, /nextSnapshot\.artifactUsage = event\.payload/);
  assert.match(workspace, /event\.payload\.fileCreationRequested === false/);
  assert.match(workspace, /nextSnapshot\.artifactProgress = null/);
  assert.match(workspace, /nextSnapshot\.artifactUsage = null/);

  assert.match(stylesheet, /--artifact-progress-color: var\(--cobalt\)/);
  assert.match(stylesheet, /\.artifact-progress-count \{[^}]*width: 100%/s);
  assert.match(stylesheet, /\.artifact-progress-count \{[^}]*container-type: inline-size/s);
  assert.match(stylesheet, /\.artifact-progress-count \{[^}]*font: 13px\/1\.35 var\(--font-code\)/s);
  assert.match(stylesheet, /\.artifact-progress-heading \.artifact-model-output \{[^}]*color: inherit/s);
  assert.match(stylesheet, /\.artifact-model-output-help \{[^}]*font: inherit/s);
  assert.doesNotMatch(stylesheet, /\.artifact-progress-heading \.artifact-model-output \{[^}]*var\(--faint\)/s);
  assert.match(stylesheet, /\.artifact-progress-count\.is-green \{ --artifact-progress-color: var\(--success\); \}/);
  assert.match(stylesheet, /\.artifact-progress-count\.is-orange \{ --artifact-progress-color: color-mix\(in srgb, #f46d43 55%, var\(--surface\)\); \}/);
  assert.match(stylesheet, /\.artifact-progress-count\.is-red \{ --artifact-progress-color: var\(--danger\); \}/);
  assert.match(stylesheet, /\.artifact-progress-fill \{[^}]*transition: width 100ms linear/s);
  assert.match(stylesheet, /@container \(max-width: 560px\) \{\s*\.artifact-progress-target \{ display: none; \}\s*\}/);
  assert.doesNotMatch(stylesheet, /stream-meter-sweep/);
});
