import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("artifact split keeps enough width for the completed answer actions", () => {
  assert.match(app, /const artifactPaneMinWidth = 360;/);
  assert.match(app, /const artifactSplitPaneMinViewport = 1024;/);
  assert.match(app, /const chatPaneMinWidth = 440;/);
  assert.match(app, /window\.innerWidth - sidebarWidth - chatPaneMinWidth/);
  assert.match(app, /expandedChatWidth <= chatPaneMinWidth/);
  assert.match(app, /expandedChatWidth > chatPaneMinWidth/);
  assert.match(app, /window\.innerWidth < artifactSplitPaneMinViewport/);

  assert.match(styles, /\.app-shell\.has-artifact \{[\s\S]*?minmax\(440px, 1fr\)/);
  assert.match(styles, /\.app-shell\.has-artifact\.is-sidebar-collapsed \{[^}]*minmax\(440px, 1fr\)/);
  assert.match(styles, /\.artifact-resize-handle \{[\s\S]*?z-index: 5;/);
  assert.match(styles, /\.artifact-resize-handle::after \{[^}]*inset: 0 auto 0 5px;[^}]*width: 1px;/);
  assert.doesNotMatch(styles, /\.artifact-resize-handle[^}]*box-shadow/);
  assert.match(styles, /@media \(max-width: 1023px\) \{\s*\.artifact-resize-handle \{ display: none; \}/);
  assert.doesNotMatch(styles, /@media \(max-width: 1399px\) \{\s*\.artifact-resize-handle/);
});
