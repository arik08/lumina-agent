import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("artifact progress uses a full-width indeterminate meter without a fake token ceiling", async () => {
  const [app, stylesheet] = await Promise.all([
    read("../src/components/ConversationTurn.tsx"),
    read("../src/styles.css"),
  ]);

  assert.doesNotMatch(app, /ARTIFACT_TOKEN_SEGMENT/);
  assert.doesNotMatch(app, /\/ 5,000/);
  assert.match(app, /artifact-progress-meter/);
  assert.match(app, /artifact-progress-fill/);
  assert.match(app, /artifactProgress\.tokens\.toLocaleString\(\)\} 토큰 · \{snapshot\.artifactProgress\.lines\.toLocaleString\(\)\}줄/);

  assert.match(stylesheet, /--artifact-progress-color: var\(--cobalt\)/);
  assert.match(stylesheet, /\.artifact-progress-count \{[^}]*width: 100%/s);
  assert.match(stylesheet, /\.artifact-progress-fill \{[^}]*width: 36%[^}]*animation: stream-meter-sweep/s);
});
