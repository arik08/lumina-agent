import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("mid-size artifact layout keeps the chat pane uncovered for double-click close", () => {
  assert.match(app, /window\.innerWidth >= 1024 && window\.innerWidth < 1400/);
  assert.match(app, /sidebarAutoCollapsedRef\.current = true;[\s\S]*?setSidebarCollapsed\(true\);[\s\S]*?clampArtifactPaneWidth\(current, true\)/);
  assert.match(app, /onMouseDown=\{\(event\) => \{[\s\S]*?if \(event\.detail > 1\) event\.preventDefault\(\);[\s\S]*?\}\}/);
  assert.match(app, /onDoubleClick=\{\(\) => \{ if \(artifactOpen\) closeArtifact\(\); \}\}/);

  const midSizeRules = styles.match(/@media \(max-width: 1399px\) \{([\s\S]*?)\n\}/)?.[1] ?? "";
  assert.doesNotMatch(midSizeRules, /\.artifact-pane:not\(\.is-fullscreen\).*position: fixed/);
});

test("only mobile artifact layout overlays the chat and auto-collapsed sidebar is restored", () => {
  assert.match(styles, /@media \(max-width: 1023px\)[\s\S]*?\.artifact-pane:not\(\.is-fullscreen\) \{ position: fixed;/);
  assert.match(app, /if \(sidebarAutoCollapsedRef\.current\) \{[\s\S]*?sidebarAutoCollapsedRef\.current = false;[\s\S]*?setSidebarCollapsed\(false\);/);
});
