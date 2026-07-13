import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");

test("artifact split keeps enough width for the completed answer actions", () => {
  assert.match(app, /const chatPaneMinWidth = 440;/);
  assert.match(app, /window\.innerWidth - sidebarWidth - chatPaneMinWidth/);
  assert.match(app, /expandedChatWidth <= chatPaneMinWidth/);
  assert.match(app, /expandedChatWidth > chatPaneMinWidth/);

  assert.match(styles, /\.app-shell\.has-artifact \{[\s\S]*?minmax\(440px, 1fr\)/);
  assert.match(styles, /\.app-shell\.has-artifact\.is-sidebar-collapsed \{[^}]*minmax\(440px, 1fr\)/);
});
