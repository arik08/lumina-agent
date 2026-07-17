import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");

test("artifact close hides the panel before rewinding browser history", () => {
  assert.match(app, /const closeArtifact = useCallback\(\(\) => \{[\s\S]*?const shouldRewindHistory = artifactHistoryOpenRef\.current;[\s\S]*?finishCloseArtifact\(\);[\s\S]*?if \(shouldRewindHistory\) window\.history\.back\(\);/);
});

test("leaving an artifact-compatible view also closes before history rewind", () => {
  assert.match(app, /if \(!artifactOpen \|\| artifactPaneViews\.has\(mainView\)\) return;[\s\S]*?const shouldRewindHistory = artifactHistoryOpenRef\.current;[\s\S]*?finishCloseArtifact\(\);[\s\S]*?if \(shouldRewindHistory\) window\.history\.back\(\);/);
});
