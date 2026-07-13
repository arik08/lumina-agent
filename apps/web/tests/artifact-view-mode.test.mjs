import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appPath = new URL("../src/App.tsx", import.meta.url);

test("artifact pane stays available only in agent and library views", async () => {
  const app = await readFile(appPath, "utf8");

  assert.match(app, /const artifactPaneViews = new Set<MainView>\(\["chat", "library"\]\);/);
  assert.match(app, /const artifactPaneVisible = artifactOpen && artifactPaneViews\.has\(mainView\);/);
  assert.match(app, /if \(!artifactOpen \|\| artifactPaneViews\.has\(mainView\)\) return;[\s\S]*?finishCloseArtifact\(\);/);
  assert.match(app, /className=\{`app-shell \$\{artifactPaneVisible \? "has-artifact" : ""\}/);
  assert.match(app, /\{artifactPaneVisible && \(\s*<aside className=\{`artifact-pane/);
});
